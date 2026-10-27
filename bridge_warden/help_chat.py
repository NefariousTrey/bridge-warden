"""v6: two help chats, each in its own lane. Read-only. No buttons. Your own xAI key (your cost).

  * "BW help chat (xAI)" - what is happening NOW: the light, held payments, blocks, alerts and calls, and open
    BW AG Grid agent issues. Home page.
  * "BW AG Grid agent chat" - your HISTORY: past and ongoing patterns, spending groups, subscriptions, and the
    agent's audit flags (Bridge Warden's own actions and the xAI notes). History page. When the AG Studio bundle
    is installed, the same lane also runs in AG Studio's own chat panel (Agent Framework, see static/bw-studio.js).

Both walk you through a fix step by step, the same way the fraud call walks you through PayPal's steps. Steps
come from LOCAL rules (free, no AI). "Next" / "done" moves to the next step without any AI call. Only a real
question goes to xAI, with redacted data, short answers, and the usage the API reports shown under the answer.
Neither chat can approve, ignore, turn anything green, change a setting or move money. Their answers are text.
Made by @Nefarious_Trey, with Grok. Copyright 2026 Douglas Gibbons III. Apache-2.0.
"""
from __future__ import annotations

import re

from . import ag_agent as AG
from . import dashboard as D
from .notify import LOCK_STEPS

NOW, HISTORY = "now", "history"
TITLE = {NOW: "BW help chat (xAI)", HISTORY: "BW AG Grid agent chat"}
LANE_WHAT = {NOW: "what is happening now: the light, held payments, blocks, alerts and calls",
             HISTORY: "your history: spending groups, subscriptions, patterns, and the agent's audit flags"}
TICKS_PER_USD = 10_000_000_000          # xAI: usage.cost_in_usd_ticks / 1e10 = dollars (docs.x.ai cost-tracking)
NO_LIMIT = "limit not available from provider"
NEXT_WORDS = re.compile(r"^\s*(next|done|ok(ay)?|did it|finished|go on|continue)\s*[.!]?\s*$", re.I)
BACK_WORDS = re.compile(r"^\s*(back|previous|repeat|again)\s*[.!]?\s*$", re.I)
_HISTORY_Q = re.compile(r"\b(spend|spent|spending|subscri|subs?\b|bill|bills|gas|food|grocer|month|last week|"
                        r"last month|pattern|trend|duplicate|unused|price (went )?up|refund spike|category|budget|"
                        r"audit|history|chain)\w*", re.I)
_NOW_Q = re.compile(r"\b(hold|held|waiting|pending|blocked|block|alert|call(ed)?|ring|light|red|yellow|now|today|"
                    r"right now|lock|password|hacked|scam|fraud|send|cancel)\w*", re.I)
_ON_TOPIC = re.compile(r"\b(paypal|bridge warden|bw|pay|payment|money|refund|charge|subscri|bill|light|alert|call|"
                       r"hold|block|scam|fraud|agent|flag|issue|fix|ignore|seen|step|spend|account|password|safe|"
                       r"gas|food|history|why|what|how)\w*", re.I)
SCOPE = {
    NOW: ("You are the 'BW help chat'. Your lane is ONLY what is happening now in Bridge Warden: the light, held "
          "payments, blocked payments, alerts and calls, and how to fix them in PayPal step by step. If asked about "
          "past spending, subscriptions or history patterns, say: 'Ask the BW AG Grid agent chat on the History "
          "page.' If asked about anything not Bridge Warden or PayPal, say you can only help with those. "
          "Answer in at most 3 short sentences. You cannot press any button. Never say you approved, ignored, "
          "turned the light green, sent, refunded or moved money."),
    HISTORY: ("You are the 'BW AG Grid agent chat'. Your lane is ONLY the person's History: spending groups (bills, "
              "subscriptions, gas, food, other), duplicate or maybe-unused subscriptions, refund spikes, unusual "
              "amounts, and the agent's audit flags. If asked about what is happening right now (a held payment, "
              "a call, an alert), say: 'Ask the BW help chat on the Home page.' If asked about anything not Bridge "
              "Warden or PayPal, say you can only help with those. Use only numbers that are in the data. Answer "
              "in at most 3 short sentences. You cannot press any button or change anything."),
}


# ------------------------------------------------------------------ lanes
def route(question: str, lane: str) -> str:
    """'ok' | 'other_lane' | 'off_topic'. Local, free, before any AI call."""
    q = str(question or "")
    if not _ON_TOPIC.search(q):
        return "off_topic"
    h, n = len(_HISTORY_Q.findall(q)), len(_NOW_Q.findall(q))
    if lane == NOW and h > n:
        return "other_lane"
    if lane == HISTORY and n > h and not re.search(r"\b(flag|issue|audit)", q, re.I):
        return "other_lane"
    return "ok"


def local_reply(kind: str, lane: str) -> str:
    if kind == "other_lane":
        return ("That's a History question. Ask the BW AG Grid agent chat on the History page." if lane == NOW else
                "That's about what is happening now. Ask the BW help chat on the Home page.")
    return "I can only help with Bridge Warden and PayPal issues."


