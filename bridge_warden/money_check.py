""""Check my money" (v4). READ-ONLY. Moves no money, changes nothing at PayPal.

On one tap it looks at:
  * your Bridge Warden history (always; works with no keys at all),
  * PayPal sandbox, read-only GETs only, through ReadOnlyPayPal (path allowlist, GET only):
      - Subscriptions / Billing Plans  (GET /v1/billing/plans, GET /v1/billing/subscriptions/{id})
      - Transaction Search             (GET /v1/reporting/transactions)  needs the Transaction Search
        permission on the PayPal app. If it is missing we say so; we never add scopes ourselves.
      - Payout status                  (GET /v1/payments/payouts/{batch id}) for payouts in your history.
and finds, like an accountant would: duplicate subscriptions, bills due soon, failed or declined payments,
repeat charges that look like a subscription, and odd items worth a look.

Then, at most ONE small advisory xAI call per tap (redacted counts and amounts only, ZDR rules as v3).
No key, or AI off: the local rules write the summary.

Note on PayPal Subscriptions: the REST API shows subscriptions to YOUR plans (you as seller) and any
subscription whose id you give it. There is no public REST call that lists subscriptions you pay as a buyer.
So subscription ids to watch go in policy "money_check": {"subscription_ids": [...]}.
"""
from __future__ import annotations

import re
import statistics
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

DEFAULTS = {"subscription_ids": [], "due_soon_days": 7, "lookback_days": 31, "ai_summary": True}

READ_PATHS = (
    re.compile(r"^/v1/billing/plans$"),
    re.compile(r"^/v1/billing/subscriptions/I-[A-Z0-9]{6,40}$"),
    re.compile(r"^/v1/reporting/transactions$"),
    re.compile(r"^/v1/payments/payouts/[A-Z0-9]{6,40}$"),
)
SUB_ID = re.compile(r"^I-[A-Z0-9]{6,40}$")
TX_FAILED = {"D": "declined", "F": "failed", "V": "reversed"}   # Transaction Search status codes


