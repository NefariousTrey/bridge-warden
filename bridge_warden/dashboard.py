"""Plain-words view of the audit log for the dashboard, history and proof export (v4).

Everything here is derived from the hash-chained audit log; nothing is stored anywhere else.
  * moves(): one row per money request: safe (sent), held, approved, cancelled, blocked, expired, failed.
  * status(): the status light. green = everything is working. yellow (state "gray") = paused (by you, or while
    you fix a red you already saw) or a check needs you. red = something bad happened (a new held payment, or a
    block you have not marked as seen); it stays red until you respond. Safe payments stay silent.
    REDYELLOW (Trey): responding to a red that is not fixed yet steps it DOWN to yellow (paused), never
    straight to green; every color change is a timestamped History line (light_changed).
  * why_line(): one short line on why something was held or blocked.
  * proof(): the export used as dispute / appeal evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import controls
from .devmode import is_test_id
from .textnorm import ascii_view, display_safe, is_plain_ascii

BLOCK_SHOWN_HOURS = 24   # a block keeps the light red until you mark it seen, or for this long

SHORT = {
    "price_too_low": "Price is far below what stores ask.",
    "new_payee": "New payee.", "over_auto_limit": "Over your auto-allow amount.",
    "velocity": "Many payments this hour.", "odd_hours": "During your quiet hours.",
    "hidden_characters": "Hidden characters in the note.", "non_ascii_payee": "Odd letters in the payee.",
    "refund_unknown_capture": "Refund of a payment this agent didn't make.", "duplicate": "Looks like a double payment.",
    "scam_pattern": "Scam-like wording.", "ai_scam_model": "The scam model is worried.",
    "xai_review": "The xAI check is worried.", "xai_unavailable": "The xAI check did not answer.",
    "hard_max": "Over your hard limit.", "daily_cap": "Over your daily cap.",
    "blocked_payee": "Payee is on your blocked list.", "lookalike_payee": "Fake payee made to look like a real one.",
    "scam_pattern_stack": "Scam signs.", "prompt_injection": "Tries to trick the rules (prompt injection).",
    "secret_in_text": "Contains a password, key or card number.",
    "control_characters": "Text that can disguise your screen.", "refund_too_big": "Refund is bigger than the payment.",
    "paused": "Bridge Warden is paused.", "unknown_action": "Not an allowed action.", "bad_input": "Broken request.",
    "currency": "Currency you don't allow.", "bad_amount": "Not a valid amount.", "bad_payee": "Not a valid payee.",
    "refund_no_capture": "Refund doesn't say which payment.",
    "fix_pause": "Paused while you fix an earlier problem.",
}
LABEL = {"safe": "Safe, sent", "waiting": "Held, waiting for you", "approved": "Held, you sent it",
         "cancelled": "Held, you cancelled", "blocked": "Blocked", "expired": "Held, timed out",
         "failed": "PayPal said no", "unknown": "Unknown"}
KIND = {"safe": "safe", "approved": "safe", "waiting": "held", "cancelled": "gray", "expired": "gray",
        "blocked": "blocked", "failed": "blocked", "unknown": "gray"}
VERB = {"payout": "Paying", "create_order": "Buying from", "refund": "Refunding"}


def money(amount, currency) -> str:
    a, c = display_safe(str(amount or ""), 40), display_safe(str(currency or ""), 8)
    return f"${a}" if c == "USD" else f"{a} {c}"


def payee_text(p: dict) -> str:
    who = p.get("payee") or p.get("capture_id") or "-"
    if not is_plain_ascii(who):
        return ascii_view(who) + " (odd letters)"
    return display_safe(who, 200)


AI_RULES = {"ai_scam_model", "xai_review"}


def ai_flagged(verdict: dict) -> bool:
    """True when an AI check (local scam model or xAI review) helped hold or block this. Shown as an "AI check" badge."""
    return any(f.get("rule") in AI_RULES and f.get("severity") in ("hold", "block") for f in verdict.get("findings") or [])


def why_line(verdict: dict, proposal: dict) -> str:
    """One plain line. Holds list up to two reasons; blocks lead with the worst one."""
    fs = verdict.get("findings") or []
    sev = verdict.get("verdict")
    pick = [f for f in fs if f.get("severity") == ("block" if sev == "block" else "hold")]
    pick.sort(key=lambda f: f.get("rule") != "price_too_low")   # v4: the rarer, sharper warning first
    out = []
    for f in pick:
        r = f.get("rule", "")
        s = SHORT.get(r)
        if r in ("scam_pattern", "scam_pattern_stack"):
            low = " ".join(x.get("reason", "") for x in fs).lower()
            if "gift" in low:
                s = "Gift-card scam signs."
        if s and s not in out:
            out.append(s)
    out = out[:2]
    if sev == "hold" and proposal.get("action") == "payout":
        out.append("Payouts have no buyer protection.")
    if not out:
        out = [display_safe((verdict.get("reasons") or ["Nothing looks risky."])[0], 160)]
    return " ".join(out)


def _ts(rec) -> datetime | None:
    for k in ("clock_at", "at"):
        try:
            return datetime.fromisoformat(rec[k])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _pause_only(vd: dict) -> bool:
    """PAUSEOFF: blocked ONLY because you paused Bridge Warden (not risky by itself). It does not turn the light red."""
    bad = [f for f in vd.get("findings", []) if isinstance(f, dict) and f.get("severity") == "block"]
    return bool(bad) and all(f.get("rule") == "paused" for f in bad)


def moves(records: list) -> list:
    """Newest first."""
    props, verdicts = {}, {}
    after = {}
    for r in records:
        aid = r.get("action_id")
        ev = r.get("event")
        if ev == "proposed" and aid not in props:
            props[aid] = r
        elif ev == "verdict" and aid in props and aid not in verdicts \
                and r.get("proposal_hash") == props[aid].get("proposal_hash"):
            verdicts[aid] = r
        elif ev in ("owner_decision", "executed", "failed", "recheck_blocked", "expired", "owner_kept_waiting"):
            after.setdefault(aid, []).append(r)
    out = []
    for aid, v in verdicts.items():
        p, vd = props[aid]["proposal"], v["verdict"]
        evs = {r["event"]: r for r in after.get(aid, [])}
        sev = vd.get("verdict")
        if sev == "allow":
            st = "failed" if "failed" in evs else "safe"
        elif sev == "block":
            st = "blocked"
        else:
            dec = evs.get("owner_decision")
            if dec is None:
                st = "expired" if "expired" in evs else "waiting"
            elif dec.get("decision") == "no":
                st = "cancelled"
            elif "recheck_blocked" in evs:
                st = "blocked"
            elif "failed" in evs:
                st = "failed"
            else:
                st = "approved"
        refs = [{"seq": r["seq"], "event": r["event"], "at": r["at"], "hash": r["hash"]}
                for r in records if r.get("action_id") == aid]
        out.append({"action_id": aid, "seq": v["seq"], "at": v.get("clock_at") or v["at"], "action": p.get("action"),
                    "amount": p.get("amount"), "currency": p.get("currency"), "payee": payee_text(p),
                    "description": display_safe(p.get("description", ""), 300), "verdict": sev, "status": st,
                    "test": is_test_id(aid), "pause_only": _pause_only(vd),
                    "label": ("TEST: " if is_test_id(aid) else "") + LABEL[st], "kind": KIND[st], "why": why_line(vd, p) if sev != "allow" else "Nothing risky.",
                    "reasons": [display_safe(x, 300) for x in vd.get("reasons", [])],
                    "risk_score": vd.get("risk_score", 0), "ai": ai_flagged(vd), "proposal_hash": props[aid].get("proposal_hash"),
                    "decided_by": (evs.get("owner_decision") or {}).get("decided_by"),
                    "result": {k: display_safe(str(val), 80) for k, val in ((evs.get("executed") or {}).get("result")
                               or {}).items() if isinstance(val, (str, int, float, bool))},
                    "records": refs})
    out.sort(key=lambda m: m["seq"], reverse=True)
    return out


def unseen_blocks(records: list, now: datetime) -> list:
    seen = max([r.get("upto_seq", 0) for r in records if r.get("event") == "owner_saw_blocks"] or [0])
    out = []
    for m in moves(records):
        if str(m["action_id"]).startswith("ag-"):   # v6: BW AG Grid agent reds follow ag_agent.light (seen, not time)
            continue
        if m["status"] == "blocked" and m["seq"] > seen:
            t = _ts({"at": m["at"]})
            if t is None or now - t <= timedelta(hours=BLOCK_SHOWN_HOURS):
                out.append(m)
    return out


def unresolved_final(records: list) -> list:
    """Trey 2026-10-27: alerts that got the final "we couldn't reach you" message and that YOU have not cleared.
    They keep the light red with no time limit. Only your own clear ends it: "mark as seen" (Settings / home /
    incident choice, written as owner_saw_blocks by the owner) or your decision on the Held card (owner_decision).
    No timeout, no state check, no retry bookkeeping can clear it."""
    finals = []
    for r in records:
        if r.get("event") == "alert_final_notice" and r.get("for_action") and r["for_action"] not in finals:
            finals.append(r["for_action"])
    out = []
    for aid in finals:
        vseq = max([r["seq"] for r in records if r.get("action_id") == aid and r.get("event") == "verdict"] or [0])
        cleared = False
        for r in records:
            ev = r.get("event")
            if ev == "owner_saw_blocks" and str(r.get("by", "")).startswith("owner") and vseq \
                    and r.get("upto_seq", 0) >= vseq:
                cleared = True
            elif ev == "owner_decision" and r.get("action_id") == aid:
                cleared = True
            elif ev == "ag_agent_seen" and str(aid).startswith("ag-") and r.get("issue_id") == aid[3:] \
                    and str(r.get("by", "")).startswith("owner"):
                cleared = True       # v6: you saw the BW AG Grid agent's red issue (it stays yellow until fixed)
        if not cleared and not is_test_id(aid):
            out.append(aid)
    return out


LIGHT_EVENT = "light_changed"      # REDYELLOW (Trey): every color change is a timestamped History line
FIX_PAUSE_RULE = "fix_pause"        # new requests wait while you fix a red you already saw
FIX_PAUSE_TEXT = ("Bridge Warden is paused while you fix an earlier problem. New requests wait for you, so "
                  "nothing piles up.")
COLOR = {"green": "green", "gray": "yellow", "red": "red"}
_LIGHT_LOCK = __import__("threading").Lock()


def seen_upto(records: list) -> int:
    """Highest record the OWNER marked as seen ("Got it" / "I'm fine"). Only the owner can downgrade a red."""
    return max([r.get("upto_seq", 0) for r in records if r.get("event") == "owner_saw_blocks"
                and str(r.get("by", "")).startswith("owner")] or [0])


def _split_waiting(gate, recs: list) -> tuple:
    """Real (non-test) held payments split into (new, seen). Seen = the owner already saw it (its verdict is at or
    before their last "Got it"), or it was held only because Bridge Warden was paused for a fix. A new one turns the
    light red; a seen one that is still open keeps the light YELLOW (paused) until you decide it."""
    seen = seen_upto(recs)
    vseq, fix = {}, set()
    for r in recs:
        if r.get("event") == "verdict":
            aid = r.get("action_id")
            vseq.setdefault(aid, r.get("seq", 0))
            if any(f.get("rule") == FIX_PAUSE_RULE for f in (r.get("verdict") or {}).get("findings") or []):
                fix.add(aid)
    new, old = [], []
    for p in gate.pending():
        aid = p["proposal"].get("action_id")
        if is_test_id(aid):
            continue
        (old if (seen and vseq.get(aid, 0) <= seen) or aid in fix else new).append(aid)
    return new, old


OWNER_OK = "owner_light_ok"   # v6 (Trey): after ANY red, only the owner's own "It's fixed" / "Ignore + I'm sure" -> green
SEEN_FIX_TEXT = ("You responded to the red. Bridge Warden stays yellow (paused) until you confirm it's fixed, or "
                 "choose to ignore it, on the home page.")
ON_TEXT = ("Bridge Warden is back on. It stays yellow (paused) until you confirm everything is fine on the home "
           "page.")   # v6: Off is red too, so turning it on steps to yellow first, never straight to green


def red_followup(records: list) -> dict | None:
    """v6, Trey's rule: red can NEVER go straight to green, for ANY issue (blocks, unanswered alerts, held payments,
    a block aging out, the BW AG Grid agent...). After any red light, the light can only reach green after the
    OWNER's own click: "It's fixed" (owner_light_ok mode=fixed) or Ignore with "I'm sure" ticked (mode=ignored,
    sure=True). Until then it is yellow and paused. Off is red too (nothing is guarded): turning Bridge Warden back
    on steps to yellow, and the owner's own click turns it green. Returns {"since": seq of the last red} or None."""
    last_ok = max([r.get("seq", 0) for r in records if r.get("event") == OWNER_OK
                   and str(r.get("by", "")).startswith("owner")
                   and (r.get("mode") == "fixed" or (r.get("mode") == "ignored" and r.get("sure") is True))] or [0])
    reds = [r for r in records if r.get("event") == LIGHT_EVENT and r.get("to") == "red"
            and r.get("seq", 0) > last_ok]
    if not reds:
        return None
    if all(r.get("why") == "ag_agent" for r in reds):   # the agent's own issues: owner fixed / ignored it in History
        last = reds[-1]["seq"]
        if any(r.get("event") in ("ag_agent_fixed", "ag_agent_ignored") and r.get("seq", 0) > last
               and str(r.get("by", "")).startswith("owner") for r in records):
            return None
    return {"since": reds[-1]["seq"], "first": reds[0]["seq"], "off_only": all(r.get("why") == "off" for r in reds)}


