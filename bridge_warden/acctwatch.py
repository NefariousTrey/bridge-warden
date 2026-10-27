"""ACCTWATCH (2026-10-26): watch the PayPal account itself, not just Bridge Warden's own gate. SANDBOX ONLY.

Bridge Warden's gate only sees money moves that go through it. A thief who logs in to PayPal directly is invisible
to it. This module listens for PayPal's own webhooks (event-driven, no polling delay) and feeds anything suspicious
into the same red light + alert path (alerts.py: in-app always, call if set up, free email if set up).

Every webhook is:
  1. size-capped (64 KB), header-checked (all 5 PAYPAL-* headers, SHA256withRSA, a PayPal sandbox cert host),
  2. inside a transmission-time window (default 300 s) and never seen before (transmission id),
  3. VERIFIED by PayPal itself: POST /v1/notifications/verify-webhook-signature with the RAW body (re-serializing
     can break the signature). Anything not "SUCCESS" is refused (400). Simulator "mock" events cannot be verified,
  4. handled once per event id (persisted), then classified. Suspicious = a BLOCK record in the history
     (action id "pp-<event id>", agent "paypal-webhook"), so the light goes red, then the alert fires AT ONCE in the
     same request thread. Outside events are BLOCK only: never HOLD, because approving a hold executes money.
Timings (received -> verified -> checked -> call request sent) go to the history (acctwatch_timing) and
acctwatch_latency.jsonl.

Dev mode: refused with 503 and NO PayPal call. Binds 127.0.0.1 only; a public URL (and registering the webhook
with PayPal) is the owner's decision. The backup Transaction Search poller is OFF by default; PayPal says new
transactions can take up to ~3 hours to show there, so it is a safety net, not an alarm.

One automatic action, OFF by default (BW_ACCTWATCH_AUTOCANCEL=on): cancel an UNCLAIMED payout item that Bridge
Warden did not send (POST /v1/payments/payouts-item/{id}/cancel; money returns to the sender). For everything else
the alert tells the owner what to do; Bridge Warden cannot lock a PayPal account.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import net
from .alerts import Alerts, RetryQueue
from .gate import proposal_hash
from .guard import canonical_amount
from .models import BLOCK, Finding, ProposedAction, Verdict

MAX_BODY = 64 * 1024
WEBHOOK_PATH = "/paypal/webhook"
HEADERS = ("PAYPAL-AUTH-ALGO", "PAYPAL-CERT-URL", "PAYPAL-TRANSMISSION-ID", "PAYPAL-TRANSMISSION-SIG",
           "PAYPAL-TRANSMISSION-TIME")
CERT_HOSTS = {"api.sandbox.paypal.com", "api-m.sandbox.paypal.com"}   # sandbox only
EVENT_ID = re.compile(r"^WH-[A-Za-z0-9-]{8,80}$")
TID = re.compile(r"^[A-Za-z0-9-]{8,80}$")
ITEM_ID = re.compile(r"^[A-Z0-9]{8,40}$")
VERIFY_PATH = "/v1/notifications/verify-webhook-signature"

# Event names checked against PayPal's webhook event list (developer.paypal.com/api/rest/webhooks/event-names/)
ALWAYS_RED = {
    "CUSTOMER.DISPUTE.CREATED": "Someone opened a dispute (chargeback) on your PayPal.",
    "RISK.DISPUTE.CREATED": "Someone opened a dispute on your PayPal.",
    "PAYMENT.CAPTURE.REVERSED": "PayPal took back a payment you received (reversal).",
    "PAYMENT.CAPTURE.DENIED": "A payment on your PayPal was denied.",
    "PAYMENT.CAPTURE.DECLINED": "A payment on your PayPal was declined.",
    "PAYMENT.SALE.REVERSED": "PayPal took back a sale (reversal).",
    "PAYMENT.SALE.DENIED": "A sale on your PayPal was denied.",
    "CUSTOMER.ACCOUNT-LIMITATION.ADDED": "PayPal put a limitation on your account.",
    "CUSTOMER.ACCOUNT-LIMITATION.ESCALATED": "PayPal made a limitation on your account stricter.",
    "CUSTOMER.ACCOUNT-LIMITATION.UPDATED": "PayPal changed a limitation on your account.",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED": "PayPal blocked a payout from your account.",
    "PAYMENT.PAYOUTSBATCH.DENIED": "PayPal denied a payout batch from your account.",
    "CHECKOUT.PAYMENT-APPROVAL.REVERSED": "A checkout approval on your PayPal was reversed.",
}
MONEY_OUT = {   # red unless Bridge Warden itself sent it
    "PAYMENT.CAPTURE.REFUNDED": ("refund", "A refund went out that Bridge Warden did not send."),
    "PAYMENT.SALE.REFUNDED": ("refund", "A refund went out that Bridge Warden did not send."),
    "PAYMENT.REFUND.PENDING": ("refund", "A refund is going out that Bridge Warden did not send."),
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED": ("payout", "Money was paid out that Bridge Warden did not send."),
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED": ("payout", "A payout Bridge Warden did not send is waiting to be claimed."),
    "PAYMENT.PAYOUTS-ITEM.HELD": ("payout", "A payout Bridge Warden did not send is on hold at PayPal."),
    "PAYMENT.PAYOUTSBATCH.PROCESSING": ("payout", "A payout batch Bridge Warden did not send is being processed."),
    "PAYMENT.PAYOUTSBATCH.SUCCESS": ("payout", "A payout batch Bridge Warden did not send went out."),
}
MONEY_IN = {"PAYMENT.CAPTURE.COMPLETED", "PAYMENT.SALE.COMPLETED"}
NEXT_STEP = ("Open PayPal yourself (type paypal.com), check Activity, change your password, turn on two-step login, "
             "and log out of devices you do not know. For a dispute, answer it in the PayPal Resolution Center.")


def _env(env, k, default=""):
    return str((os.environ if env is None else env).get(k, default) or default).strip()


def _on(v) -> bool:
    return str(v).strip().lower() in ("1", "on", "true", "yes")


# ---------------------------------------------------------------- reading an event
def _money(res: dict):
    for a in (res.get("amount"), res.get("dispute_amount"), (res.get("payout_item") or {}).get("amount"),
              (res.get("batch_header") or {}).get("amount")):
        if isinstance(a, dict):
            v, c = a.get("value", a.get("total")), a.get("currency_code", a.get("currency", "USD"))
            try:
                return canonical_amount(str(v), str(c)), str(c)
            except Exception:
                continue
    return "0.00", "USD"


def _ids(res: dict) -> set:
    bh = res.get("batch_header") or {}
    pi = res.get("payout_item") or {}
    vals = {res.get("id"), res.get("payout_item_id"), res.get("payout_batch_id"), res.get("transaction_id"),
            bh.get("payout_batch_id"), bh.get("sender_batch_header", {}).get("sender_batch_id") if isinstance(
                bh.get("sender_batch_header"), dict) else None, pi.get("sender_item_id"),
            (res.get("sender_batch_header") or {}).get("sender_batch_id") if isinstance(
                res.get("sender_batch_header"), dict) else None}
    return {str(v) for v in vals if isinstance(v, (str, int)) and str(v)}


def ours(gate) -> set:
    """Every id Bridge Warden's own executed moves produced (capture, batch, item, refund ids) + its action ids."""
    out = set()
    for r in gate.audit.records():
        if r.get("event") in ("executing", "executed"):
            out.add(str(r.get("action_id")))
            for v in (r.get("result") or {}).values():
                if isinstance(v, (str, int)) and str(v):
                    out.add(str(v))
    return out


