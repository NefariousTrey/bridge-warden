"""Policy loading with integrity: strict validation (fail closed) and a SHA-256 fingerprint for the audit log."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .guard import BadMoney, CURRENCY, parse_amount

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = {"allowed_currencies", "auto_allow_max", "hard_max", "daily_cap", "max_actions_per_hour"}
KNOWN_KEYS = REQUIRED | {"owner_name", "preferred_name", "call_voice", "call_retry_minutes", "owner_timezone", "duplicate_window_minutes", "quiet_hours", "known_payees",
                         "blocked_payees", "ai_hold_at", "ai_block_at", "private_terms", "xai", "hold_expires_hours",
                         "approval_link_minutes", "mode", "checks", "trusted", "notify", "money_check", "ui"}
XAI_KEYS = {"enabled", "model", "timeout_seconds", "require_zdr", "owner_confirmed_zdr", "on_ai_failure",
            "review_local_blocks", "max_calls_per_minute", "breaker_failures", "breaker_cooldown_seconds"}


class PolicyError(ValueError):
    pass


def resolve_path(path=None) -> Path:
    if path:
        p = Path(path)
        if not p.exists():
            raise PolicyError(f"policy file not found: {p}")  # an explicit path never falls back silently
        return p
    p = ROOT / "policy.json"
    return p if p.exists() else ROOT / "policy.example.json"


def fingerprint(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(p) -> dict:
    """Raises PolicyError listing every problem. Never 'fixes' a policy quietly."""
    errs = []
    if not isinstance(p, dict):
        raise PolicyError("policy must be a JSON object")
    missing = REQUIRED - set(p)
    if missing:
        errs.append(f"missing keys: {', '.join(sorted(missing))}")
    unknown = set(p) - KNOWN_KEYS
    if unknown:
        errs.append(f"unknown keys (typo?): {', '.join(sorted(unknown))}")
    cur = p.get("allowed_currencies")
    if not isinstance(cur, list) or not cur or not all(isinstance(c, str) and CURRENCY.match(c) for c in cur):
        errs.append("allowed_currencies must be a non-empty list of 3-letter upper-case codes like \"USD\"")
    limits = {}
    for k in ("auto_allow_max", "hard_max", "daily_cap"):
        if k in p:
            v = p[k]
            if isinstance(v, int) and not isinstance(v, bool):
                v = str(v)
            try:
                limits[k] = parse_amount(v, "USD")
            except BadMoney as e:
                errs.append(f"{k}: {e} (write money as a string, e.g. \"50.00\")")
    if len(limits) == 3 and not (limits["auto_allow_max"] <= limits["hard_max"]):
        errs.append("auto_allow_max must not be above hard_max")
    for k, lo in (("max_actions_per_hour", 1), ("duplicate_window_minutes", 0), ("hold_expires_hours", 1),
                  ("approval_link_minutes", 1)):
        if k in p and (not isinstance(p[k], int) or isinstance(p[k], bool) or p[k] < lo):
            errs.append(f"{k} must be a whole number >= {lo}")
    if "approval_link_minutes" in p and isinstance(p["approval_link_minutes"], int) and p["approval_link_minutes"] > 240:
        errs.append("approval_link_minutes must be 240 or less (the login link and buttons should not live long)")
    errs += _notify_errors(p.get("notify"))
    errs += _money_check_errors(p.get("money_check"))
    errs += _ui_errors(p.get("ui"))
    if "call_retry_minutes" in p and not valid_call_retry_minutes(p["call_retry_minutes"]):
        errs.append("call_retry_minutes must be a list of up to 3 whole minutes, each 1 to 120 ([] = no retries)")
    if "call_voice" in p and not valid_call_voice(p["call_voice"]):
        errs.append("call_voice must be empty or a Twilio voice name like Google.en-US-Chirp3-HD-Charon, Polly.Joanna or man")
    if "preferred_name" in p and not valid_preferred_name(p["preferred_name"]):
        errs.append("preferred_name must be empty or up to 40 letters, spaces, hyphens or apostrophes")
    q = p.get("quiet_hours", [0, 6])
    if not (isinstance(q, list) and len(q) == 2 and all(isinstance(h, int) and 0 <= h <= 24 for h in q) and q[0] <= q[1]):
        errs.append("quiet_hours must be [start, end] hours, 0-24")
    for k in ("known_payees", "blocked_payees", "private_terms"):
        if k in p and not (isinstance(p[k], list) and all(isinstance(x, str) for x in p[k])):
            errs.append(f"{k} must be a list of strings")
    hold, block = p.get("ai_hold_at", 0.6), p.get("ai_block_at", 0.9)
    if not (_is_num(hold) and _is_num(block) and 0 < hold <= block <= 1):
        errs.append("ai_hold_at and ai_block_at must be numbers with 0 < ai_hold_at <= ai_block_at <= 1")
    try:
        ZoneInfo(p.get("owner_timezone", "UTC"))
    except Exception:
        errs.append("owner_timezone is not a valid time zone name")
    x = p.get("xai")
    if x is not None:
        if not isinstance(x, dict):
            errs.append("xai must be an object")
        else:
            if set(x) - XAI_KEYS:
                errs.append(f"unknown xai keys: {', '.join(sorted(set(x) - XAI_KEYS))}")
            for k in ("enabled", "require_zdr", "owner_confirmed_zdr", "review_local_blocks"):
                if k in x and not isinstance(x[k], bool):
                    errs.append(f"xai.{k} must be true or false")
            if "on_ai_failure" in x and x["on_ai_failure"] not in ("use_local", "hold"):
                errs.append("xai.on_ai_failure must be \"use_local\" or \"hold\"")
            for k in ("timeout_seconds", "max_calls_per_minute", "breaker_failures", "breaker_cooldown_seconds"):
                if k in x and (not _is_num(x[k]) or x[k] <= 0):
                    errs.append(f"xai.{k} must be a positive number")
            if "model" in x and not (isinstance(x["model"], str) and x["model"].replace("-", "").replace(".", "").isalnum()):
                errs.append("xai.model must be a plain model name")
    errs += _control_errors(p)
    if errs:
        raise PolicyError("policy rejected: " + "; ".join(errs))
    return p


PREFERRED_NAME = re.compile(r"[A-Za-z][A-Za-z' -]{0,39}")   # same rule as notify.clean_name / the Worker


def valid_preferred_name(v) -> bool:
    """The name the alert call greets you by ("Hi Trey, this is Bridge Warden."). "" = no name (plain greeting)."""
    return isinstance(v, str) and (v == "" or (bool(PREFERRED_NAME.fullmatch(v)) and "  " not in v
                                               and v == v.strip(" ")))


UI_KEYS = {"colorblind_mode", "theme"}
THEMES = ("light", "dark")   # display only (Trey, 2026-10-26). Light is the default.


def _ui_errors(u) -> list:
    """Display-only preferences. They never change what money can move."""
    if u is None:
        return []
    if not isinstance(u, dict):
        return ["ui must be an object like {\"colorblind_mode\": false}"]
    errs = []
    if set(u) - UI_KEYS:
        errs.append("ui may only have colorblind_mode and theme")
    if "colorblind_mode" in u and not isinstance(u["colorblind_mode"], bool):
        errs.append("ui.colorblind_mode must be true or false")
    if "theme" in u and u["theme"] not in THEMES:
        errs.append("ui.theme must be \"light\" or \"dark\"")
    return errs


def _money_check_errors(m) -> list:
    """Read-only "Check my money" settings (v4)."""
    if m is None:
        return []
    import re as _re
    if not isinstance(m, dict) or set(m) - {"subscription_ids", "due_soon_days", "lookback_days", "ai_summary"}:
        return ["money_check may only have subscription_ids, due_soon_days, lookback_days, ai_summary"]
    errs = []
    ids = m.get("subscription_ids", [])
    if not (isinstance(ids, list) and len(ids) <= 25 and all(isinstance(i, str) and _re.fullmatch(r"I-[A-Z0-9]{6,40}", i) for i in ids)):
        errs.append('money_check.subscription_ids must be up to 25 PayPal ids like "I-ABC123DEF456"')
    for k, lo, hi in (("due_soon_days", 1, 60), ("lookback_days", 1, 90)):
        v = m.get(k, lo)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            errs.append(f"money_check.{k} must be a whole number from {lo} to {hi}")
    if not isinstance(m.get("ai_summary", True), bool):
        errs.append("money_check.ai_summary must be true or false")
    return errs


def _notify_errors(n) -> list:
    """Optional phone push to YOUR OWN ntfy-style server. Off by default. Only a loopback URL (a server on this
    computer, or a tunnel you run to it) is allowed, so no outside service is ever contacted."""
    if n is None:
        return []
    if isinstance(n, dict) and "call_on_fraud" in n:
        c = n["call_on_fraud"]
        ok = (isinstance(c, dict) and not set(c) - {"enabled", "provider", "experimental"}
              and isinstance(c.get("enabled", False), bool) and isinstance(c.get("experimental", False), bool)
              and c.get("provider", "dry_run") in ("dry_run", "twilio"))
        if not ok:
            return ['notify.call_on_fraud must be {"enabled": true/false, "provider": "dry_run" or "twilio", '
                    '"experimental": true/false}.']
        if c.get("provider") == "twilio" and not c.get("experimental"):
            return ['notify.call_on_fraud provider "twilio" is EXPERIMENTAL (not yet tested on a real phone). '
                    'Set "experimental": true to use your own Twilio account, or use "dry_run".']
        n = {k: v for k, v in n.items() if k != "call_on_fraud"}
    if not isinstance(n, dict) or set(n) - {"webhook_enabled", "webhook_url"}:
        return ['notify must be an object with "webhook_enabled" and "webhook_url"']
    errs = []
    if "webhook_enabled" in n and not isinstance(n["webhook_enabled"], bool):
        errs.append("notify.webhook_enabled must be true or false")
    url = n.get("webhook_url", "")
    if not isinstance(url, str):
        return errs + ["notify.webhook_url must be text"]
    if url:
        from urllib.parse import urlsplit
        u = urlsplit(url)
        if (u.scheme not in ("http", "https") or (u.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1")
                or u.username or u.password or u.query or u.fragment or len(url) > 200):
            errs.append("notify.webhook_url must be a plain http(s) URL on this computer (127.0.0.1 or localhost)")
    elif n.get("webhook_enabled"):
        errs.append("notify.webhook_enabled is true but notify.webhook_url is empty")
    return errs


def _control_errors(p) -> list:
    """User controls: master mode, per-check switches, trusted payees (see controls.py)."""
    from .controls import CHECKS, MODES
    from .textnorm import is_plain_ascii, lookalike_of
    errs = []
    if "mode" in p and p["mode"] not in MODES:
        errs.append(f"mode must be one of: {', '.join(MODES)}")
    c = p.get("checks", {})
    if not isinstance(c, dict):
        errs.append("checks must be an object of check name -> true/false")
    else:
        bad = set(c) - set(CHECKS)
        if bad:
            errs.append(f"unknown checks (typo?): {', '.join(sorted(bad))}")
        if any(not isinstance(v, bool) for v in c.values()):
            errs.append("each check must be true or false")
    t = p.get("trusted", {})
    entries = []
    if not isinstance(t, dict) or set(t) - {"payees", "categories"}:
        errs.append('trusted must be an object with "payees" and/or "categories"')
        t = {}
    pay = t.get("payees", [])
    if not (isinstance(pay, list) and all(isinstance(x, str) for x in pay)):
        errs.append("trusted.payees must be a list of emails")
    else:
        entries += pay
    cats = t.get("categories", {})
    if not isinstance(cats, dict):
        errs.append("trusted.categories must be an object of name -> list of emails")
    else:
        for name, lst in cats.items():
            if not (isinstance(name, str) and 0 < len(name) <= 40 and is_plain_ascii(name) and name.isprintable()):
                errs.append("trusted category names must be short plain text")
            if not (isinstance(lst, list) and all(isinstance(x, str) for x in lst)):
                errs.append(f"trusted.categories.{name} must be a list of emails")
            else:
                entries += lst
    blocked = {x.strip().lower() for x in p.get("blocked_payees", []) if isinstance(x, str)}
    others = {x.strip().lower() for x in p.get("known_payees", []) if isinstance(x, str)} | blocked
    seen = {}
    for e in entries:
        low = e.strip().lower()
        if not (is_plain_ascii(low) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", low)):
            errs.append(f"trusted payee {e!r} must be a plain email address")  # no lookalike letters, ever
            continue
        if low in blocked:
            errs.append(f"{low} is both trusted and blocked; pick one")
        look = lookalike_of(low, (others | set(seen)) - {low})
        if look:
            errs.append(f"trusted payee {low} looks like {look[0]}; refusing a lookalike")
        seen[low] = True
    return errs


def load(path=None) -> tuple:
    """Returns (policy, sha256, path). Raises PolicyError on a missing, malformed or invalid file."""
    p = resolve_path(path)
    raw = p.read_bytes()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise PolicyError(f"policy file is not valid JSON: {e.msg if hasattr(e, 'msg') else e}") from None
    return validate(data), hashlib.sha256(raw).hexdigest(), str(p)


def valid_call_retry_minutes(v) -> bool:
    """MISSEDCALL: minutes between call retries after a missed alert call. Same rule as alerts.valid_retry_minutes."""
    return (isinstance(v, list) and len(v) <= 3
            and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 120 for x in v))


def valid_call_voice(v) -> bool:
    """VOICEPICK: the owner's call voice. "" = default (Charon). Same allow-list as notify.VOICE_OK / the Worker."""
    from .notify import VOICE_OK
    return isinstance(v, str) and (v == "" or bool(VOICE_OK.match(v)))
