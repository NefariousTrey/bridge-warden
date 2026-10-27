"""The risk rules. Each rule looks at one proposed action (plus recent history) and adds findings.

Verdict = the worst severity found:
  allow -> runs right away
  hold  -> waits for the owner's yes or no
  block -> never runs (the owner can change the policy, but cannot click past a block)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai import ScamTextModel
from .controls import RULE_TO_CHECK, is_on, mode, tier, trusted_map
from .guard import BadMoney, CURRENCY, input_problems, parse_amount
from .models import ACTIONS, ALLOW, BLOCK, HOLD, Finding, ProposedAction, Verdict, worst
from .policy import load as _load_policy
from .textnorm import ascii_view, control_chars, hidden_chars, is_plain_ascii, lookalike_of, normalize, variants

ROOT = Path(__file__).resolve().parent.parent

# Fast, explainable patterns. The AI model catches softer wording these miss.
SCAM_PATTERNS = [
    (re.compile(r"gift\s*cards?|prepaid\s+card", re.I), "asks for gift cards, a classic scam payment method"),
    (re.compile(r"\b(bitcoin|crypto|usdt|wallet\s+address)\b", re.I), "mentions crypto, which scammers use because it can't be reversed"),
    (re.compile(r"\b(wire\s+transfer|western\s+union|moneygram)\b", re.I), "asks for a wire-style transfer"),
    (re.compile(r"\b(urgent(ly)?|immediately|act\s+now|final\s+(notice|warning)|right\s+away)\b", re.I), "uses pressure words like 'urgent'"),
    (re.compile(r"\b(lottery|prize|inheritance|grant\s+release|unlock\s+fee|advance\s+fee)\b", re.I), "matches a prize, inheritance or fee scam"),
    (re.compile(r"\b(keep\s+this\s+between\s+us|off\s+the\s+books|don'?t\s+tell)\b", re.I), "asks for secrecy"),
    (re.compile(r"\b(new\s+bank\s+details|change\s+of\s+bank|new\s+account\s+for\s+payment)\b", re.I), "says the payment details changed, a common invoice scam"),
]
INJECTION = re.compile(
    r"(ignore\s+(all\s+)?previous|disregard\s+(your\s+)?(rules|instructions)|you\s+are\s+now|system\s+prompt|"
    r"without\s+asking|bypass\s+(the\s+)?(checker|owner|approval)|skip\s+(the\s+)?approval)", re.I)
SECRET = re.compile(r"(api[_-]?key|password|passwd|client[_-]?secret|access[_-]?token|-----BEGIN [A-Z ]*PRIVATE KEY|\b\d{13,19}\b)", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_policy(path=None) -> dict:
    """Load and validate the policy. Raises PolicyError (fail closed) if it is missing, malformed or invalid."""
    return _load_policy(path)[0]


def _dec(x) -> Decimal:
    return Decimal(str(x))


class RiskEngine:
    def __init__(self, policy: dict, model: ScamTextModel | None = None):
        self.p = policy
        self.model = model or ScamTextModel()

    def _apply_controls(self, f: list, payee: str, trusted: dict) -> list:
        """The owner's switches. A trusted payee skips only SOFT checks; hard blocks need the owner to switch
        that check off themselves (with the typed phrase). Structural guards (malformed input, ids, amounts,
        currency) belong to no check and are never skipped. Skips stay visible as findings in the log."""
        m = mode(self.p)
        label = trusted.get(payee) if payee and is_plain_ascii(payee) else None
        out = []
        for x in f:
            check = RULE_TO_CHECK.get(x.rule)
            why = None
            if x.severity != ALLOW and check:
                if m == "off":
                    why = "Bridge Warden is switched off by you"
                elif not is_on(self.p, check):
                    why = f"you switched off the '{check}' check"
                elif label and tier(check) == "soft":
                    why = f"{payee} is {label}"
            out.append(Finding(f"skipped:{x.rule}", ALLOW, f"Skipped ({why}): {x.reason}", 0) if why else x)
        if m == "off":
            out.append(Finding("master_off", ALLOW, "Bridge Warden checks are OFF (your choice).", 0))
        if m == "paused":
            out.append(Finding("paused", BLOCK, "Bridge Warden is paused by you, so no money moves until you resume.", 100))
        return out

    def check(self, a: ProposedAction, history: list, now: datetime | None = None) -> Verdict:
        """history: list of dicts of earlier actions that were actually executed (from the audit log)."""
        now = now or datetime.now(timezone.utc)
        f: list[Finding] = []
        add = lambda rule, sev, reason, pts=0: f.append(Finding(rule, sev, reason, pts))

        # 1. Shape of the request (types, lengths, ids). Nothing odd gets near PayPal.
        if a.action not in ACTIONS:
            add("unknown_action", BLOCK, f"'{a.action}' is not an action this checker allows.", 100)
        problems = input_problems(a)
        for why in problems:
            add("bad_input", BLOCK, f"The request is malformed: {why}.", 100)
        if problems:  # don't run text rules on malformed input
            a = ProposedAction(a.action if isinstance(a.action, str) else "?", "0", "USD", "", "",
                               action_id=a.action_id if isinstance(a.action_id, str) else "act-invalid")

        # 2. Currency (allowlist) and amount (strict string, no floats, right number of decimals)
        cur = a.currency if isinstance(a.currency, str) else ""
        if not CURRENCY.match(cur) or cur not in self.p["allowed_currencies"]:
            add("currency", BLOCK, f"Currency {cur or '(none)'} isn't one you allow ({', '.join(self.p['allowed_currencies'])}).", 60)
        try:
            amt = parse_amount(a.amount, cur if CURRENCY.match(cur) else "USD")
        except BadMoney as e:
            add("bad_amount", BLOCK, f"The amount is not a valid money amount: {e}.", 100)
            amt = Decimal("0")

        # 3. Amount limits
        if amt > _dec(self.p["hard_max"]):
            add("hard_max", BLOCK, f"${amt} is over your hard limit of ${self.p['hard_max']}.", 80)
        elif amt > _dec(self.p["auto_allow_max"]):
            add("over_auto_limit", HOLD, f"${amt} is over ${self.p['auto_allow_max']}, the most the agent may spend without asking.", 30)

        # 4. Payee
        payee = (a.payee or "").strip().lower()
        known = {x.lower() for x in self.p.get("known_payees", [])}
        blocked = {x.lower() for x in self.p.get("blocked_payees", [])}
        trusted = trusted_map(self.p)
        named = known | blocked | set(trusted)
        look = lookalike_of(payee, named)
        if look:
            twin, kind = look
            if kind == "address":
                add("lookalike_payee", BLOCK, f"Payee '{ascii_view(a.payee)}' is made to look like '{twin}' but is a "
                                              f"different address.", 100)
            else:
                add("lookalike_payee", BLOCK, f"Payee '{ascii_view(a.payee)}' uses a web address made to look like "
                                              f"the one in '{twin}' (letters and numbers swapped).", 100)
        elif payee and not is_plain_ascii(payee):
            add("non_ascii_payee", HOLD, f"Payee has unusual characters: '{ascii_view(a.payee)}'.", 25)
        if payee in blocked:
            add("blocked_payee", BLOCK, f"{payee} is on your blocked list.", 100)
        elif a.action == "payout" and not EMAIL.match(payee):
            add("bad_payee", BLOCK, f"A payout needs a valid email for the payee; got '{a.payee}'.", 60)
        elif a.action != "refund" and payee and payee not in known:
            add("new_payee", HOLD, f"{payee} is new. The agent has never paid them before.", 25)

        # 5. History-based: duplicates, velocity, daily cap
        recent = []
        for h in history:
            try:
                t = datetime.fromisoformat(h["at"])
            except (KeyError, ValueError):
                continue
            recent.append((t, h))
        win = timedelta(minutes=int(self.p.get("duplicate_window_minutes", 30)))
        for t, h in recent:
            if (now - t <= win and h.get("action") == a.action and (h.get("payee") or "").lower() == payee
                    and _dec(h.get("amount", "0")) == amt):
                add("duplicate", HOLD, f"Same {a.action} of ${amt} to {payee or 'this payee'} already went through "
                                       f"{int((now - t).total_seconds() // 60)} min ago. Is this a double charge?", 40)
                break
        last_hour = [h for t, h in recent if now - t <= timedelta(hours=1)]
        if len(last_hour) >= int(self.p["max_actions_per_hour"]):
            add("velocity", HOLD, f"The agent already moved money {len(last_hour)} times in the last hour.", 25)
        spent = sum((_dec(h.get("amount", "0")) for t, h in recent
                     if now - t <= timedelta(hours=24) and h.get("action") in ("payout", "create_order")), Decimal("0"))
        if a.action in ("payout", "create_order") and spent + amt > _dec(self.p["daily_cap"]):
            add("daily_cap", BLOCK, f"This would bring today's total to ${spent + amt}, over your daily cap of ${self.p['daily_cap']}.", 60)

        # 6. Refund sanity
        if a.action == "refund":
            if not a.capture_id:
                add("refund_no_capture", BLOCK, "A refund must name the payment (capture) it refunds.", 80)
            else:
                orig = next((h for _, h in recent if h.get("capture_id") == a.capture_id and h.get("action") == "create_order"), None)
                if orig is None:
                    add("refund_unknown_capture", HOLD, f"Capture {a.capture_id} isn't a payment this agent made.", 30)
                elif amt > _dec(orig.get("amount", "0")):
                    add("refund_too_big", BLOCK, f"Refund ${amt} is more than the original ${orig.get('amount')}.", 80)

        # 7. Odd hours (owner's local time)
        lo, hi = self.p.get("quiet_hours", [0, 6])
        local = now.astimezone(ZoneInfo(self.p.get("owner_timezone", "UTC")))
        if lo <= local.hour < hi:   # (12-hour clock built by hand: Windows has no %-I)
            add("odd_hours", HOLD, f"It's {local.hour % 12 or 12}:{local:%M %p} for you, inside your quiet hours.", 15)

        # 8. The agent's own words: injection, secrets, scam patterns, AI score
        raw = a.description or ""
        texts = variants(raw)            # normalized text + de-disguised skeleton (catches "g1ft c4rd", "gіft")
        if control_chars(raw):
            add("control_characters", BLOCK, "The description contains terminal control characters "
                                             f"({', '.join(control_chars(raw)[:3])}).", 100)
        hid = hidden_chars(raw)
        if hid:
            add("hidden_characters", HOLD, f"The description contains invisible characters ({', '.join(hid[:3])}) "
                                           "that can hide words from filters.", 25)
        if any(INJECTION.search(t) for t in texts):
            add("prompt_injection", BLOCK, "The description tries to talk past the safety rules (prompt injection).", 100)
        if SECRET.search(texts[0]):
            add("secret_in_text", BLOCK, "The description looks like it contains a password, key or card number.", 100)
        hits = [why for rx, why in SCAM_PATTERNS if any(rx.search(t) for t in texts)]
        for why in hits:
            add("scam_pattern", HOLD, f"The description {why}.", 20)
        if len(hits) >= 2:
            add("scam_pattern_stack", BLOCK, "Several scam signs show up together.", 40)
        prob = max(self.model.scam_probability(t) for t in texts)
        if prob >= float(self.p.get("ai_block_at", 0.9)):
            add("ai_scam_model", BLOCK, f"The AI scam model rates this description {prob:.0%} likely to be a scam.", 50)
        elif prob >= float(self.p.get("ai_hold_at", 0.6)):
            add("ai_scam_model", HOLD, f"The AI scam model rates this description {prob:.0%} likely to be a scam.", 25)
        else:
            add("ai_scam_model", ALLOW, f"AI scam model: {prob:.0%}.", 0)

        f = self._apply_controls(f, payee, trusted)
        verdict = ALLOW
        for x in f:
            verdict = worst(verdict, x.severity)
        score = min(100, sum(x.points for x in f))
        return Verdict(a.action_id, verdict, score, f, prob)