# ------------------------------------------------------------------ step-by-step guides (local rules, free)
def _issue_steps(it: dict) -> list:
    tip = {
        "chain_broken": "Download your proof from History (Export) and keep it safe. Then check PayPal Activity "
                        "yourself.",
        "hold_released_no_yes": "Open PayPal Activity yourself and find that payment. If you did not mean it, use "
                                "Report a problem on it.",
        "ran_after_block": "Open PayPal Activity yourself and find that payment. If you did not mean it, use Report "
                           "a problem on it.",
        "sent_twice": "Open PayPal Activity and look for the same payment two times. Ask the person to refund one.",
        "repeat_blocks": "Check your agent's instructions. Someone may be pushing it to pay a scammer.",
        "red_stuck": "Go to Home and answer what is waiting.",
        "alert_open": "Go to Home and open the alert.",
    }.get(it.get("kind", "").replace("money_", ""), "Read the issue and check it in PayPal yourself.")
    if it.get("kind", "").startswith("ai_"):
        tip = "Trust Bridge Warden's own rule result, not the AI note. Check the payment in PayPal yourself."
    steps = []
    if it["status"] == "red":
        steps.append("Open History and read the red issue from the BW AG Grid agent.")
        steps.append("Click \u201cI've seen this\u201d. The light steps down to yellow (paused).")
    steps.append(tip)
    steps.append("When it is fixed, click \u201cIt's fixed, confirm\u201d. Or tick \u201cI'm sure\u201d and click "
                 "Ignore. Fixing is better. Only you can press these.")
    return steps


SUB_STEPS = ("Open the PayPal app or paypal.com yourself.",
             "Go to Settings, then Payments, then Manage automatic payments.",
             "Find the service. If you see it twice, or you no longer use it, pick it.",
             "Tap Cancel and confirm. If the service bills you directly, cancel on its own site too.",
             "Come back to History. When it is done, click \u201cIt's fixed, confirm\u201d on the flag.")
REFUND_STEPS = ("Open PayPal Activity yourself and filter by Refunds.",
                "Check each refund: did you ask for it? Do you know the seller?",
                "If any look wrong, use Report a problem on that payment, then change your PayPal password.",
                "Come back to History and confirm it is fixed, or ignore it with the box ticked.")
HOLD_STEPS = ("Read who it pays and how much, on the Home page.",
              "Ask yourself: did you or your agent mean to pay them? Is anyone rushing you?",
              "If unsure, check with the person another way, on a number you already trust.",
              "Decide on Home: Send (tick \u201cI'm sure\u201d first) or Cancel. Only you can press it.")


def guide(gate, lane: str, report: dict | None = None) -> dict:
    """{'title', 'steps'} for the most urgent thing in this lane. Local rules only."""
    recs = gate.audit.records()
    open_issues = [i for i in AG.issues(recs) if i["status"] in ("red", "yellow")]
    if lane == NOW:
        if any(D.unresolved_final(recs)) or [m for m in D.unseen_blocks(recs, gate.clock())
                                             if not str(m["action_id"]).startswith("ag-")]:
            return {"title": "Lock your PayPal (same steps as the call)", "steps": list(LOCK_STEPS)}
        if gate.pending():
            return {"title": "A payment is waiting for you", "steps": list(HOLD_STEPS)}
        if open_issues:
            it = sorted(open_issues, key=lambda i: i["status"] != "red")[0]
            return {"title": "Fix the BW AG Grid agent issue", "steps": _issue_steps(it), "issue": it["id"]}
        return {"title": "All fine right now", "steps": ["Nothing needs you right now. The light is green."]}
    hist = [i for i in open_issues if i["kind"].startswith("money_") or i.get("area") in ("history", "actions", "ai")]
    if hist:
        it = sorted(hist, key=lambda i: i["status"] != "red")[0]
        if it["kind"] == "money_refund_spike":
            return {"title": "Check the refund spike", "steps": list(REFUND_STEPS), "issue": it["id"]}
        return {"title": "Fix the BW AG Grid agent issue", "steps": _issue_steps(it), "issue": it["id"]}
    kinds = {f["kind"] for f in (report or {}).get("flags", [])}
    if kinds & {"duplicate", "still_use", "price_up"}:
        return {"title": "Tidy your subscriptions", "steps": list(SUB_STEPS)}
    if "refund_spike" in kinds:
        return {"title": "Check the refund spike", "steps": list(REFUND_STEPS)}
    return {"title": "Nothing to fix in History", "steps": ["Your History looks fine. Nothing to fix."]}