def classify(event: dict, gate, source: str = "webhook") -> dict:
    """{"red": bool, "reason", "action", "amount", "currency", "kind"} for one PayPal event (or poll row)."""
    et = str(event.get("event_type") or "")
    res = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    amount, cur = _money(res)
    base = {"event_type": et, "amount": amount, "currency": cur, "source": source}
    if et in ALWAYS_RED:
        return {**base, "red": True, "reason": ALWAYS_RED[et], "action": "create_order", "kind": "always"}
    if et in MONEY_OUT:
        action, why = MONEY_OUT[et]
        mine = bool(_ids(res) & ours(gate)) or any(str(x).startswith(("act-", "pp-")) and x in ours(gate)
                                                    for x in _ids(res))
        if mine:
            return {**base, "red": False, "reason": "Bridge Warden's own move.", "action": action, "kind": "ours"}
        return {**base, "red": True, "reason": why, "action": action, "kind": "money_out"}
    if et in MONEY_IN:
        try:
            hard = canonical_amount(str(gate.engine.p.get("hard_max", "0")), cur)
            big = float(amount) > float(hard) > 0
        except Exception:
            big = False
        if big:
            return {**base, "red": True, "kind": "money_in",
                    "reason": "An unusually large payment came in. Scammers send too much, then ask for some back.",
                    "action": "create_order"}
        return {**base, "red": False, "reason": "Money came in.", "action": "create_order", "kind": "money_in"}
    return {**base, "red": False, "reason": "Recorded for your history.", "action": "create_order", "kind": "info"}