def owner_light_ok(gate, mode: str, sure: bool = False, by: str = "owner (web)") -> dict:
    """The owner's own yellow -> green step after a red. mode "fixed", or "ignored" (needs sure=True). Logged."""
    if not str(by).startswith("owner"):
        return {"ok": False, "why": "only the owner can do this"}
    status(gate)                      # log the current color first, so "still red" is checked on fresh facts
    recs = gate.audit.records()
    rf = red_followup(recs)
    if rf is None:
        return {"ok": False, "why": "nothing is waiting for your OK"}
    if last_light(recs) == "red":
        gate.audit.write("owner_light_ok_refused", action_id="-", mode=mode, by=by,
                         why="red never goes straight to green: respond to the red first")
        return {"ok": False, "why": "the light is still red. Respond to the red first (it steps down to yellow)"}
    if mode not in ("fixed", "ignored"):
        return {"ok": False, "why": "unknown step"}
    if mode == "ignored" and sure is not True:
        gate.audit.write("owner_light_ok_refused", action_id="-", mode=mode, by=by, why="I'm sure was not ticked")
        return {"ok": False, "why": "tick \u201cI'm sure\u201d first"}
    gate.audit.write(OWNER_OK, action_id="-", mode=mode, sure=bool(sure), since_seq=rf["since"], by=by)
    st = status(gate)
    return {"ok": True, "state": st["state"]}