# ------------------------------------------------------------------ what the AI may see (redacted)
def context(gate, lane: str, report: dict | None, step: str = "") -> dict:
    recs = gate.audit.records()
    st = D.status(gate, log=False)
    issues = [{"level": i["status"], "what": i["text"][:200]} for i in AG.issues(recs) if i["status"] in ("red", "yellow")]
    if lane == NOW:
        held = [{"amount": p["proposal"].get("amount"), "currency": p["proposal"].get("currency"),
                 "why": D.why_line(p["verdict"], p["proposal"])[:200], "payee": "payee A"} for p in gate.pending()[:5]]
        alerts = [r.get("event") for r in recs if str(r.get("event", "")).startswith("alert_")][-6:]
        return {"lane": "now", "light": {"green": "green", "gray": "yellow"}.get(st["state"], st["state"]),
                "light_text": st["text"], "held_payments": held, "blocked_unseen": st["blocked"],
                "recent_alert_steps": alerts, "open_agent_issues": issues, "current_fix_step": step}
    from .money_map import redacted
    return {"lane": "history", "money": redacted(report) if report else {}, "open_agent_issues": issues,
            "flags": [f["text"][:160] for f in (report or {}).get("flags", [])[:12]], "current_fix_step": step}


# ------------------------------------------------------------------ usage line (real numbers only)
def usage_line(res: dict) -> str:
    """Only what the xAI API itself returned. No estimates."""
    u = res.get("usage") or {}
    if not res.get("called"):
        return "No AI call, no cost."
    bits = []
    if u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None:
        bits.append(f"{u['prompt_tokens']} in + {u['completion_tokens']} out tokens")
    if isinstance(u.get("cost_in_usd_ticks"), int):
        bits.append(f"cost ${u['cost_in_usd_ticks'] / TICKS_PER_USD:.5f} (from xAI)")
    else:
        bits.append("cost not reported by xAI")
    bits.append(f"remaining credit: {NO_LIMIT}")
    return "This answer used " + ", ".join(bits) + "."


def check_answer(text: str, report: dict | None, gate) -> list:
    """Mutual check: local rules + the BW AG Grid agent check the chat answer like any xAI output."""
    nums = AG._known_amounts(gate.audit.records(), [ln["amount"] for ln in (report or {}).get("lines", [])] +
                             list((report or {}).get("totals", {}).values()) +
                             [(report or {}).get("total", 0), (report or {}).get("refunds", 0)])
    return AG.check_ai_text(text, "hold", nums, key="chat", where="chat answer")


def ask(gate, lane: str, question: str, state: dict, report: dict | None = None, by: str = "owner (web)") -> dict:
    """One turn. state: {'step': int} for this lane (kept by the caller). Returns {'answer', 'by_ai', 'usage',
    'step', 'guide', 'warn'}. Never raises on AI trouble; never acts."""
    from .xai_check import redact_description
    g = guide(gate, lane, report)
    n = int(state.get("step", 0))
    q = " ".join(str(question or "").split())[:300]
    terms = gate.engine.p.get("private_terms", [])
    red_q = redact_description(q, "", terms)[:300]
    out = {"guide": g, "by_ai": False, "usage": "No AI call, no cost.", "warn": ""}
    if NEXT_WORDS.match(q) or BACK_WORDS.match(q) or not q:
        n = n + 1 if NEXT_WORDS.match(q) else max(0, n - 1) if BACK_WORDS.match(q) else n
        n = min(n, len(g["steps"]))
        out["answer"] = (f"Step {n + 1} of {len(g['steps'])}: {g['steps'][n]}" if n < len(g["steps"]) else
                         "That was the last step. Well done. Say 'back' to see a step again.")
        out["step"] = n
        gate.audit.write("help_chat_step", action_id="-", lane=lane, step=n, by=by, ai_used=False)
        return out
    out["step"] = n
    kind = route(q, lane)
    if kind != "ok":
        out["answer"] = local_reply(kind, lane)
        gate.audit.write("help_chat_asked", action_id="-", lane=lane, by=by, question_redacted=red_q,
                         ai_used=False, routed=kind, advisory_only=True)
        return out
    step = g["steps"][n] if n < len(g["steps"]) else ""
    ai = getattr(gate, "ai", None)
    res = (ai.advise(context(gate, lane, report, step), red_q, scope=SCOPE[lane])
           if ai is not None and hasattr(ai, "advise") else {"called": False, "skipped": "no_api_key"})
    if res.get("text"):
        out.update(answer=res["text"], by_ai=True)
        flags = check_answer(res["text"], report, gate)
        if flags:
            out["warn"] = ("The BW AG Grid agent checked this answer: " + flags[0]["text"])
    else:
        why = res.get("skipped") or res.get("error") or "no answer"
        out["answer"] = (f"Step {n + 1} of {len(g['steps'])}: {step}" if step else g["steps"][0]) + \
            f" (AI not used: {str(why)[:60]}.)"
    out["usage"] = usage_line(res)
    u = res.get("usage") or {}
    gate.audit.write("help_chat_asked", action_id="-", lane=lane, by=by, question_redacted=red_q,
                     ai_used=out["by_ai"], ai_called=bool(res.get("called")), skipped=res.get("skipped"),
                     usage={k: u.get(k) for k in ("prompt_tokens", "completion_tokens", "cost_in_usd_ticks")},
                     ai_answer_flags=[f["kind"] for f in (check_answer(out["answer"], report, gate)
                                                          if out["by_ai"] else [])], advisory_only=True)
    if out["by_ai"]:
        AG.log_ai_note(gate, out["answer"], [])   # the next scan cross-checks it like any xAI output
    return out
