"""State check after calls and actions (2026-10-27). The AI does NOT hear or transcribe calls.

After every alert call (real, test and judge) and after every Bridge Warden money action, re-read what PayPal shows
(the payout status the app already pulls) and compare it with Bridge Warden's own signed log. Looks for:
  * an action that did not land (PayPal says denied, failed, returned, blocked, or cannot find it),
  * an action that landed twice (two "executed" lines for one action, or one PayPal batch logged twice),
  * a state that does not match the log (started but never finished, or an approval that never ran).
If anything needs attention: the light goes YELLOW (never over a red; a red you respond to while this is still open
steps down to yellow, REDYELLOW), Bridge Warden's automatic actions wait
(new requests wait for you; your own approvals still work), you see a plain note in the app, and an email goes out
if email is set up. It clears when you clear it in the app or when a later check comes back clean.
Problems, and the clean check that clears one, are logged ("state_check"). Dev mode never calls PayPal and can simulate a yellow check (TEST).
"""

CHECK_EVENT = "state_check"
ALERT_EVENT = "state_check_alert"        # shown in the alert feed
CLEAR_EVENT = "state_check_cleared"
SUBJECT = "Bridge Warden: something needs your attention"
BAD_BATCH = {"DENIED", "CANCELED", "FAILED"}
BAD_ITEM = {"FAILED", "RETURNED", "BLOCKED", "REVERSED", "DENIED"}
HOLD_TEXT = ("A check found something that needs your attention. Bridge Warden's automatic actions wait until you "
             "clear it in Settings.")
SIM_NOTE = "TEST: simulated check. Nothing real is wrong."
MAX_READS = 10


def attention(gate):
    """The open problem (dict) or None. Open = the last check found something and nobody cleared it since."""
    try:
        recs = gate.audit.records()
    except Exception:
        return None
    for r in reversed(recs):
        if r.get("event") == CLEAR_EVENT:
            return None
        if r.get("event") == CHECK_EVENT and r.get("ok") is not None:
            return None if r.get("ok") else {"note": " ".join(r.get("problems") or []) or "Check needed.",
                                              "simulated": bool(r.get("simulated")), "seq": r.get("seq")}
    return None


def hold_reason(gate):
    return HOLD_TEXT if attention(gate) else None


def _dev(gate) -> bool:
    try:
        return bool(gate.dev_lock())
    except Exception:
        return False


def problems(gate, aid=None) -> list:
    """Plain notes on what needs attention. Reads PayPal only for real (non-dry-run) payouts, at most MAX_READS."""
    recs = gate.audit.records()
    out, by_aid, batches = [], {}, {}
    for r in recs:
        a = r.get("action_id")
        if not a or a == "-":
            continue
        by_aid.setdefault(a, []).append(r)
    for a, rs in by_aid.items():
        ev = [r.get("event") for r in rs]
        real_exec = [r for r in rs if r.get("event") == "executed" and not (r.get("result") or {}).get("dry_run")]
        if len(real_exec) > 1:
            out.append(f"Action {a} was logged as done more than once. Check PayPal for a double payment.")
        if "executing" in ev and not ({"executed", "failed"} & set(ev)):
            out.append(f"Action {a} started but Bridge Warden never logged how it ended. Check PayPal.")
        if "failed" in ev and any(r.get("outcome") == "unknown" for r in rs if r.get("event") == "failed"):
            out.append(f"Action {a} may or may not have gone through. Check PayPal.")
        last_yes = max((i for i, r in enumerate(rs) if r.get("event") == "owner_decision"
                        and r.get("decision") == "yes"), default=None)
        if last_yes is not None and not ({"executing", "recheck_blocked"} & set(ev[last_yes:])):
            out.append(f"Action {a} was approved but never ran.")
        for r in real_exec:
            b = (r.get("result") or {}).get("payout_batch_id")
            if b:
                batches.setdefault(b, set()).add(a)
    for b, aids in batches.items():
        if len(aids) > 1:
            out.append("One PayPal payout was logged for two different actions.")
    read = getattr(getattr(gate, "paypal", None), "payout_status", None)
    if callable(read) and not _dev(gate):
        todo = [(b, next(iter(a))) for b, a in batches.items() if aid is None or aid in a][-MAX_READS:]
        for b, a in todo:
            try:
                st = read(b) or {}
            except Exception as ex:
                if getattr(ex, "status", None) == 404:
                    out.append(f"PayPal cannot find the payout for action {a}. It may not have landed.")
                continue    # PayPal unreachable: not a mismatch, check again later
            if str(st.get("batch_status", "")).upper() in BAD_BATCH or str(st.get("item_status", "")).upper() in BAD_ITEM:
                out.append(f"PayPal says the payout for action {a} did not go through.")
    return out