def action_id_for(event_id: str) -> str:
    return "pp-" + re.sub(r"[^A-Za-z0-9-]", "", str(event_id))[:70]


def batch_id_of(res: dict) -> str:
    """The PayPal payout batch id an event belongs to ("" if none). Item and batch events share it."""
    bh = res.get("batch_header") if isinstance(res.get("batch_header"), dict) else {}
    pi = res.get("payout_item") if isinstance(res.get("payout_item"), dict) else {}
    for v in (res.get("payout_batch_id"), bh.get("payout_batch_id"), pi.get("payout_batch_id")):
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9-]{4,80}", v):
            return v
    return ""


def alert_key(res: dict) -> str:
    """E2EFIX (2026-10-27): what ONE alert covers. One stranger payout sends several webhooks (batch PROCESSING,
    batch SUCCESS, item SUCCEEDED/UNCLAIMED): all share the payout batch id, so they are ONE alert and ONE call.
    Anything else: the related resource id (a dispute, a capture). "" = no id, alert on its own."""
    b = batch_id_of(res)
    if b:
        return "batch:" + b
    for v in (res.get("id"), res.get("transaction_id"), res.get("dispute_id")):
        if isinstance(v, (str, int)) and re.fullmatch(r"[A-Za-z0-9-]{4,80}", str(v)):
            return "res:" + str(v)
    return ""


def raise_red(gate, event_id: str, c: dict, payee: str = "PayPal (outside Bridge Warden)") -> str:
    """Write proposed + verdict(BLOCK) so dashboard.moves shows it as blocked and the light turns red."""
    aid = action_id_for(event_id)
    a = ProposedAction(c["action"], c["amount"], c["currency"], payee=payee[:120],
                       description=f"Outside Bridge Warden ({c['event_type']}): {c['reason']} Money may already have "
                                   f"moved. {NEXT_STEP}"[:600],
                       agent_id="paypal-" + c["source"], action_id=aid)
    pd = a.to_dict()
    h = proposal_hash(pd)
    v = Verdict(aid, BLOCK, 100, [Finding("outside_paypal", BLOCK, c["reason"] + " " + NEXT_STEP, 100)])
    gate.audit.write("proposed", action_id=aid, proposal=pd, proposal_hash=h)
    gate.audit.write("verdict", action_id=aid, verdict=v.to_dict(), proposal_hash=h,
                     clock_at=gate.clock().isoformat())
    return aid


# ---------------------------------------------------------------- PayPal's own signature check
class PayPalVerifier:
    """POST /v1/notifications/verify-webhook-signature (sandbox). Needs the sandbox app + BW_PAYPAL_WEBHOOK_ID."""

    def __init__(self, client, webhook_id: str, sender=None):
        self.client, self.webhook_id, self._send = client, webhook_id, sender or net.request

    def __call__(self, h: dict, raw: bytes) -> bool:
        if not self.webhook_id:
            return False
        meta = {"auth_algo": h["PAYPAL-AUTH-ALGO"], "cert_url": h["PAYPAL-CERT-URL"],
                "transmission_id": h["PAYPAL-TRANSMISSION-ID"], "transmission_sig": h["PAYPAL-TRANSMISSION-SIG"],
                "transmission_time": h["PAYPAL-TRANSMISSION-TIME"], "webhook_id": self.webhook_id}
        body = (json.dumps(meta)[:-1] + ', "webhook_event": ' + raw.decode("utf-8") + "}").encode()   # RAW event
        code, _, out = self._send("POST", self.client.base + VERIFY_PATH,
                                  {"Authorization": "Bearer " + self.client.token(),
                                   "Content-Type": "application/json"}, body, 10)
        try:
            return code == 200 and json.loads(out or b"{}").get("verification_status") == "SUCCESS"
        except ValueError:
            return False


# ---------------------------------------------------------------- the watcher
class Store(RetryQueue):
    def __init__(self, path):
        self.path = Path(path)


