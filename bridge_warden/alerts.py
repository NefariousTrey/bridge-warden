"""Alert fan-out (ACCTWATCH / FREEALERTS / MISSEDCALL, 2026-10-26).

One place that raises a real alert, so every path behaves the same:
  * In-app notice: ALWAYS. A signed "alert_raised" line in the history; the red light and the browser's desktop
    alert (web.py, Notification API) come from the blocked item itself. Needs no account and costs nothing.
  * Phone call: if voice is set up (notify.call_on_fraud). Placed at once, in the caller's own thread.
  * Email: FREE, off unless the self-hoster sets their OWN mail server (any SMTP, e.g. a Gmail app password).
    Sent at once when there is no phone call, or as soon as the call is missed or fails. Runs in its own thread,
    in parallel, so it never waits on the call and a failure on one path never blocks the others.
  * Missed call: Twilio says no-answer / busy / failed / canceled (or a machine answered, if the owner turned on
    Twilio's paid answering-machine check) -> email + in-app notice now, then call again at the owner's retry
    times (default 15, then 25 more minutes = +15 and +40). Retries stop once the owner answers or opens the
    alert in the app. Retries live in a small file next to the history (survive a restart; claimed under a
    file lock before dialing, so two processes can never ring twice for the same step).
  * Dev mode / dry run: no real call or email; the missed call is SIMULATED and retries use the dry-run adapter.
  * Judges: "Test my alert" calls never retry (FraudDrill never uses this module), and judge mode refuses to
    start while any owner key (Twilio, SMTP, PayPal webhook) is set.
The email is fixed text: no payee, amount, link or account detail ever leaves the app.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from .filelock import lock as _flock, unlock as _funlock

DEFAULT_RETRY_MINUTES = [15, 15]   # 3 calls in all: now, +15 min, +30 min (Trey, 2026-10-27)
RETRY_MIN, RETRY_MAX, RETRY_COUNT_MAX = 1, 120, 3
MISSED = {"no-answer", "busy", "failed", "canceled"}
ANSWERED = {"completed", "in-progress"}
MACHINE = re.compile(r"^(machine_|fax)")
RING_TIMEOUT_SECONDS = 300        # no word from Twilio this long after dialing = treat as missed
CALL_SID = re.compile(r"^CA[0-9a-f]{32}$")
EMAIL_ENV = ("BW_SMTP_HOST", "BW_SMTP_PORT", "BW_SMTP_USER", "BW_SMTP_PASSWORD", "BW_ALERT_EMAIL_FROM",
             "BW_ALERT_EMAIL_TO")
OUTSIDE_LINE = "This happened in PayPal itself, so money may have moved. Check PayPal now."
EMAIL_SUBJECT = "Bridge Warden: something needs you"
EMAIL_BODY = ("Bridge Warden found activity that looks like fraud on your PayPal.\n\n"
              "Open your Bridge Warden app now to see it.\n"
              "Then open PayPal yourself (type paypal.com, do not use links) and check your recent activity.\n\n"
              "This email has no payment details and no links on purpose.\n")
MISSED_SUBJECT = "Bridge Warden: we tried to call you"
# Trey 2026-10-27: after the LAST missed call (3rd by default, about 30 min in), stop calling and send ONE final
# message (email if set up + in-app). No amounts, no names, no links: money details never go in it.
FINAL_SUBJECT = "Bridge Warden: still needs your attention"
FINAL_TEXT = "We couldn't reach you by phone. Something in your PayPal needs attention. Check PayPal now."
FINAL_BODY = (FINAL_TEXT + "\n\nOpen your Bridge Warden app to see it, then open PayPal yourself "
              "(type paypal.com, do not use links).\n\nThis email has no payment details and no links on purpose.\n")
ADDR = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- settings
def valid_retry_minutes(v) -> bool:
    """policy.json call_retry_minutes: a list of 0..3 whole minutes, each 1..120. [] = retries off."""
    return (isinstance(v, list) and len(v) <= RETRY_COUNT_MAX
            and all(isinstance(x, int) and not isinstance(x, bool) and RETRY_MIN <= x <= RETRY_MAX for x in v))


def retry_minutes(policy: dict) -> list:
    v = (policy or {}).get("call_retry_minutes", DEFAULT_RETRY_MINUTES)
    return list(v) if valid_retry_minutes(v) else list(DEFAULT_RETRY_MINUTES)


def saved_retry_minutes(gate) -> list:
    """Read fresh from policy.json (a Settings change reaches the next retry without a restart)."""
    try:
        path = (getattr(gate, "policy_info", None) or {}).get("path")
        if path and os.path.basename(str(path)) != "policy.example.json":
            with open(path, encoding="utf-8") as f:
                return retry_minutes(json.load(f) or {})
    except Exception:
        pass
    return retry_minutes(gate.engine.p)


def offsets(mins: list) -> list:
    """[15, 15] -> [15, 30]: each retry waits its minutes after the one before."""
    out, t = [], 0
    for m in mins:
        t += m
        out.append(t)
    return out


# ---------------------------------------------------------------- email (free, self-hosted)
class EmailAlerter:
    """Owner's OWN mail server. Off unless BW_SMTP_HOST, BW_ALERT_EMAIL_FROM and BW_ALERT_EMAIL_TO are set
    (user + password optional, as a pair). Port 465 = TLS from the start; anything else = STARTTLS (required).
    Secrets come from this computer's environment only and are never logged."""
    name = "smtp"

    def __init__(self, env=None, smtp_factory=None):
        env = os.environ if env is None else env
        g = lambda k: str(env.get(k, "")).strip()   # noqa: E731
        self._host, self._user, self._pw = g("BW_SMTP_HOST"), g("BW_SMTP_USER"), g("BW_SMTP_PASSWORD")
        self._from, self._to = g("BW_ALERT_EMAIL_FROM"), g("BW_ALERT_EMAIL_TO")
        try:
            self._port = int(g("BW_SMTP_PORT") or "587")
        except ValueError:
            self._port = 0
        self._factory = smtp_factory

    def __repr__(self):
        return f"EmailAlerter(ready={self.ready})"

    @property
    def ready(self) -> bool:
        return bool(self._host and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", self._host) and 0 < self._port < 65536
                    and ADDR.match(self._from) and ADDR.match(self._to) and bool(self._user) == bool(self._pw))

    def send(self, subject: str, body: str, attachments=None) -> dict:
        """attachments: [(filename, text)] - plain text files (E2EFIX: "Email me my proof"). Always to the
        owner's OWN address (BW_ALERT_EMAIL_TO); nobody else, never the developer."""
        if not self.ready:
            return {"sent": False, "note": "email not set up"}
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self._from, self._to
        msg.set_content(body)
        for name, text in attachments or ():
            safe = re.sub(r"[^A-Za-z0-9._-]", "-", str(name))[:100] or "proof.txt"
            msg.add_attachment(str(text).encode("utf-8"), maintype="text", subtype="plain", filename=safe)
        ctx = ssl.create_default_context()
        try:
            if self._factory is not None:
                s = self._factory(self._host, self._port)
            elif self._port == 465:
                s = smtplib.SMTP_SSL(self._host, self._port, timeout=10, context=ctx)
            else:
                s = smtplib.SMTP(self._host, self._port, timeout=10)
            with s:
                if self._port != 465 and self._factory is None:
                    s.starttls(context=ctx)
                if self._user:
                    s.login(self._user, self._pw)
                s.send_message(msg)
            return {"sent": True}
        except Exception as ex:
            txt = str(ex)
            for secret in (self._pw, self._user, self._to, self._from):
                if secret:
                    txt = txt.replace(secret, "[hidden]")
            return {"sent": False, "error": f"{type(ex).__name__}: {txt}"[:160]}