def fix_pause_reason(gate):
    """Yellow-for-a-fix: you saw a red but a held payment is still open. Automatic actions wait (gate.py)."""
    try:
        recs = gate.audit.records()
        new, old = _split_waiting(gate, recs)
        if old:
            return FIX_PAUSE_TEXT
        st = status(gate, log=False) if red_followup(recs) else {}
        if st.get("why") == "seen_fix":
            return st["text"]             # v6: yellow after a red (or after Off) = paused until your OK
        return None
    except Exception:
        return None


def status(gate, log: bool = True) -> dict:
    """The status light. Never includes agent text (it is also used for desktop alerts).
    Green = everything is working. Yellow (state "gray") = a check found something, or Bridge Warden is paused (by
    you, or while you fix a red you already saw). Red = something bad happened; it stays red until YOU respond.
    PAUSEOFF (Trey): Off = red (nothing is guarded). Paused = yellow, unless an alert you have not answered
    is still open: that stays red until you respond.
    REDYELLOW (Trey): when you respond but the problem is not fixed yet (a held payment still waits for your
    yes or no, or a state check is still open), red steps DOWN to yellow and Bridge Warden stays paused, so nothing
    piles up. Only when everything is fixed does it go green. Every color change is logged (light_changed)."""
    recs = gate.audit.records()
    pol = gate.engine.p
    paused = gate.live_pause() if hasattr(gate, "live_pause") else None
    # Dev mode test moves are shown (marked TEST) but never count toward the real light.
    new_wait, old_wait = _split_waiting(gate, recs)
    waiting = len(new_wait) + len(old_wait)
    unseen = [m for m in unseen_blocks(recs, gate.clock()) if not m.get("test") and not m.get("pause_only")]
    final = unresolved_final(recs)
    blocked = len(unseen) + len([a for a in final if a not in {m["action_id"] for m in unseen}])   # never ages out
    seq = recs[-1]["seq"] if recs else 0
    try:
        from .ag_agent import light as _ag_light
        ag = _ag_light(recs)
    except Exception:
        ag = "gray"       # can't tell: stay paused (fail safe), never green
    why = "ok"
    try:
        rf = red_followup(recs)
    except Exception:
        rf = {"since": 0}  # can't tell: stay yellow (fail safe), never green
    if final:   # stays red over pause/off/yellow: only your own clear ends it
        state, why, text = "red", "final", ("Needs you: we couldn't reach you by phone. Check PayPal now, then clear "
                                            "it here." if not waiting else f"Needs you: {waiting} payment"
                                            f"{'s' if waiting != 1 else ''} waiting for you, and we couldn't reach "
                                            "you by phone.")
    elif controls.mode(pol) == "off":   # PAUSEOFF (Trey): off = red. Nothing is guarded.
        state, why, text = "red", "off", "Off. Payments are not checked."
    elif new_wait or unseen:   # an active red alert stays red, even while paused, until you respond
        bits = []
        if waiting:
            bits.append(f"{waiting} payment{'s' if waiting != 1 else ''} waiting for you")
        if blocked:
            bits.append(f"{blocked} blocked")
        state, why, text = "red", "needs_you", "Needs you: " + ", ".join(bits) + "."
    elif ag == "red":   # v6: the BW AG Grid agent raised red. Only you step it down (I've seen this / the call).
        state, why, text = "red", "ag_agent", ("Needs you: the BW AG Grid agent found a serious problem. Open History "
                                               "and look at it.")
    elif paused:   # PAUSEOFF (Trey): paused = yellow
        state, text = "gray", "Paused. No money moves until you resume."
        why = "paused" if "paused by you" in paused else "paused_safety"   # e.g. a broken policy file
    elif old_wait:   # you saw the red, but a held payment is still open: yellow + paused until you decide it
        n = len(old_wait)
        state, why, text = "gray", "fix", (f"Paused while you fix it: {n} payment{'s' if n != 1 else ''} still "
                                           "waiting for your yes or no. Nothing new runs by itself.")
    elif ag == "gray":  # v6: BW AG Grid agent issue still open: yellow + paused until YOU fix or ignore it
        state, why, text = "gray", "ag_agent", ("Paused: the BW AG Grid agent found something. Fix it or ignore it in "
                                                "History. Nothing new runs by itself.")
    elif _check(gate):   # yellow, never over red: a state check found something; automatic actions wait
        state, why, text = "gray", "check", "Check needed. Automatic actions are paused until you clear it in Settings."
    elif rf:   # v6 (Trey): red never goes straight to green. Yellow until YOU confirm fixed or ignore (I'm sure).
        state, why, text = "gray", "seen_fix", (ON_TEXT if rf.get("off_only") else SEEN_FIX_TEXT)
    else:
        state, text = "green", "Guarding. All fine."
    out = {"state": state, "text": text, "waiting": waiting, "blocked": blocked, "seq": seq,
           "paused": bool(paused), "mode": controls.mode(pol), "check": bool(_check(gate)),
           "fix_pause": why in ("fix", "check", "ag_agent", "seen_fix"), "why": why}
    if log:
        log_light(gate, out)
    return out