OUTSIDE_EVENT = "state_check_outside"     # E2EFIX: an outside payout, re-read after its alert (never yellow)
OUTSIDE_NO_READ = "outside payout, could not re-check"


def check_outside(gate, batch_id, read=None, for_action="-") -> dict:
    """After an alert about a payout Bridge Warden did NOT send: re-read that batch from PayPal if we can.
    Only LOGS what PayPal says. It never turns the light yellow: the move is not in Bridge Warden's log, so a
    difference is expected, not a mismatch (the red light already covers it). Never raises."""
    import re
    b = str(batch_id or "")
    if read is None:
        read = getattr(getattr(gate, "paypal", None), "payout_status", None)
    res = {"batch": b[:40], "rechecked": False}
    try:
        if not re.fullmatch(r"[A-Z0-9]{8,40}", b) or not callable(read) or _dev(gate):
            res["note"] = OUTSIDE_NO_READ
        else:
            try:
                st = read(b) or {}
                res.update(rechecked=True, batch_status=str(st.get("batch_status") or "")[:20],
                           item_status=str(st.get("item_status") or "")[:20],
                           note="outside payout re-checked at PayPal")
            except Exception as ex:
                res["note"] = OUTSIDE_NO_READ
                if getattr(ex, "status", None) is not None:
                    res["http"] = getattr(ex, "status")
        gate.audit.write(OUTSIDE_EVENT, action_id="-", for_action=str(for_action)[:90], **res)
    except Exception as ex:
        res = {"rechecked": False, "note": OUTSIDE_NO_READ, "error": type(ex).__name__}
    return res


def run(gate, why: str, aid=None, email=None, env=None) -> dict:
    """Run the check, log it, and alert if something needs attention. Never raises."""
    try:
        found = problems(gate, aid)
        res = {"ok": not found, "problems": found}
        if not found and not attention(gate):
            return res      # clean and nothing open: stays green, no extra log line
        gate.audit.write(CHECK_EVENT, action_id="-", why=why, ok=not found, problems=found,
                         for_action=aid or "-", paypal_read=not _dev(gate))
        if found:
            note = " ".join(found)
            gate.audit.write(ALERT_EVENT, action_id="-", note=note[:600])
            res["email"] = _email(gate, note, email, env)
        _log_light(gate)    # REDYELLOW: yellow (paused) or back to green: a timestamped History line
        return res
    except Exception as ex:
        try:
            gate.audit.write(CHECK_EVENT, action_id="-", why=why, ok=None, note=f"check error: {type(ex).__name__}")
        except Exception:
            pass
        return {"ok": None, "error": type(ex).__name__}


def simulate(gate, by: str = "owner (web)") -> dict:
    """Dev mode / test: a pretend yellow check. Marked TEST. Nothing real is wrong."""
    gate.audit.write(CHECK_EVENT, action_id="-", why="simulated", ok=False, problems=[SIM_NOTE], simulated=True,
                     label="TEST", by=by)
    gate.audit.write(ALERT_EVENT, action_id="-", note=SIM_NOTE, simulated=True, label="TEST")
    return {"ok": False, "problems": [SIM_NOTE], "simulated": True}


def clear(gate, by: str = "owner (web)") -> bool:
    if not attention(gate):
        return False
    gate.audit.write(CLEAR_EVENT, action_id="-", by=by)
    _log_light(gate)
    return True


def _log_light(gate):
    try:
        from .dashboard import status
        status(gate)
    except Exception:
        pass


def _email(gate, note, email=None, env=None) -> dict:
    from . import alerts as A
    em = A.DryRunEmail() if _dev(gate) else (email if email is not None else A.EmailAlerter(env=env))
    if not getattr(em, "ready", False):
        return {"sent": False, "note": "email not set up"}
    body = ("Bridge Warden re-checked your PayPal against its own log. Something needs your attention:\n"
            f"{note}\nAutomatic actions wait until you clear it in Settings. Check your PayPal activity yourself too.")
    try:
        r = em.send(SUBJECT, body)
    except Exception as ex:
        r = {"sent": False, "error": type(ex).__name__}
    gate.audit.write("email_sent" if r.get("sent") else "would_email_owner", action_id="-", channel="email",
                     why="state_check", sent=bool(r.get("sent")), note=r.get("error") or r.get("note") or "")
    return r