class DryRunEmail:
    name = "dry_run"
    ready = True

    def send(self, subject, body, attachments=None):
        out = {"sent": False, "would": "email owner", "note": "dry run: no email was sent"}
        if attachments:
            out["would_attach"] = [str(n)[:100] for n, _ in attachments]
        return out


# ---------------------------------------------------------------- Twilio status callback signature
def twilio_signature(token: str, url: str, params: dict) -> str:
    data = url + "".join(k + str(params[k]) for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def twilio_signature_ok(token: str, url: str, params: dict, sig: str) -> bool:
    if not token or not sig:
        return False
    return hmac.compare_digest(twilio_signature(token, url, params), str(sig))


# ---------------------------------------------------------------- the persisted retry queue
class RetryQueue:
    """alert_retries.json next to the history. Every change happens under an exclusive file lock."""

    def __init__(self, folder):
        self.path = Path(folder) / "alert_retries.json"

    def _lock(self):
        from .audit import private_open
        return private_open(self.path.with_name(self.path.name + ".lock"), "a")

    def update(self, fn):
        """fn(entries: dict) -> result. Entries are saved atomically after fn returns."""
        with self._lock() as lf:
            _flock(lf)
            try:
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    data = data if isinstance(data, dict) else {}
                except (OSError, ValueError):
                    data = {}
                out = fn(data)
                from .audit import private, private_open
                tmp = self.path.with_name(self.path.name + ".tmp")
                with private_open(tmp, "w") as fh:
                    fh.write(json.dumps(data, sort_keys=True, indent=1))
                os.replace(tmp, self.path)
                private(self.path)
                return out
            finally:
                _funlock(lf)

    def read(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}


# ---------------------------------------------------------------- the fan-out
class Alerts:
    def __init__(self, gate, caller="auto", email=None, clock=None, env=None, retries=True):
        from . import notify as N
        self.N, self.gate = N, gate
        self.env = os.environ if env is None else env
        self.clock = clock or _now
        cfg = gate.engine.p.get("notify", {}) or {}
        self.caller = N.call_adapter(cfg, env=self.env) if caller == "auto" else caller   # None = voice off
        self.email = email if email is not None else EmailAlerter(env=self.env)
        self.retries = retries
        folder = getattr(getattr(gate.audit, "path", None), "parent", None)
        self.queue = RetryQueue(folder) if folder is not None else None

    # -- helpers
    def dev(self) -> bool:
        return self.N.dev_locked(self.gate)

    def _caller(self):
        if self.caller is None:
            return None
        return self.N.DryRunCallAdapter() if self.dev() else self.caller

    def voice_ready(self) -> bool:
        c = self.caller
        return c is not None and (not getattr(c, "real", False) or bool(getattr(c, "ready", True)))

    def email_ready(self) -> bool:
        return bool(getattr(self.email, "ready", False))

    def _email(self, aid, subject, why, out, body=EMAIL_BODY):
        em = DryRunEmail() if self.dev() else self.email
        try:
            res = em.send(subject, body)
        except Exception as ex:   # never let email break anything
            res = {"sent": False, "error": str(ex)[:120]}
        out["email"] = res
        self.gate.audit.write("email_sent" if res.get("sent") else "would_email_owner", action_id="-",
                              channel="email", provider=getattr(em, "name", "smtp"), for_action=aid, why=why,
                              sent=bool(res.get("sent")),
                              note=res.get("error") or res.get("note") or ("email sent to you" if res.get("sent") else ""))

    def _place(self, aid, attempt, out, mark=None, outside=None, outside_batch=None, reader=None):
        caller = self._caller()
        N = self.N
        stamp = {}
        send = getattr(caller, "_send", None)
        if callable(send) and mark is not None:   # time the moment the request to Twilio leaves
            def timed(*a, **k):
                stamp["t"] = time.perf_counter()
                return send(*a, **k)
            caller._send = timed
        try:
            nm = N.clean_name(self.gate.engine.p.get("preferred_name") or "")
            text = " ".join(N.call_lines(N.REAL_WHAT, test=False, name=nm))
            if outside is None:
                outside = self._outside(aid)
            if outside:   # money may already have moved outside Bridge Warden: never say "Nothing was sent"
                text = text.replace("Nothing was sent.", OUTSIDE_LINE)
            res = N.place(caller, text, name=nm, voice=N.saved_voice(self.gate))
        except Exception as ex:   # an adapter must never break the gate
            res = {"error": str(ex)[:120]}
        finally:
            if callable(send) and mark is not None:
                caller._send = send
        if mark is not None:
            mark["t_call_request"] = stamp.get("t") or time.perf_counter()
        sid = res.get("call_sid") if CALL_SID.match(str(res.get("call_sid") or "")) else None
        N.log_call(self.gate, caller, res, test=False, for_action=aid)
        try:   # STATE CHECK: re-read PayPal + our log after the call (the AI never hears the call)
            from .callaudit import check_outside, run as state_check
            out["state_check"] = state_check(self.gate, "after_alert_call", email=self.email, env=self.env)
            if outside_batch is not None:   # E2EFIX: also re-read the OUTSIDE payout batch (log only, never yellow)
                out["outside_check"] = check_outside(self.gate, outside_batch, read=reader, for_action=aid)
        except Exception:
            pass
        out["call"] = {k: res.get(k) for k in ("dialed", "status", "error", "note", "would") if k in res}
        if sid:
            out["call"]["call_sid"] = sid      # E2EFIX: the Twilio call id, so the call can be looked up later
        return caller, res

    @staticmethod
    def _outside(aid) -> bool:
        return str(aid).startswith("pp-")

    # -- the one entry point
    def fire(self, aid: str, source: str = "gate", mark: dict | None = None, wait: bool = True,
             outside_batch: str | None = None, reader=None) -> dict:
        """Raise one real alert for action `aid`. In-app notice first (one signed line), then email in parallel
        (no voice) and the call right here. Returns what happened per channel."""
        voice = self.voice_ready()
        email_now = self.email_ready() and not voice
        out = {"in_app": True}
        self.gate.audit.write("alert_raised", action_id="-", for_action=aid, source=source,
                              channels=["in_app"] + (["call"] if voice else []) + (["email"] if email_now else []))
        th = None
        if email_now:
            th = threading.Thread(target=self._email, args=(aid, EMAIL_SUBJECT, "alert", out), daemon=True,
                                  name="bw-alert-email")
            th.start()
        if self.caller is not None:
            caller, res = self._place(aid, 0, out, mark, outside_batch=outside_batch, reader=reader)
            self._after_call(aid, 0, caller, res, out)
        elif outside_batch is not None:     # no voice: still re-check the outside payout (log only)
            from .callaudit import check_outside
            out["outside_check"] = check_outside(self.gate, outside_batch, read=reader, for_action=aid)
        if th is not None and wait:
            th.join(15)
        return out

    def _after_call(self, aid, attempt, caller, res, out):
        """Track the call so a miss can be followed up. Dry run = simulated miss (no real call anywhere)."""
        if self.queue is None:
            return
        sim = not getattr(caller, "real", False) or not res.get("dialed")
        sid = res.get("call_sid") if CALL_SID.match(str(res.get("call_sid") or "")) else None
        mins = saved_retry_minutes(self.gate) if self.retries else []
        now = self.clock()

        def put(d):
            e = d.get(aid) or {"action_id": aid, "first_call_at": now.isoformat(), "attempts": 0, "emailed": False,
                               "retry_minutes": mins}
            e.update({"state": "ringing", "call_sid": sid, "simulated": bool(sim) and not sid,
                      "dialed_at": now.isoformat(), "attempts": attempt + 1})
            d[aid] = e
        self.queue.update(put)
        if sim and not sid:   # no real ringing phone: dry run, error, or not dialed -> treat as missed at once
            self.on_status(aid=aid, status="no-answer" if not res.get("error") else "failed",
                           simulated=not getattr(caller, "real", False), out=out)

    # -- status from Twilio (signed callback or a read of the call)
    def on_status(self, call_sid=None, status="", answered_by="", aid=None, simulated=False, out=None) -> dict:
        status, answered_by = str(status or "").lower(), str(answered_by or "").lower()
        missed = status in MISSED or bool(MACHINE.match(answered_by))
        answered = status in ANSWERED and not missed
        if not (missed or answered):
            return {"ignored": status or "empty"}
        now = self.clock()
        res = {}

        def upd(d):
            key = aid if aid in d else next((k for k, e in d.items() if call_sid and e.get("call_sid") == call_sid), None)
            if key is None or d[key].get("state") != "ringing":
                return None
            e = d[key]
            if answered:
                e.update(state="done", done_why="answered", done_at=now.isoformat())
                return key, "answered", False, None
            first = datetime.fromisoformat(e["first_call_at"])
            offs = offsets(e.get("retry_minutes") or [])
            n = e.get("attempts", 1)               # calls made so far (first call + retries)
            nxt = first + timedelta(minutes=offs[n - 1]) if n - 1 < len(offs) else None
            email_due = True                       # every missed call: email (if set up) + in-app alert
            e.update(state="waiting_retry" if nxt else "done", next_at=nxt.isoformat() if nxt else None,
                     emailed=True, last_status=answered_by or status)
            if not nxt:
                e.update(done_why="no_more_retries", done_at=now.isoformat())
            return key, "missed", email_due, nxt
        got = self.queue.update(upd) if self.queue else None
        if got is None:
            return {"ignored": "unknown or already handled"}
        key, what, email_due, nxt = got
        if what == "answered":
            self.gate.audit.write("alert_answered", action_id="-", for_action=key, status=status)
            return {"answered": True}
        self.gate.audit.write("alert_missed_call", action_id="-", for_action=key, status=answered_by or status,
                              simulated=bool(simulated), next_retry_at=nxt.isoformat() if nxt else None,
                              label="SIMULATED" if simulated else "")
        res = out if out is not None else {}
        final = nxt is None            # last call missed: stop calling, ONE final message instead of the missed email
        if final:
            self.gate.audit.write("alert_final_notice", action_id="-", for_action=key, text=FINAL_TEXT,
                                  simulated=bool(simulated), label="SIMULATED" if simulated else "",
                                  note="calls stopped; the light stays red until you clear it")
        if email_due and self.email_ready():
            args = ((key, FINAL_SUBJECT, "final_notice", res, FINAL_BODY) if final
                    else (key, MISSED_SUBJECT, "missed_call", res))
            th = threading.Thread(target=self._email, args=args, daemon=True, name="bw-alert-email")
            th.start()
            th.join(15)
        return {"missed": True, "next_at": nxt.isoformat() if nxt else None, "final": final}

    def acknowledged(self, aid: str) -> bool:
        recs = self.gate.audit.records()
        vseq = max([r["seq"] for r in recs if r.get("action_id") == aid and r.get("event") == "verdict"] or [0])
        for r in recs:
            ev = r.get("event")
            if ev == "owner_saw_blocks" and vseq and r.get("upto_seq", 0) >= vseq:
                return True
            if ev in ("owner_decision", "alert_acknowledged") and (r.get("action_id") == aid or r.get("for_action") == aid):
                return True
        return False

    def tick(self, now: datetime | None = None) -> list:
        """Run due retries. Safe to call often and from more than one process (claimed under the file lock)."""
        if self.queue is None or not self.queue.path.exists():
            return []
        now = now or self.clock()
        done = []
        # 1) calls still "ringing" too long, or with a real call id: ask Twilio what happened (a free read)
        for aid, e in list(self.queue.read().items()):
            if e.get("state") != "ringing":
                continue
            st = None
            if e.get("call_sid") and hasattr(self.caller, "call_status") and not self.dev():
                try:
                    st = self.caller.call_status(e["call_sid"])
                except Exception:
                    st = None
            if st and st.get("status"):
                self.on_status(call_sid=e["call_sid"], status=st["status"], answered_by=st.get("answered_by", ""),
                               aid=aid)
            elif now - datetime.fromisoformat(e["dialed_at"]) > timedelta(seconds=RING_TIMEOUT_SECONDS):
                self.on_status(aid=aid, status="no-answer")
        # 2) due retries
        for aid, e in list(self.queue.read().items()):
            if e.get("state") != "waiting_retry" or not e.get("next_at"):
                continue
            if datetime.fromisoformat(e["next_at"]) > now:
                continue
            if self.acknowledged(aid):
                self.queue.update(lambda d, a=aid: d[a].update(state="done", done_why="acknowledged",
                                                               done_at=now.isoformat()))
                self.gate.audit.write("alert_retry_stopped", action_id="-", for_action=aid, why="you saw it in the app")
                continue

            def claim(d, a=aid, due=e["next_at"]):
                x = d.get(a)
                if not x or x.get("state") != "waiting_retry" or x.get("next_at") != due:
                    return False          # someone else already took this step
                x.update(state="dialing", next_at=None)
                return True
            if not self.queue.update(claim):
                continue
            attempt = e.get("attempts", 1)
            self.gate.audit.write("alert_retry_call", action_id="-", for_action=aid, attempt=attempt,
                                  of=len(e.get("retry_minutes") or []))
            out = {}
            if self.caller is None:
                self.queue.update(lambda d, a=aid: d[a].update(state="done", done_why="voice_off"))
                continue
            caller, res = self._place(aid, attempt, out)
            self._after_call(aid, attempt, caller, res, out)
            done.append(aid)
        return done


def acknowledge(gate, aid: str, by="owner (web)"):
    """The owner opened the alert in the app: stop retries for it."""
    gate.audit.write("alert_acknowledged", action_id="-", for_action=aid, by=by)