def last_light(records: list) -> str:
    for r in reversed(records):
        if r.get("event") == LIGHT_EVENT and r.get("to") in COLOR:
            return r["to"]
    return "green"          # a fresh install starts green


def light_line(frm: str, to: str, why: str, text: str, frm_why: str = "") -> str:
    """The plain History line for one color change (no agent text, no money details)."""
    if to == "red" and why == "off":
        return f"Bridge Warden turned off: light set to red. {text}"
    if to == "red":
        return f"Light set to red: something bad happened. It stays red until you respond. {text}"
    if to == "gray" and why == "paused":
        return f"Bridge Warden paused by you: light set to yellow. {text}"
    if to == "gray" and frm_why == "off":
        return f"Bridge Warden turned on: light set to yellow until you confirm. {text}"
    if to == "gray" and why in ("fix", "check", "ag_agent", "seen_fix"):
        return f"Bridge Warden paused operations: light set to yellow while you fix it. {text}"
    if to == "gray" and why == "paused_safety":
        return f"Bridge Warden paused for safety: light set to yellow. {text}"
    if to == "gray":
        return f"Light set to yellow: {text}"
    if frm_why == "off":
        return "Bridge Warden turned on: light set to green. Everything is working."
    if frm == "gray":
        return "Bridge Warden resumed operations: light set to green. Everything is working."
    return "Light set to green. Everything is working."