class ReadOnlyPayPal:
    """Wraps the sandbox client so ONLY allowlisted GETs can be made. No method here can move money."""

    def __init__(self, client):
        self._c = client

    def get(self, path: str, params: dict | None = None) -> dict:
        if not any(rx.match(path) for rx in READ_PATHS):
            raise ValueError("not an allowed read-only PayPal path")
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        return self._c._call("GET", path + q)

    def plans(self) -> list:
        return self.get("/v1/billing/plans", {"page_size": 20, "total_required": "true"}).get("plans", []) or []

    def subscription(self, sid: str) -> dict:
        if not SUB_ID.match(sid or ""):
            raise ValueError("bad subscription id")
        return self.get(f"/v1/billing/subscriptions/{sid}")

    def transactions(self, start: datetime, end: datetime) -> list:
        f = "%Y-%m-%dT%H:%M:%S-0000"
        return self.get("/v1/reporting/transactions", {
            "start_date": start.astimezone(timezone.utc).strftime(f), "end_date": end.astimezone(timezone.utc).strftime(f),
            "fields": "transaction_info", "page_size": 100}).get("transaction_details", []) or []

    def payout(self, batch_id: str) -> dict:
        return self.get(f"/v1/payments/payouts/{batch_id}")


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _when(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _money(v, cur="USD") -> str:
    d = _dec(v)
    return f"${d:,.2f}" if d is not None and cur == "USD" else f"{v} {cur}"


def _sub_row(s: dict, plan_names: dict, now: datetime, soon_days: int) -> dict:
    bi = s.get("billing_info") or {}
    last = (bi.get("last_payment") or {}).get("amount") or {}
    fail = bi.get("last_failed_payment") or {}
    nxt = _when(bi.get("next_billing_time"))
    status = str(s.get("status", "")).upper()
    failed_n = int(bi.get("failed_payments_count") or 0)
    pid = s.get("plan_id", "")
    row = {"id": s.get("id", ""), "plan_id": pid, "name": plan_names.get(pid) or s.get("_name") or "Subscription",
           "status": status.title(), "amount": last.get("value"), "currency": last.get("currency_code", "USD"),
           "next_bill": nxt.isoformat() if nxt else None, "failed_count": failed_n,
           "last_failed": (fail.get("amount") or {}).get("value")}
    if status in ("SUSPENDED",) or failed_n > 0 or fail:
        row["bucket"] = "failed"
    elif status == "ACTIVE" and nxt and now <= nxt <= now + timedelta(days=soon_days):
        row["bucket"] = "due_soon"
    elif status == "ACTIVE":
        row["bucket"] = "active"
    else:
        row["bucket"] = "other"
    return row


def _history(recs: list, now: datetime, lookback: int) -> dict:
    """What Bridge Warden itself saw: sent, failed, blocked, and repeat payments."""
    since = now - timedelta(days=lookback)
    sent, failed, blocked, held = [], [], [], []
    props = {r["action_id"]: r.get("proposal", {}) for r in recs if r["event"] == "proposed"}
    for r in recs:
        at = _when(r.get("clock_at") or r.get("at"))
        if at and at < since:
            continue
        a = r.get("proposal") or props.get(r.get("action_id"), {})
        if r["event"] == "executed":
            sent.append({"aid": r["action_id"], "payee": a.get("payee"), "amount": a.get("amount"),
                         "currency": a.get("currency", "USD"), "at": at, "action": a.get("action"),
                         "batch": (r.get("result") or {}).get("payout_batch_id")})
        elif r["event"] == "failed":
            failed.append({"aid": r["action_id"], "payee": a.get("payee"), "amount": a.get("amount"),
                           "currency": a.get("currency", "USD")})
        elif r["event"] == "verdict":
            v = (r.get("verdict") or {}).get("verdict")
            (blocked if v == "block" else held if v == "hold" else []).append(r["action_id"])
    return {"sent": sent, "failed": failed, "blocked": blocked, "held": held}


def run_check(gate, reader=None, cfg: dict | None = None, now: datetime | None = None, ai=None) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    now = now or gate.clock()
    soon = int(cfg["due_soon_days"])
    rep = {"at": now.isoformat(), "sources": [], "subs": [], "look": [], "ok": [], "tx": {"count": 0},
           "ai": {"used": False}}
    look = rep["look"]

    # 1. Bridge Warden history (always)
    h = _history(gate.audit.records(), now, int(cfg["lookback_days"]))
    rep["sources"].append({"name": "Bridge Warden history", "ok": True,
                           "note": f"{len(h['sent'])} sent, {len(h['blocked'])} blocked, {len(h['failed'])} failed "
                                   f"in the last {cfg['lookback_days']} days."})
    for f in h["failed"]:
        look.append({"kind": "failed", "level": "look", "text": f"A payment to {f['payee']} for "
                     f"{_money(f['amount'], f['currency'])} failed. It did not go through.", "payee": f["payee"]})
    groups = defaultdict(list)
    for s in h["sent"]:
        groups[(s["payee"], s["amount"])].append(s)
    for (payee, amt), items in groups.items():
        if len(items) >= 2:
            look.append({"kind": "repeat", "level": "look", "payee": payee,
                         "text": f"You paid {payee} {_money(amt)} {len(items)} times. Is this a subscription you "
                                 "still want?"})
    amts = [_dec(s["amount"]) for s in h["sent"] if _dec(s["amount"]) is not None]
    if len(amts) >= 4:
        med = statistics.median(amts)
        for s in h["sent"]:
            d = _dec(s["amount"])
            if d is not None and med > 0 and d >= med * 3 and d >= 50:
                look.append({"kind": "unusual", "level": "look", "payee": s["payee"],
                             "text": f"{_money(d)} to {s['payee']} is much bigger than your usual "
                                     f"({_money(med)}). Worth a look."})

    # 2. PayPal, read-only
    if reader is None:
        rep["sources"].append({"name": "PayPal", "ok": False,
                               "note": "Not connected (practice mode). Used your Bridge Warden history only."})
    else:
        plan_names = {}
        try:
            plans = reader.plans()
            plan_names = {p.get("id"): p.get("name") for p in plans if isinstance(p, dict)}
            rep["sources"].append({"name": "PayPal billing plans", "ok": True, "note": f"{len(plans)} plan(s) found."})
        except Exception as ex:
            rep["sources"].append({"name": "PayPal billing plans", "ok": False, "note": _why(ex)})
        sids = [s for s in cfg.get("subscription_ids") or [] if isinstance(s, str) and SUB_ID.match(s)][:25]
        got = 0
        for sid in sids:
            try:
                rep["subs"].append(_sub_row(reader.subscription(sid), plan_names, now, soon))
                got += 1
            except Exception as ex:
                rep["subs"].append({"id": sid, "name": "Subscription", "status": "Unknown", "bucket": "other",
                                    "note": _why(ex)})
        rep["sources"].append({"name": "PayPal subscriptions", "ok": got == len(sids),
                               "note": (f"{got} of {len(sids)} watched subscription(s) read." if sids else
                                        "No subscription ids to watch yet (add them in policy money_check).")})
        try:
            txs = reader.transactions(now - timedelta(days=int(cfg["lookback_days"])), now)
            rep["tx"]["count"] = len(txs)
            from .money_map import lines_from_paypal   # v6: BW AG Grid agent groups (merchant names only, emails hidden)
            rep["map_lines"] = lines_from_paypal(txs)
            for t in txs:
                ti = t.get("transaction_info") or {}
                st = TX_FAILED.get(str(ti.get("transaction_status", "")))
                if st:
                    amt = (ti.get("transaction_amount") or {})
                    look.append({"kind": "declined", "level": "look", "text": f"A {_money(amt.get('value'), amt.get('currency_code', 'USD'))} "
                                 f"payment was {st} on {str(ti.get('transaction_initiation_date', ''))[:10]}."})
            rep["sources"].append({"name": "PayPal transactions", "ok": True, "note": f"{len(txs)} transaction(s) read."})
        except Exception as ex:
            note = _why(ex)
            if getattr(ex, "status", None) in (401, 403):
                note = ("PayPal said no. This app needs the Transaction Search permission "
                        "(scope reporting/search/read). The app owner decides; Bridge Warden did not add it.")
            rep["sources"].append({"name": "PayPal transactions", "ok": False, "note": note})
        n_po = 0
        for s in h["sent"]:
            if s.get("batch") and n_po < 10:
                n_po += 1
                try:
                    out = reader.payout(s["batch"])
                    items = out.get("items") or [{}]
                    ist = str(items[0].get("transaction_status", "")).upper()
                    if ist in ("FAILED", "RETURNED", "BLOCKED", "DENIED", "UNCLAIMED", "REFUNDED", "REVERSED"):
                        look.append({"kind": "payout", "level": "look", "payee": s["payee"],
                                     "text": f"Your payout to {s['payee']} ({_money(s['amount'])}) is {ist.lower()}."})
                except Exception:
                    pass
        if n_po:
            rep["sources"].append({"name": "PayPal payout status", "ok": True, "note": f"{n_po} payout(s) checked."})

    # 3. subscriptions: duplicates, due soon, failed
    subs = rep["subs"]
    seen = defaultdict(list)
    for s in subs:
        if s.get("status") == "Active":
            seen[(s.get("name", "").strip().lower(), s.get("amount"))].append(s)
            if s.get("plan_id"):
                seen[("plan", s["plan_id"])].append(s)
    dup_ids = set()
    for key, items in seen.items():
        ids = {i["id"] for i in items}
        if len(ids) >= 2 and not ids <= dup_ids:
            dup_ids |= ids
            look.append({"kind": "duplicate", "level": "look", "text": f"Two or more active subscriptions look the "
                         f"same: {items[0].get('name')} {_money(items[0].get('amount'))}. You may be paying twice."})
    for s in subs:
        if s.get("bucket") == "failed":
            look.append({"kind": "failed", "level": "look", "text": f"{s['name']}: a payment failed "
                         f"({s.get('failed_count') or 1} time(s)). Check your card or funding."})
        elif s.get("bucket") == "due_soon":
            d = _when(s["next_bill"])
            look.append({"kind": "due", "level": "info", "text": f"{s['name']} renews {d:%b %d} for "
                         f"{_money(s.get('amount'), s.get('currency', 'USD'))}."})
    if not look:
        rep["ok"].append("Nothing odd found. No failed payments, no doubles, nothing due in the next "
                         f"{soon} days.")
    rep["local_summary"] = local_summary(rep)
    if ai is None:
        rep["ai"] = {"used": False, "skipped": "no_ai"}
    elif not cfg.get("ai_summary", True):
        rep["ai"] = {"used": False, "skipped": "ai_off"}
    else:
        rep["ai"] = _ai_summary(rep, ai)
    return rep


def _why(ex) -> str:
    s = getattr(ex, "status", None)
    if s:
        return f"PayPal answered {s}. Skipped."
    return "Could not reach it. Skipped."


def local_summary(rep: dict) -> str:
    n = len([x for x in rep["look"] if x["level"] == "look"])
    due = len([x for x in rep["look"] if x["kind"] == "due"])
    if not rep["look"]:
        return "All looks normal."
    parts = []
    if n:
        parts.append(f"{n} thing{'s' if n != 1 else ''} worth a look")
    if due:
        parts.append(f"{due} bill{'s' if due != 1 else ''} due soon")
    return "Found " + " and ".join(parts) + "."


def redacted_context(rep: dict) -> dict:
    """The ONLY money-check data that may go to xAI: kinds, counts, amounts, statuses. No names, emails or ids."""
    names, out = {}, []
    for x in rep["look"][:12]:
        text = x["text"]
        p = x.get("payee")
        if p:
            names.setdefault(p, f"payee {chr(65 + len(names))}")
            text = text.replace(p, names[p])
        for s in rep["subs"]:
            if s.get("name"):
                text = text.replace(s["name"], "a subscription")
        from .xai_check import redact_description
        out.append({"kind": x["kind"], "level": x["level"], "text": redact_description(text)[:200]})
    subs = [{"status": s.get("status"), "bucket": s.get("bucket"), "amount": s.get("amount")} for s in rep["subs"][:25]]
    return {"findings": out, "subscriptions": subs, "transactions_read": rep["tx"]["count"]}


def _ai_summary(rep: dict, ai) -> dict:
    """At most ONE call per tap."""
    res = ai.advise(redacted_context(rep), "Summarize what I should look at, like a careful accountant.")
    out = {"used": bool(res.get("called")) and "text" in res, "usage": res.get("usage"),
           "skipped": res.get("skipped"), "error": res.get("error")}
    if out["used"]:
        out["text"] = res["text"]
    return out
