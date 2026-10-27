"""Input validation and secret scrubbing. Pure functions, no network.

Money rules: amounts are strings only (never floats), plain ASCII digits, a dot, and no more
decimal places than the currency allows. No exponents, signs, spaces, NaN or Infinity.
"""
from __future__ import annotations

import os
import re
from decimal import Decimal

from .textnorm import control_chars

# PayPal: these currencies have no minor unit. Everything else in the allowlist uses 2 decimals.
ZERO_DECIMAL = {"HUF", "JPY", "TWD"}
MAX_AMOUNT_DIGITS = 9            # up to 999,999,999 before the dot; policy limits are far lower anyway
MAX_DESCRIPTION = 1000
MAX_PAYEE = 254                  # longest valid email address
MAX_AGENT_ID = 64
CAPTURE_ID = re.compile(r"^[A-Za-z0-9-]{4,64}$")      # PayPal ids are short alphanumerics; no / . % ? #
ACTION_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


class BadMoney(ValueError):
    pass


def currency_places(currency: str) -> int:
    return 0 if currency in ZERO_DECIMAL else 2


def parse_amount(amount, currency: str = "USD") -> Decimal:
    """Strict money parser. Returns a positive Decimal or raises BadMoney with a plain reason."""
    if isinstance(amount, bool) or not isinstance(amount, str):
        raise BadMoney(f"amount must be a text string like \"12.50\", not {type(amount).__name__}")
    places = currency_places(currency)
    frac = r"(\.\d{1,%d})?" % places if places else ""
    if not re.fullmatch(r"(0|[1-9][0-9]{0,%d})%s" % (MAX_AMOUNT_DIGITS - 1, frac), amount):
        raise BadMoney(f"'{amount[:40]}' is not a plain amount with at most {places} decimal places")
    d = Decimal(amount)
    if d <= 0:
        raise BadMoney("amount must be more than zero")
    return d


def canonical_amount(amount, currency: str = "USD") -> str:
    d = parse_amount(amount, currency)
    places = currency_places(currency)
    return str(d.quantize(Decimal(1).scaleb(-places))) if places else str(d)


def input_problems(a) -> list:
    """Shape checks on a proposed action. Returns plain-English problems (empty = fine)."""
    out = []
    for name, limit in (("payee", MAX_PAYEE), ("description", MAX_DESCRIPTION), ("agent_id", MAX_AGENT_ID),
                        ("currency", 3), ("action", 32)):
        v = getattr(a, name)
        if not isinstance(v, str):
            out.append(f"{name} must be text")
        elif len(v) > limit:
            out.append(f"{name} is too long ({len(v)} characters, limit {limit})")
    if a.capture_id is not None and (not isinstance(a.capture_id, str) or not CAPTURE_ID.match(a.capture_id)):
        out.append("capture_id has characters a PayPal id never has")
    if not isinstance(a.action_id, str) or not ACTION_ID.match(a.action_id):
        out.append("action_id has unexpected characters")
    for name in ("payee", "capture_id", "currency", "agent_id"):
        v = getattr(a, name)
        if isinstance(v, str) and control_chars(v):
            out.append(f"{name} contains control characters")
    return out


# ---- secrets ---------------------------------------------------------------------------
SECRET_ENV = ("PAYPAL_SANDBOX_SECRET", "XAI_API_KEY", "CHECKER_LLM_KEY", "CHECKER_AUDIT_KEY", "TWILIO_AUTH_TOKEN", "CHANNEL3_API_KEY",
              "BW_JUDGE_KEY")
_TOKEN_PATTERNS = [
    re.compile(r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(\"?access_token\"?\s*[:=]\s*\"?)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bxai-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bA21AA[A-Za-z0-9_-]{20,}\b"),   # PayPal access token shape
]


def scrub(text, extra=()) -> str:
    """Remove secret values (from env) and token-shaped strings from any text before it is logged or shown."""
    s = str(text)
    for v in [os.environ.get(k, "") for k in SECRET_ENV] + list(extra):
        if v and len(v) >= 6:
            s = s.replace(v, "[redacted]")
    for rx in _TOKEN_PATTERNS:
        s = rx.sub(lambda m: (m.group(1) + " [redacted]") if m.lastindex else "[redacted]", s)
    return s


def scrub_obj(obj, extra=()):
    """scrub() applied to every string inside a JSON-like structure."""
    if isinstance(obj, str):
        return scrub(obj, extra)
    if isinstance(obj, dict):
        return {k: scrub_obj(v, extra) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v, extra) for v in obj]
    return obj