def log_light(gate, st: dict):
    """Write one signed History line when the light changes color (green, yellow, red). Never raises."""
    try:
        with _LIGHT_LOCK:
            recs = gate.audit.records()
            frm = last_light(recs)
            frm_why = next((r.get("why", "") for r in reversed(recs) if r.get("event") == LIGHT_EVENT), "")
            if frm == st["state"]:
                return None
            clk = gate.clock() if callable(getattr(gate, "clock", None)) else datetime.now(timezone.utc)
            return gate.audit.write(LIGHT_EVENT, action_id="-", **{"from": frm}, to=st["state"],
                                    from_color=COLOR[frm], to_color=COLOR[st["state"]], why=st.get("why", ""),
                                    text=light_line(frm, st["state"], st.get("why", ""), st["text"], frm_why),
                                    clock_at=clk.isoformat(), halted=st["state"] != "green")
    except Exception:
        return None


def _check(gate):
    try:
        from .callaudit import attention
        return attention(gate)
    except Exception:
        return None


def local_time(iso: str, tz: str) -> str:
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo(tz)).strftime("%b %-d, %-I:%M %p %Z")
    except (TypeError, ValueError, KeyError):
        return "-"


def proof(gate) -> dict:
    """Export for a PayPal dispute, a bank, or an appeal. Every row points at signed audit records."""
    recs = gate.audit.records()
    ok, why = gate.audit.verify()
    tz = gate.engine.p.get("owner_timezone", "UTC")
    ms = moves(recs)
    return {
        "title": "Bridge Warden: record of money moves",
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "owner_timezone": tz,
        "sandbox_only": True,
        "audit_log_check": {"intact": ok, "detail": why},
        "chain_head": {"seq": recs[-1]["seq"], "hash": recs[-1]["hash"]} if recs else None,
        "policy_sha256": (gate.policy_info or {}).get("sha256") if hasattr(gate, "policy_info") else None,
        "how_to_check": ("Each row lists the audit records behind it (sequence number and SHA-256). The owner can "
                         "run 'python -m bridge_warden audit --verify' on the full log; every record is "
                         "hash-chained and signed (HMAC), so a changed or removed record breaks the check."),
        "moves": [{**{k: m[k] for k in ("action_id", "at", "action", "amount", "currency", "payee", "description",
                                         "status", "label", "why", "reasons", "risk_score", "proposal_hash",
                                         "decided_by", "result", "records")},
                   "at_local": local_time(m["at"], tz)} for m in ms],
    }


def proof_text(p: dict) -> str:
    L = [p["title"], "=" * len(p["title"]), f"Made: {p['made_at']} (UTC)",
         f"Audit log check: {'INTACT' if p['audit_log_check']['intact'] else 'FAILED - ' + p['audit_log_check']['detail']}"]
    if p["chain_head"]:
        L.append(f"Last record: #{p['chain_head']['seq']}  {p['chain_head']['hash']}")
    L += ["Sandbox only: no real money.", "", p["how_to_check"], ""]
    for m in p["moves"]:
        L += [f"{m['at_local']}  {m['label'].upper()}",
              f"  {VERB.get(m['action'], m['action'])} {m['payee']}  {money(m['amount'], m['currency'])}",
              f"  Agent said: {m['description']}", f"  Why: {m['why']}"]
        L += [f"   - {r}" for r in m["reasons"]]
        if m["decided_by"]:
            L.append(f"  Decided by: {m['decided_by']}")
        L.append(f"  Fingerprint: {m['proposal_hash']}")
        L.append("  Records: " + ", ".join(f"#{r['seq']} {r['event']}" for r in m["records"]))
        L.append("")
    return "\n".join(L) + "\n"