class AccountWatch:
    def __init__(self, gate, verifier=None, alerts=None, env=None, clock=None, cancel=None, reader=None):
        self.gate, self.env = gate, (os.environ if env is None else env)
        self.verifier = verifier
        self.alerts = alerts
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.window = int(_env(self.env, "BW_ACCTWATCH_REPLAY_SECONDS", "300") or 300)
        self.autocancel = _on(_env(self.env, "BW_ACCTWATCH_AUTOCANCEL", "off"))
        self.cancel = cancel      # fn(item_id) -> dict ; None = no cancel possible
        self.reader = reader      # fn(batch_id) -> {"batch_status", "item_status"} ; None = gate.paypal, if any
        # One alert per payout batch (or related resource) inside this window. Saved in acctwatch_state.json,
        # so a restart does not ring again for the same batch.
        try:
            self.dedupe_window = max(60, int(_env(self.env, "BW_ACCTWATCH_DEDUPE_SECONDS", "86400") or 86400))
        except ValueError:
            self.dedupe_window = 86400
        folder = Path(gate.audit.path).parent
        self.state = Store(folder / "acctwatch_state.json")
        self.latency_log = folder / "acctwatch_latency.jsonl"
        self._lk = threading.Lock()

    def _alerts(self):
        return self.alerts if self.alerts is not None else Alerts(self.gate)

    # -- 1..4: the checks. Returns (http code, reason, event or None)
    def accept(self, headers: dict, raw: bytes, mark: dict):
        if self.gate.dev_lock():
            return 503, "dev mode: PayPal is not contacted", None
        h = {k.upper(): str(v) for k, v in headers.items()}
        if any(not h.get(k) for k in HEADERS):
            return 400, "missing PayPal headers", None
        if h["PAYPAL-AUTH-ALGO"] != "SHA256withRSA":
            return 400, "wrong algorithm", None
        cu = urlsplit(h["PAYPAL-CERT-URL"])
        if cu.scheme != "https" or (cu.hostname or "").lower() not in CERT_HOSTS:
            return 400, "cert not from PayPal sandbox", None
        tid = h["PAYPAL-TRANSMISSION-ID"]
        if not TID.match(tid):
            return 400, "bad transmission id", None
        try:
            t = datetime.fromisoformat(h["PAYPAL-TRANSMISSION-TIME"].replace("Z", "+00:00"))
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except ValueError:
            return 400, "bad transmission time", None
        now = self.clock()
        if abs((now - t).total_seconds()) > self.window:
            return 400, "too old or from the future (replay?)", None
        try:
            event = json.loads(raw.decode("utf-8"))
            assert isinstance(event, dict)
        except Exception:
            return 400, "not JSON", None
        eid = str(event.get("id") or "")
        if not EVENT_ID.match(eid):
            return 400, "bad event id", None
        if tid in self.state.read().get("tids", {}):
            return 409, "replayed transmission", None
        if self.verifier is None:
            return 503, "not set up (no webhook id)", None
        try:
            ok = self.verifier(h, raw)
        except Exception:
            ok = False
        mark["t_verified"] = time.perf_counter()
        if not ok:
            self.gate.audit.write("acctwatch_refused", action_id="-", why="PayPal did not verify this webhook")
            return 400, "not verified by PayPal", None

        def claim(d):
            tids, eids = d.setdefault("tids", {}), d.setdefault("events", {})
            cut = (now - timedelta(days=2)).isoformat()
            for k in [k for k, v in tids.items() if v < cut]:
                del tids[k]
            if tid in tids:
                return "replay"
            tids[tid] = now.isoformat()
            if eid in eids:
                return "dupe"
            eids[eid] = now.isoformat()
            if len(eids) > 5000:
                for k in sorted(eids, key=eids.get)[:len(eids) - 5000]:
                    del eids[k]
            return "new"
        got = self.state.update(claim)
        if got == "replay":
            return 409, "replayed transmission", None
        if got == "dupe":
            return 200, "already handled", None
        return 200, "ok", event

    # -- 5: check, record, alert
    def handle(self, event: dict, mark: dict, source="webhook") -> dict:
        c = classify(event, self.gate, source)
        mark["t_checked"] = time.perf_counter()
        eid = str(event.get("id") or f"poll-{int(time.time())}")
        self.gate.audit.write("acctwatch_event", action_id="-", event_type=c["event_type"], source=source,
                              red=c["red"], kind=c["kind"], event_id=eid[:90])
        out = {"red": c["red"], "event_type": c["event_type"]}
        if not c["red"]:
            return out
        res = event.get("resource") if isinstance(event.get("resource"), dict) else {}
        first = self._claim_alert(alert_key(res), action_id_for(eid))
        if first is not None:   # same batch / resource already alerted: log only, no new red item, no call
            self.gate.audit.write("acctwatch_same_alert", action_id="-", for_action=first, event_type=c["event_type"],
                                  event_id=eid[:90], note="same payout or item as an alert already raised: logged only")
            out.update(action_id=first, deduped=True)
            if c["event_type"] == "PAYMENT.PAYOUTS-ITEM.UNCLAIMED":   # stopping the money is not a new alert
                out["cancel"] = self._maybe_cancel(first, res)
            return out
        payee = str((res.get("payout_item") or {}).get("receiver") or "PayPal (outside Bridge Warden)")
        aid = raise_red(self.gate, eid, c, payee=payee)
        out["action_id"] = aid
        extra = {}
        if c["action"] == "payout" and c["kind"] == "money_out":   # re-read the outside batch after the alert
            extra = {"outside_batch": batch_id_of(res), "reader": self.reader}
        out["alert"] = self._alerts().fire(aid, source="paypal-" + source, mark=mark, **extra)
        if c["event_type"] == "PAYMENT.PAYOUTS-ITEM.UNCLAIMED":
            out["cancel"] = self._maybe_cancel(aid, res)
        return out

    def _claim_alert(self, key: str, aid: str):
        """None = this is the first alert for `key` (now claimed, under the file lock). Else the first action id."""
        if not key:
            return None
        now = self.clock()

        def claim(d):
            al = d.setdefault("alerted", {})
            cut = (now - timedelta(seconds=self.dedupe_window)).isoformat()
            for k in [k for k, v in al.items() if str((v or {}).get("at", "")) < cut]:
                del al[k]
            if key in al:
                return al[key].get("aid") or "-"
            al[key] = {"at": now.isoformat(), "aid": aid}
            return None
        return self.state.update(claim)

    def _maybe_cancel(self, aid, res):
        item = str(res.get("payout_item_id") or "")
        if not self.autocancel or self.cancel is None or not ITEM_ID.match(item) or self.gate.dev_lock():
            self.gate.audit.write("acctwatch_cancel_skipped", action_id=aid,
                                  why="auto-cancel is off" if not self.autocancel else "not possible here")
            return {"cancelled": False}
        try:
            r = self.cancel(item)
            ok = str((r or {}).get("transaction_status", "")).upper() in ("RETURNED", "CANCELED", "CANCELLED") or bool(r)
        except Exception as ex:
            r, ok = {"error": str(ex)[:120]}, False
        self.gate.audit.write("acctwatch_cancel", action_id=aid, cancelled=ok,
                              note="unclaimed payout cancelled; money returns to you" if ok else "cancel failed")
        return {"cancelled": ok}

    def receive(self, headers: dict, raw: bytes, t0: float | None = None) -> tuple:
        """The whole webhook path. Returns (http code, short text, result)."""
        mark = {"t_received": t0 or time.perf_counter()}
        code, why, event = self.accept(headers, raw, mark)
        if event is None:
            return code, why, None
        res = self.handle(event, mark)
        self._timing(mark, res)
        return code, why, res

    def _timing(self, mark, res):
        t0 = mark["t_received"]
        ms = {k: round((mark[k] - t0) * 1000, 2) for k in ("t_verified", "t_checked", "t_call_request") if k in mark}
        self.gate.audit.write("acctwatch_timing", action_id=res.get("action_id", "-"), ms=ms,
                              event_type=res.get("event_type"), red=res.get("red"))
        try:
            from .audit import private_open
            with private_open(self.latency_log, "a") as f:
                f.write(json.dumps({"at": self.clock().isoformat(), "event_type": res.get("event_type"),
                                    "red": res.get("red"), **ms}) + "\n")
        except OSError:
            pass
        res["ms"] = ms


