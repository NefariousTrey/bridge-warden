"""The BW AG Grid agent (v6). It lives on the History page.

What it does (all READ-ONLY on money):
  1. Audits Bridge Warden's OWN actions from the signed History: hash chain, a held or blocked payment that ran
     without your yes, a yes that does not match the payment, money sent twice, repeated blocks, a light stuck
     on red, an alert nobody closed, clock going backwards.
  2. Cross-checks the xAI outputs: BW's xAI risk notes, AI summaries on verdicts, and its own AI summaries.
     Flags an AI note that contradicts the local rule result, names amounts that are not in the data, or tells
     you to do something Bridge Warden did not do (e.g. "send it" on a blocked payment).
     Mutual check: local rules + this agent check xAI; xAI only explains. xAI never decides anything here.
  3. Reads the money map (money_map.py): refund spikes and unusual amounts.

What it may do to the light (Trey, Oct 27 2026), through the SAME path Bridge Warden already uses:
  * raise it to YELLOW (pause: new requests wait for you) or RED (alert: in-app always, call / email by your
    alert rules, dry run in Dev mode). Every step is a signed History line, and the light change is logged too.
  * NEVER: turn it green, approve, release a hold, change a verdict, or move money. There is no code path here
    that writes owner_decision, executes, or calls PayPal.
How it steps down (only YOU):
  * RED -> YELLOW: you click "I've seen this" in the app, or you answer the fraud alert call. Nothing else.
  * YELLOW -> GREEN: you click in the app: "Fixed, confirm" or "Ignore" with the "I'm sure" box ticked.
  * RED can never go straight to GREEN. Nothing steps down by time, by a later scan, or by an AI.
Made by @Nefarious_Trey, with Grok. Copyright 2026 Douglas Gibbons III. Apache-2.0.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

NAME = "BW AG Grid agent"
SOURCE = "bw-ag-grid-agent"          # agent_id / source on every line it writes
ISSUE = "ag_agent_issue"             # raised (level yellow | red)
SEEN = "ag_agent_seen"               # owner saw it (red -> yellow)
FIXED = "ag_agent_fixed"             # owner confirmed it is fixed (yellow -> green)
IGNORED = "ag_agent_ignored"         # owner ignored it, with "I'm sure" ticked (yellow -> green)
SCAN = "ag_agent_scan"               # one scan ran (what it found, what it raised)
AI_NOTE = "ag_agent_ai"              # the agent's own xAI summary (text kept so it can be cross-checked too)
STEP_REFUSED = "ag_agent_step_refused"
ACTION_PREFIX = "ag-"
LEVELS = ("info", "yellow", "red")
SURE_SEND = "I'm sure, send this held payment"
SURE_TEXT = "I'm sure, I want to ignore this"
RECOMMEND = "We recommend fixing this instead of ignoring it. It's your money, your call."
DEFAULTS = {"red_stuck_hours": 24, "repeat_blocks": 3, "repeat_days": 7, "money_spikes_raise": True}
EVENTS = (ISSUE, SEEN, FIXED, IGNORED, SCAN, AI_NOTE, STEP_REFUSED)


def _when(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _f(kind, level, text, *, key, area, seq=None, action=None, evidence=None):
    return {"kind": kind, "level": level, "text": text, "key": f"{kind}:{key}", "area": area, "seq": seq,
            "action": action, "evidence": evidence or {}}


# ------------------------------------------------------------------ 1. Bridge Warden's own actions
def audit_actions(records: list, verify: tuple, now: datetime | None = None, cfg: dict | None = None) -> list:
    cfg = {**DEFAULTS, **(cfg or {})}
    now = now or datetime.now(timezone.utc)
    out = []
    ok, why = verify
    if not ok:
        out.append(_f("chain_broken", "red", f"Your signed history does not check out ({why}). Someone or something "
                      "may have changed it. Download your proof now and do not trust this copy.", key=why,
                      area="history"))
    verdict, proposal_hash, decisions, executed, proposed = {}, {}, defaultdict(list), defaultdict(list), {}
    blocks_by_payee = defaultdict(list)
    last_at = None
    for r in records:
        ev, aid, seq = r.get("event"), r.get("action_id"), r.get("seq")
        at = _when(r.get("at"))
        if at and last_at and at < last_at - timedelta(minutes=5):
            out.append(_f("clock_back", "yellow", f"History line #{seq} is dated earlier than the line before it. "
                          "The computer clock may have jumped.", key=seq, area="history", seq=seq))
        last_at = at or last_at
        if ev == "proposed":
            proposed.setdefault(aid, r)
        elif ev == "verdict" and aid not in verdict:
            verdict[aid] = (r.get("verdict") or {}).get("verdict")
            proposal_hash[aid] = r.get("proposal_hash")
            p = (proposed.get(aid) or {}).get("proposal") or {}
            if verdict[aid] == "block" and p.get("agent_id") != SOURCE and at:
                blocks_by_payee[str(p.get("payee", ""))].append((at, seq))
        elif ev == "owner_decision":
            decisions[aid].append(r)
            if aid not in proposed:
                out.append(_f("decision_no_request", "yellow", f"History line #{seq} records your answer for a "
                              "request that was never logged.", key=seq, area="actions", seq=seq, action=aid))
            elif r.get("decision") == "yes" and r.get("proposal_hash") != proposal_hash.get(aid):
                out.append(_f("yes_mismatch", "red", "Your yes does not match the payment that was checked. "
                              "The payment may have been swapped.", key=aid, area="actions", seq=seq, action=aid))
        elif ev == "executed":
            executed[aid].append(r)
            v = verdict.get(aid)
            yes = any(d.get("decision") == "yes" for d in decisions[aid])
            if v is None:
                out.append(_f("ran_unchecked", "red", "Money was marked sent with no safety check on record.",
                              key=aid, area="actions", seq=seq, action=aid))
            elif v == "block":
                out.append(_f("ran_after_block", "red", "A BLOCKED payment was marked sent. That must never "
                              "happen.", key=aid, area="actions", seq=seq, action=aid))
            elif v == "hold" and not yes:
                out.append(_f("hold_released_no_yes", "red", "A HELD payment was marked sent without your yes.",
                              key=aid, area="actions", seq=seq, action=aid))
            if len(executed[aid]) == 2:
                out.append(_f("sent_twice", "red", "The same payment was marked sent twice.", key=aid,
                              area="actions", seq=seq, action=aid))
    for payee, items in blocks_by_payee.items():
        items.sort()
        for i in range(len(items)):
            win = [x for x in items[i:] if x[0] - items[i][0] <= timedelta(days=int(cfg["repeat_days"]))]
            if len(win) >= int(cfg["repeat_blocks"]):
                out.append(_f("repeat_blocks", "yellow", f"Your agent tried {len(win)} times in "
                              f"{cfg['repeat_days']} days to pay someone Bridge Warden blocked. It may be tricked, "
                              "or stuck.", key=f"{payee}:{win[-1][1]}", area="actions", seq=win[-1][1]))
                break
    # light stuck on red, and light lines that do not join up
    lights = [r for r in records if r.get("event") == "light_changed"]
    prev = "green"   # a fresh install starts green (join-up check only, never written)
    for r in lights:
        if r.get("from") != prev:
            out.append(_f("light_jump", "yellow", f"History line #{r.get('seq')} says the light changed from "
                          f"{r.get('from_color', r.get('from'))}, but it was {prev} before.", key=r.get("seq"),
                          area="light", seq=r.get("seq")))
        prev = r.get("to")
    if lights and lights[-1].get("to") == "red":
        t = _when(lights[-1].get("clock_at") or lights[-1].get("at"))
        if t and now - t > timedelta(hours=int(cfg["red_stuck_hours"])):
            out.append(_f("red_stuck", "yellow", f"The light has been red for more than {cfg['red_stuck_hours']} "
                          "hours. Something still needs you.", key=lights[-1].get("seq"), area="light",
                          seq=lights[-1].get("seq")))
    raised = {r.get("for_action"): r for r in records if r.get("event") == "alert_raised"}
    closed = {r.get("for_action") for r in records if r.get("event") in (
        "alert_answered", "alert_acknowledged", "alert_final_notice", "alert_retry_stopped")}
    closed |= {r.get("action_id") for r in records if r.get("event") == "owner_decision"}
    seen_upto = max([r.get("upto_seq", 0) for r in records if r.get("event") == "owner_saw_blocks"] or [0])
    for aid, r in raised.items():
        t = _when(r.get("at"))
        if aid not in closed and r.get("seq", 0) > seen_upto and t and now - t > timedelta(hours=24):
            out.append(_f("alert_open", "yellow", "An alert was raised more than a day ago and nobody closed it.",
                          key=aid, area="alerts", seq=r.get("seq"), action=aid))
    return out


# ------------------------------------------------------------------ 2. cross-check the xAI outputs
_MONEY = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_SAYS_SAFE = re.compile(r"\b(safe to (send|pay)|looks (safe|fine|legit)|low risk|no (red flags|risk)|"
                        r"nothing (wrong|suspicious))\b", re.I)
_SAYS_BAD = re.compile(r"\b(scam|fraud|block(ed)?|do not (send|pay)|don't (send|pay)|high risk)\b", re.I)
_TELLS_ACT = re.compile(r"\b(go ahead and (send|pay)|send it( now)?|approve (it|this|the payment)|release (it|the "
                        r"hold)|pay (it|them) now|i (have )?(approved|sent|released|refunded|paid))\b", re.I)


def _amounts(text: str) -> set:
    out = set()
    for m in _MONEY.finditer(text or ""):
        try:
            out.add(round(float(m.group(1).replace(",", "")), 2))
        except ValueError:
            pass
    return out


def _known_amounts(records: list, extra=()) -> set:
    out = set(round(float(x), 2) for x in extra)
    for r in records:
        for p in (r.get("proposal") or {},):
            try:
                out.add(round(float(p.get("amount")), 2))
            except (TypeError, ValueError):
                pass
    return out


def check_ai_text(text: str, local_verdict: str | None, known: set, *, key, seq=None, action=None,
                  where="xAI note") -> list:
    """Local rules check one AI text. local_verdict: allow | hold | block | None (a money summary)."""
    out = []
    t = str(text or "")
    if not t.strip():
        return out
    if local_verdict in ("hold", "block") and _SAYS_SAFE.search(t):
        out.append(_f("ai_contradicts", "yellow", f"The {where} calls this safe, but Bridge Warden's own rules said "
                      f"{local_verdict.upper()}. The rules win. Do not act on the AI note alone.", key=key,
                      area="ai", seq=seq, action=action, evidence={"ai_said": t[:200]}))
    if local_verdict == "allow" and _SAYS_BAD.search(t) and not _SAYS_SAFE.search(t):
        out.append(_f("ai_contradicts", "yellow", f"The {where} sounds worried, but this payment was allowed. "
                      "Take a second look.", key=key, area="ai", seq=seq, action=action,
                      evidence={"ai_said": t[:200]}))
    m = _TELLS_ACT.search(t)
    if m and local_verdict != "allow":
        out.append(_f("ai_told_action", "red" if local_verdict == "block" else "yellow",
                      f"The {where} says \u201c{m.group(0)}\u201d, but Bridge Warden did not do that. An AI can never "
                      "send, approve or release. Only you can.", key=key, area="ai", seq=seq, action=action,
                      evidence={"ai_said": t[:200]}))
    extra = sorted(a for a in _amounts(t) if a not in known)
    if extra:
        out.append(_f("ai_made_up", "yellow", f"The {where} mentions ${extra[0]:,.2f}, which is not in your data. "
                      "It may be made up.", key=key, area="ai", seq=seq, action=action,
                      evidence={"ai_said": t[:200]}))
    return out


def audit_ai(records: list, money_amounts=()) -> list:
    known = _known_amounts(records, money_amounts)
    verdicts = {}
    out = []
    for r in records:
        ev, aid, seq = r.get("event"), r.get("action_id"), r.get("seq")
        if ev == "verdict":
            vd = r.get("verdict") or {}
            verdicts.setdefault(aid, vd.get("verdict"))
            if vd.get("ai_summary"):
                out += check_ai_text(vd["ai_summary"], vd.get("verdict"), known, key=f"sum:{seq}", seq=seq,
                                     action=aid, where="AI summary")
        elif ev == "ai_check":
            res = r.get("result") or {}
            p = res.get("parsed") or {}
            if not p:
                continue
            final = r.get("verdict_after")
            if p.get("risk") == "high" and final == "allow":
                out.append(_f("ai_ignored", "red", "xAI said HIGH risk but the payment was allowed. The AI can only "
                              "make things stricter, so this should not happen.", key=seq, area="ai", seq=seq,
                              action=aid))
            if p.get("suggested_verdict") == "allow" and r.get("verdict_before") == "block":
                out.append(_f("ai_disagreed", "info", "xAI thought this was fine, but the local rules blocked it. "
                              "The rules won, as designed.", key=seq, area="ai", seq=seq, action=aid))
            out += check_ai_text(p.get("reason", ""), final, known, key=f"chk:{seq}", seq=seq, action=aid,
                                 where="xAI risk note")
        elif ev == AI_NOTE and r.get("text"):
            out += check_ai_text(r["text"], None, known | set(r.get("numbers") or []), key=f"own:{seq}", seq=seq,
                                 where="agent's own AI summary")
    return out


# ------------------------------------------------------------------ 3. money spikes (from money_map)
def money_findings(report: dict | None, cfg: dict | None = None) -> list:
    cfg = {**DEFAULTS, **(cfg or {})}
    out = []
    for f in (report or {}).get("flags", []):
        lvl = "yellow" if f["kind"] in ("refund_spike", "unusual") and cfg["money_spikes_raise"] else "info"
        k = hashlib.sha256(f["text"].encode()).hexdigest()[:12]
        out.append(_f("money_" + f["kind"], lvl, f["text"], key=k, area="money"))
    return out


def scan(records: list, verify: tuple, report: dict | None = None, now=None, cfg=None) -> list:
    nums = []
    for ln in (report or {}).get("lines", []):
        nums.append(ln["amount"])
    for v in (report or {}).get("totals", {}).values():
        nums.append(v)
    nums += [(report or {}).get("total", 0), (report or {}).get("refunds", 0)]
    found = audit_actions(records, verify, now, cfg) + audit_ai(records, nums) + money_findings(report, cfg)
    seen, out = set(), []
    for f in found:
        if f["key"] not in seen:
            seen.add(f["key"])
            out.append(f)
    order = {"red": 0, "yellow": 1, "info": 2}
    out.sort(key=lambda f: order[f["level"]])
    return out


# ------------------------------------------------------------------ issues and the light
def issues(records: list) -> list:
    """Every issue the agent raised, with where it stands. status: red | yellow | fixed | ignored."""
    out, by_id = [], {}
    seen_upto = 0
    for r in records:
        ev = r.get("event")
        if ev == ISSUE:
            it = {"id": r["issue_id"], "key": r.get("key"), "level": r.get("level"), "text": r.get("text", ""),
                  "kind": r.get("kind", ""), "area": r.get("area", ""), "seq": r.get("seq"), "at": r.get("at"),
                  "action_id": r.get("for_action"), "seen": False, "status": r.get("level"), "steps": []}
            by_id[it["id"]] = it
            out.append(it)
            continue
        if ev == "owner_saw_blocks" and str(r.get("by", "")).startswith("owner"):
            seen_upto = max(seen_upto, r.get("upto_seq", 0))
            for it in out:
                if it["status"] == "red" and it["seq"] <= seen_upto:
                    it["seen"], it["status"] = True, "yellow"
                    it["steps"].append(("seen", r.get("seq"), "owner marked blocks seen"))
            continue
        if ev in ("alert_answered", "alert_acknowledged"):        # the owner answered the fraud call / opened it
            for it in out:
                if it["status"] == "red" and it["action_id"] and it["action_id"] == r.get("for_action"):
                    it["seen"], it["status"] = True, "yellow"
                    it["steps"].append(("seen", r.get("seq"), "answered the alert call" if ev == "alert_answered"
                                        else "opened the alert"))
            continue
        it = by_id.get(r.get("issue_id"))
        if it is None:
            continue
        if ev == SEEN and it["status"] == "red":
            it["seen"], it["status"] = True, "yellow"
            it["steps"].append(("seen", r.get("seq"), r.get("by", "")))
        elif ev in (FIXED, IGNORED) and it["status"] == "yellow":
            it["status"] = "fixed" if ev == FIXED else "ignored"
            it["steps"].append((it["status"], r.get("seq"), r.get("by", "")))
    return out


def light(records: list) -> str | None:
    """'red' if any agent issue is still unseen red, 'gray' (yellow) if any is open, else None."""
    st = [i["status"] for i in issues(records)]
    if "red" in st:
        return "red"
    if "yellow" in st:
        return "gray"
    return None


def hold_reason(gate) -> str | None:
    """Automatic actions wait while an agent issue is open (same pause path as the state check)."""
    try:
        s = light(gate.audit.records())
    except Exception:
        return None
    if s is None:
        return None
    return f"The {NAME} found something that needs you. New requests wait until you deal with it in History."


def _issue_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:10]


def raise_light(gate, finding: dict, *, by: str = SOURCE, alerts=None) -> dict | None:
    """Raise YELLOW or RED for one finding, the way Bridge Warden already does it. Returns the issue, or None
    when nothing was raised (info only, or this exact finding was raised before - fixed or ignored stays so).
    RED also writes a BLOCK record (like an outside PayPal event, never a HOLD: a hold could be approved into a
    payment) and fires the normal alert (in-app always; call / email by your alert rules; dry run in Dev mode)."""
    level = finding.get("level")
    if level not in ("yellow", "red"):
        return None
    recs = gate.audit.records()
    if any(r.get("event") == ISSUE and r.get("key") == finding["key"] for r in recs):
        return None
    iid = _issue_id(finding["key"])
    aid = ACTION_PREFIX + iid
    rec = gate.audit.write(ISSUE, action_id="-", issue_id=iid, key=finding["key"], level=level,
                           kind=finding["kind"], area=finding.get("area", ""), text=finding["text"][:400],
                           for_action=aid if level == "red" else None, by=by, read_only=True,
                           clock_at=gate.clock().isoformat())
    out = {"issue_id": iid, "level": level, "seq": rec.get("seq")}
    if level == "red":
        from .gate import proposal_hash
        from .models import BLOCK, Finding, ProposedAction, Verdict
        a = ProposedAction("payout", "0.00", "USD", payee=NAME,
                           description=f"{NAME}: {finding['text']}"[:600], agent_id=SOURCE, action_id=aid)
        pd = a.to_dict()
        h = proposal_hash(pd)
        v = Verdict(aid, BLOCK, 100, [Finding("ag_agent", BLOCK, finding["text"][:300], 100)])
        gate.audit.write("proposed", action_id=aid, proposal=pd, proposal_hash=h)
        gate.audit.write("verdict", action_id=aid, verdict=v.to_dict(), proposal_hash=h,
                         clock_at=gate.clock().isoformat())
        try:
            from . import notify as N
            if N.judge_acting():   # PREFLIP 2026-11-02: a judge's raise never reaches Twilio or email
                from . import alerts as AL
                alerts = AL.Alerts(gate, caller=N.DryRunCallAdapter(), email=AL.DryRunEmail(), retries=False)
            elif alerts is None:
                alerts = N.Notifier(gate).alerts()
            out["alert"] = alerts.fire(aid, source=SOURCE, wait=False)
        except Exception as ex:      # the in-app red still stands
            out["alert_error"] = type(ex).__name__
    else:
        from .callaudit import _email
        gate.audit.write("state_check_alert", action_id="-", note=f"{NAME}: {finding['text']}"[:600], source=SOURCE)
        out["email"] = _email(gate, f"{NAME}: {finding['text']}")
    _log_light(gate)
    return out


def _log_light(gate):
    try:
        from .dashboard import status
        status(gate)
    except Exception:
        pass


def run_scan(gate, report: dict | None = None, *, by: str = "owner (web)", now=None, cfg=None, alerts=None,
             raise_lights: bool = True) -> dict:
    """One scan: find, log, raise. Never steps anything down."""
    recs = gate.audit.records()
    pol = (getattr(getattr(gate, "engine", None), "p", {}) or {}).get("ag_agent") or {}
    found = scan(recs, gate.audit.verify(), report, now or gate.clock(), {**pol, **(cfg or {})})
    raised = []
    if raise_lights:
        for f in found:
            r = raise_light(gate, f, alerts=alerts)
            if r:
                raised.append(r)
    gate.audit.write(SCAN, action_id="-", by=by, read_only=True, found=len(found),
                     red=len([f for f in found if f["level"] == "red"]),
                     yellow=len([f for f in found if f["level"] == "yellow"]),
                     raised=[{"issue_id": r["issue_id"], "level": r["level"]} for r in raised])
    return {"found": found, "raised": raised}


def request_raise(gate, key: str, level: str, report: dict | None = None, *, by: str = "BW AG Grid agent (AI)",
                  alerts=None) -> dict:
    """An AI (the Studio agent) asks to raise the light. Allowed only for a finding the LOCAL rules made, and
    never above the level the local rules gave it. It can only raise; it has no way to step down."""
    if level not in ("yellow", "red"):
        return {"ok": False, "why": "An AI can only raise the light to yellow or red."}
    found = {f["key"]: f for f in scan(gate.audit.records(), gate.audit.verify(), report, gate.clock())}
    f = found.get(str(key or ""))
    if f is None:
        return {"ok": False, "why": "No such finding from the local rules."}
    if LEVELS.index(level) > LEVELS.index(f["level"]):
        return {"ok": False, "why": f"The local rules rate this {f['level']}, so it cannot be raised to {level}."}
    r = raise_light(gate, {**f, "level": level}, by=by, alerts=alerts)
    return {"ok": True, "raised": r} if r else {"ok": True, "raised": None, "why": "Already raised before."}


# ------------------------------------------------------------------ owner steps (web owner session only)
def _find(gate, iid):
    return next((i for i in issues(gate.audit.records()) if i["id"] == iid), None)


def _refuse(gate, iid, step, why, by):
    gate.audit.write(STEP_REFUSED, action_id="-", issue_id=str(iid)[:20], step=step, why=why, by=by)
    return {"ok": False, "why": why}


def _owner(by: str) -> bool:
    return isinstance(by, str) and by.startswith("owner")


def mark_seen(gate, iid: str, by: str = "owner (web)") -> dict:
    """RED -> YELLOW. Owner only."""
    it = _find(gate, iid)
    if not _owner(by):
        return _refuse(gate, iid, "seen", "only the owner can do this", by)
    if it is None or it["status"] != "red":
        return _refuse(gate, iid, "seen", "not an open red issue", by)
    gate.audit.write(SEEN, action_id="-", issue_id=iid, by=by)
    if it.get("action_id"):
        from .alerts import acknowledge
        acknowledge(gate, it["action_id"], by=by)   # stops call retries for it, as for any alert you opened
    _log_light(gate)
    return {"ok": True, "status": "yellow"}


def mark_fixed(gate, iid: str, by: str = "owner (web)") -> dict:
    """YELLOW -> GREEN (if nothing else is open). Owner only. A red must be seen first: never red -> green."""
    it = _find(gate, iid)
    if not _owner(by):
        return _refuse(gate, iid, "fixed", "only the owner can do this", by)
    if it is None or it["status"] != "yellow":
        return _refuse(gate, iid, "fixed", "see it first (red never goes straight to green)" if it and
                       it["status"] == "red" else "not an open yellow issue", by)
    gate.audit.write(FIXED, action_id="-", issue_id=iid, by=by)
    _log_light(gate)
    return {"ok": True, "status": "fixed"}


def mark_ignored(gate, iid: str, sure: bool, by: str = "owner (web)") -> dict:
    """YELLOW -> GREEN by ignoring. Owner only, and only with "I'm sure" ticked."""
    it = _find(gate, iid)
    if not _owner(by):
        return _refuse(gate, iid, "ignored", "only the owner can do this", by)
    if not sure:
        return _refuse(gate, iid, "ignored", "the I'm sure box was not ticked", by)
    if it is None or it["status"] != "yellow":
        return _refuse(gate, iid, "ignored", "see it first (red never goes straight to green)" if it and
                       it["status"] == "red" else "not an open yellow issue", by)
    gate.audit.write(IGNORED, action_id="-", issue_id=iid, by=by, sure=True, sure_text=SURE_TEXT)
    _log_light(gate)
    return {"ok": True, "status": "ignored"}


def log_ai_note(gate, text: str, numbers=()) -> dict:
    """Keep the agent's own AI summary in History so the next scan cross-checks it like any xAI output."""
    return gate.audit.write(AI_NOTE, action_id="-", text=str(text)[:600],
                            numbers=[round(float(n), 2) for n in list(numbers)[:200]])