# ---------------------------------------------------------------- backup poller (OFF by default)
class TransactionPoller:
    """Reads Transaction Search (needs the PayPal app permission reporting/search/read, which Trey decides; NOT
    added). PayPal: new transactions can take up to ~3 hours to appear. Same checks and red light as webhooks."""
    LAG_NOTE = "PayPal Transaction Search can lag up to ~3 hours, so this is a backup, not the alarm."

    def __init__(self, watch: AccountWatch, read_only, every: int = 900):
        self.w, self.ro, self.every = watch, read_only, every

    def once(self, now=None):
        if self.w.gate.dev_lock():
            return []
        now = now or self.w.clock()
        rows = self.ro.transactions(now - timedelta(hours=6), now)
        mine, out = ours(self.w.gate), []
        for row in rows:
            ti = row.get("transaction_info") or {}
            tid = str(ti.get("transaction_id") or "")
            if not tid or tid in mine:
                continue
            key = "poll-" + tid
            def claim(d, k=key):
                ev_ = d.setdefault("events", {})
                if k in ev_:
                    return False
                ev_[k] = now.isoformat()
                return True
            if not self.w.state.update(claim):
                continue
            amt = ti.get("transaction_amount") or {}
            st = str(ti.get("transaction_status", ""))
            neg = str(amt.get("value", "0")).startswith("-")
            et = ("PAYMENT.CAPTURE.DENIED" if st in ("D", "F", "V") else
                  "PAYMENT.PAYOUTS-ITEM.SUCCEEDED" if neg else "PAYMENT.CAPTURE.COMPLETED")
            ev = {"id": key, "event_type": et,
                  "resource": {"id": tid, "amount": {"value": str(amt.get("value", "0")).lstrip("-"),
                                                     "currency_code": amt.get("currency_code", "USD")}}}
            out.append(self.w.handle(ev, {"t_received": time.perf_counter()}, source="poll"))
        return out


# ---------------------------------------------------------------- local server (127.0.0.1 only)
def make_server(watch: AccountWatch, port: int = 8766, bind: str = "127.0.0.1"):
    if bind not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("acctwatch binds to this computer only; put your own HTTPS forwarder in front")

    class H(BaseHTTPRequestHandler):
        server_version = "BW-acctwatch"

        def log_message(self, *a):   # no request logging (headers carry signatures)
            pass

        def _out(self, code, text):
            b = (text + "\n").encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._out(404 if self.path != "/healthz" else 200, "ok" if self.path == "/healthz" else "not found")

        def do_POST(self):
            t0 = time.perf_counter()
            if self.path != WEBHOOK_PATH:
                return self._out(404, "not found")
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._out(413, "too large")
            raw = self.rfile.read(n)
            code, why, _ = watch.receive({k: v for k, v in self.headers.items()}, raw, t0)
            self._out(code, why)

    return ThreadingHTTPServer((bind, port), H)


def build(env=None, gate=None):
    """Watcher for the owner's sandbox app. Needs PAYPAL_CLIENT_ID, PAYPAL_SANDBOX_SECRET, BW_PAYPAL_WEBHOOK_ID."""
    from .paypal_client import PayPalSandbox
    env = os.environ if env is None else env
    if gate is None:
        from types import SimpleNamespace
        from .cli import build_gate
        gate = build_gate(SimpleNamespace(policy=_env(env, "BW_POLICY", "policy.json"),
                                          audit=_env(env, "BW_AUDIT", "audit/audit.jsonl"), live=False, no_xai=True))
    client = PayPalSandbox()
    verifier = PayPalVerifier(client, _env(env, "BW_PAYPAL_WEBHOOK_ID"))

    def cancel(item):
        return client._call("POST", f"/v1/payments/payouts-item/{item}/cancel")
    return AccountWatch(gate, verifier=verifier, env=env, cancel=cancel, reader=client.payout_status), client


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "serve":
        print("usage: python -m bridge_warden.acctwatch serve   (127.0.0.1 only, sandbox only)")
        return 2
    watch, client = build()
    port = int(_env(None, "BW_ACCTWATCH_PORT", "8766") or 8766)
    srv = make_server(watch, port)
    if _on(_env(None, "BW_ACCTWATCH_POLL", "off")):
        from .money_check import ReadOnlyPayPal
        poller = TransactionPoller(watch, ReadOnlyPayPal(client))

        def loop():
            while True:
                try:
                    poller.once()
                except Exception:
                    pass
                time.sleep(poller.every)
        threading.Thread(target=loop, daemon=True, name="bw-acctwatch-poll").start()
    print(f"acctwatch listening on 127.0.0.1:{port}{WEBHOOK_PATH} (sandbox). Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
