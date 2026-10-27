"""User controls: per-check on/off switches, a trusted-payee list, and one master switch.

Everything here is the owner's choice and everything is reversible:
- Turning anything ON (or pausing) is always allowed with no prompt, because it only makes things safer.
- Turning a check OFF shows a plain-words warning of what is lost, then needs a typed confirmation:
  "yes" for a soft check, and the exact phrase "expose me to everything" for a hard (scam) block or for
  turning the whole checker off while any hard block is on. A click or "yes" is not enough for those.
- Every change saves the previous policy file under policy_history/, writes the new file atomically,
  and records old/new SHA-256 plus the warning shown and the confirmation in the audit log.
- `undo` restores the version before the last change (through the same warnings).
- Changes need a real terminal, so an agent piping input can't switch checks off. Pausing works from anywhere.

Some guards are not checks and can't be switched off, because they stop the tool doing something other
than what was asked: malformed input, unknown actions, bad ids or amounts, the currency list, the sandbox
and host pinning, the approval fingerprint, the audit log and policy integrity, and the xAI privacy
(redaction / leak) check. To stop sending anything to xAI, turn xAI off ("xai": {"enabled": false}).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .policy import PolicyError, fingerprint, valid_call_retry_minutes, valid_call_voice, valid_preferred_name, validate

HARD_PHRASE = "expose me to everything"
MODES = ("on", "paused", "off")

# name: (tier, rule ids it covers, what it protects you from, what you lose with it off)
CHECKS = {
    # soft checks: they only ever HOLD for your yes
    "new_payee": ("soft", ["new_payee"], "Asks you before the agent pays someone it has never paid.",
                  "The agent can pay any new person or shop without asking you (up to your limits)."),
    "velocity": ("soft", ["velocity"], "Asks you when the agent makes many payments in an hour.",
                 "A runaway or looping agent can make many payments in a row without asking."),
    "over_auto_limit": ("soft", ["over_auto_limit"], "Asks you before payments over your auto-allow amount.",
                        "Any payment up to your hard limit goes through without asking."),
    "quiet_hours": ("soft", ["odd_hours"], "Asks you before payments during your quiet hours.",
                    "Payments at night go through while you're asleep."),
    "hidden_characters": ("soft", ["hidden_characters", "non_ascii_payee"],
                          "Asks you when text or a payee contains invisible or unusual characters.",
                          "Text with hidden characters or odd letters in a payee goes through unseen."),
    "unknown_refund": ("soft", ["refund_unknown_capture"], "Asks you before refunding a payment this agent didn't make.",
                       "The agent can refund other payments on your account without asking."),
    "price_sanity": ("soft", ["price_too_low"],
                     "Asks you when a price is far below what stores ask (a fake-seller trick). Needs your own "
                     "Channel3 key; without it this check does nothing.",
                     "A too-good-to-be-true price from a fake seller goes through without a question."),
    # hard blocks: they stop the payment outright
    "hard_max": ("hard", ["hard_max"], "Blocks any single payment over your hard limit.",
                 "One payment can be any size your PayPal balance allows."),
    "daily_cap": ("hard", ["daily_cap"], "Blocks spending over your daily cap.",
                  "There is no limit on how much the agent spends in a day."),
    "duplicate": ("hard", ["duplicate"], "Catches the same payment sent twice (double charges).",
                  "Double payments go through without a question."),
    "blocked_payee": ("hard", ["blocked_payee"], "Blocks everyone on your blocked list.",
                      "The agent can pay people you blocked."),
    "lookalike_payee": ("hard", ["lookalike_payee"], "Blocks payees made to look like someone you know.",
                        "Money can go to a fake address that looks exactly like a real payee."),
    "scam_text": ("hard", ["scam_pattern", "scam_pattern_stack"],
                  "Catches gift-card, crypto, wire, prize and secrecy scams.",
                  "Classic scams (gift cards, crypto, 'keep this between us') get paid like normal bills."),
    "ai_scam_model": ("hard", ["ai_scam_model"], "The scam model holds or blocks scam-like wording.",
                      "Scams worded in new ways are no longer caught by the model."),
    "prompt_injection": ("hard", ["prompt_injection"], "Blocks text that tries to talk past the rules.",
                         "Someone who tricks your agent with 'ignore previous instructions' can get paid."),
    "secret_in_text": ("hard", ["secret_in_text"], "Blocks payments whose text contains passwords, keys or card numbers.",
                       "Your passwords or card numbers can be sent to a stranger inside a payment note."),
    "control_characters": ("hard", ["control_characters"], "Blocks text that can rewrite what your screen shows.",
                           "A payment can disguise itself on your screen."),
    "refund_too_big": ("hard", ["refund_too_big"], "Blocks refunds bigger than the original payment.",
                       "The agent can refund more than was paid."),
}
RULE_TO_CHECK = {r: name for name, (_, rules, _, _) in CHECKS.items() for r in rules}
MASTER_OFF_LOSS = ("ALL checks stop: limits, daily cap, scam and prompt-injection blocks, new-payee and "
                   "double-charge questions. Whatever your agent proposes is paid at once (only malformed requests "
                   "are still refused). The xAI review is skipped too.")
PAUSE_TEXT = "Paused: no money moves until you resume. Held items wait; new requests are refused."


def tier(name: str) -> str:
    return CHECKS[name][0]


def is_on(policy: dict, name: str) -> bool:
    return policy.get("checks", {}).get(name, True)


def mode(policy: dict) -> str:
    return policy.get("mode", "on")


def trusted_map(policy: dict) -> dict:
    """payee (lower-case) -> label ('trusted' or 'trusted: <category>')."""
    t = policy.get("trusted", {}) or {}
    out = {p.strip().lower(): "trusted" for p in t.get("payees", [])}
    for cat, payees in (t.get("categories", {}) or {}).items():
        for p in payees:
            out.setdefault(p.strip().lower(), f"trusted: {cat}")
    return out


def snapshot(policy: dict) -> dict:
    """Small summary of the user controls, stored with each policy_loaded record so changes can be diffed."""
    return {"mode": mode(policy),
            "checks_off": sorted(n for n in CHECKS if not is_on(policy, n)),
            "trusted": sorted(trusted_map(policy).items())}


def diff(old: dict, new: dict) -> list:
    """List of changes, each {'what', 'from', 'to', 'loosens', 'hard'}."""
    out = []
    if mode(old) != mode(new):
        # Turning on, pausing, or resuming from a pause (back to your own settings) never needs a confirmation.
        out.append({"what": "master", "from": mode(old), "to": mode(new), "loosens": mode(new) == "off",
                    "hard": mode(new) == "off" and any(is_on(new, n) for n in CHECKS if tier(n) == "hard")})
    for n in CHECKS:
        if is_on(old, n) != is_on(new, n):
            out.append({"what": f"check:{n}", "from": "on" if is_on(old, n) else "off",
                        "to": "on" if is_on(new, n) else "off", "loosens": not is_on(new, n), "hard": tier(n) == "hard"})
    to, tn = trusted_map(old), trusted_map(new)
    for p in sorted(set(tn) - set(to)):
        out.append({"what": f"trusted+:{p}", "from": None, "to": tn[p], "loosens": True, "hard": False})
    for p in sorted(set(to) - set(tn)):
        out.append({"what": f"trusted-:{p}", "from": to[p], "to": None, "loosens": False, "hard": False})
    for p in sorted(set(to) & set(tn)):
        if to[p] != tn[p]:
            out.append({"what": f"trusted~:{p}", "from": to[p], "to": tn[p], "loosens": False, "hard": False})
    return out


def warning_text(changes: list) -> str:
    lines = []
    for c in changes:
        if not c["loosens"]:
            continue
        w = c["what"]
        if w == "master":
            lines.append("TURNING BRIDGE WARDEN OFF.\n  With it ON: every payment is checked and risky ones wait for you."
                         f"\n  With it OFF: {MASTER_OFF_LOSS}")
        elif w.startswith("check:"):
            n = w[6:]
            t, _, on, off = CHECKS[n]
            head = "HARD SCAM BLOCK" if t == "hard" else "check"
            lines.append(f"Turning OFF {head} '{n}'.\n  With it ON: {on}\n  With it OFF: {off}")
        elif w.startswith("trusted+:"):
            lines.append(f"Trusting {w[9:]} ({c['to']}).\n  Trusted payees skip the soft questions (new payee, "
                         "amount over auto-allow, many payments, quiet hours, odd characters).\n  They still face every "
                         "hard block: limits, daily cap, double charges, scam text, prompt injection, secrets.")
    return "\n\n".join(lines)


def needed_confirmation(changes: list):
    """None (no prompt), 'yes', or the hard phrase."""
    loosening = [c for c in changes if c["loosens"]]
    if not loosening:
        return None
    return HARD_PHRASE if any(c["hard"] for c in loosening) else "yes"


def confirmed(answer: str, need: str) -> bool:
    return (answer or "").strip().lower() == need


# ---------------------------------------------------------------- applying changes
def history_dir(policy_path) -> Path:
    return Path(policy_path).resolve().parent / "policy_history"


def _save_history(policy_path: Path) -> Path:
    d = history_dir(policy_path)
    d.mkdir(mode=0o700, exist_ok=True)
    n = len(list(d.glob("*.json"))) + 1
    while True:
        dest = d / f"{n:05d}-{fingerprint(policy_path)[:12]}.json"
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
    with os.fdopen(fd, "wb") as fh:
        fh.write(Path(policy_path).read_bytes())
    return dest


def _atomic_write(path: Path, text: str):
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "x") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # readers see the old or the new file, never half of one


def apply(policy_path, new_policy: dict, audit, ask=input, out=print, is_tty=None, by="owner", note="", raw_text=None):
    """Validate, warn, confirm, save history, write, log. Returns a result dict; never raises on a 'no'."""
    policy_path = Path(policy_path)
    old_raw = policy_path.read_bytes()
    old = validate(json.loads(old_raw))
    validate(new_policy)  # fail closed: an invalid result is never written
    changes = diff(old, new_policy)
    if not changes:
        return {"status": "no_change"}
    need = needed_confirmation(changes)
    warn = warning_text(changes)
    if need:
        tty = is_tty if is_tty is not None else (os.isatty(0) and os.isatty(1))
        if not tty:
            audit.write("control_refused", action_id="-", changes=changes, why="no_terminal")
            return {"status": "refused_no_terminal"}
        out("\n" + warn + "\n")
        prompt = (f'To confirm, type exactly: {HARD_PHRASE}\n> ' if need == HARD_PHRASE else 'Type "yes" to confirm: ')
        answer = ask(prompt)
        if not confirmed(answer, need):
            audit.write("control_refused", action_id="-", changes=changes, why="not_confirmed",
                        confirmation_required=need)
            return {"status": "not_confirmed", "needed": need}
    saved = _save_history(policy_path)
    old_sha = fingerprint(policy_path)
    _atomic_write(policy_path, raw_text if raw_text is not None else json.dumps(new_policy, indent=2) + "\n")
    new_sha = fingerprint(policy_path)
    audit.write("control_changed", action_id="-", by=by, changes=changes, old_sha256=old_sha, new_sha256=new_sha,
                warning_shown=warn or None, confirmation=need and ("phrase" if need == HARD_PHRASE else "yes"),
                previous_version=saved.name, note=note,
                at_local=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {"status": "changed", "changes": changes, "old_sha256": old_sha, "new_sha256": new_sha,
            "previous_version": saved.name}


def load_file(path) -> dict:
    try:
        return validate(json.loads(Path(path).read_bytes()))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise PolicyError(f"policy file is not valid JSON: {e}") from None


def set_check(policy_path, name, on: bool, audit, **kw):
    if name not in CHECKS:
        raise PolicyError(f"unknown check '{name}'. Checks: {', '.join(CHECKS)}")
    p = load_file(policy_path)
    checks = dict(p.get("checks", {}))
    checks[name] = bool(on)
    return apply(policy_path, {**p, "checks": checks}, audit, **kw)


def ui_prefs(policy: dict) -> dict:
    """Display-only preferences (default: colour-blind mode off, Light theme)."""
    u = policy.get("ui") if isinstance(policy, dict) else None
    u = u if isinstance(u, dict) else {}
    return {"colorblind_mode": u.get("colorblind_mode") is True,
            "theme": "dark" if u.get("theme") == "dark" else "light"}


def set_ui_pref(policy_path, key: str, value, audit, by="owner"):
    """Change one display-only preference (e.g. colour-blind mode). It cannot loosen any safety check, so it needs
    no confirmation, but it is still validated, backed up to policy_history/, written atomically and logged."""
    policy_path = Path(policy_path)
    old = validate(json.loads(policy_path.read_bytes()))
    if ui_prefs(old).get(key) == value:
        return {"status": "no_change"}
    new = {**old, "ui": {**(old.get("ui") or {}), key: value}}
    validate(new)  # fail closed: unknown key or wrong type is never written
    saved = _save_history(policy_path)
    old_sha = fingerprint(policy_path)
    _atomic_write(policy_path, json.dumps(new, indent=2) + "\n")
    new_sha = fingerprint(policy_path)
    audit.write("ui_pref_changed", action_id="-", by=by, key=key, value=value, old_sha256=old_sha,
                new_sha256=new_sha, previous_version=saved.name)
    return {"status": "changed", "key": key, "value": value, "previous_version": saved.name}


def set_call_voice(policy_path, voice: str, audit, by="owner"):
    """VOICEPICK: save the owner's call voice (policy.json call_voice). Only allow-listed Twilio voice names; it
    cannot loosen any safety check. Backed up to policy_history/, written atomically, logged (the voice name is
    not private, so it is logged)."""
    voice = str(voice or "").strip()
    if not valid_call_voice(voice):
        raise PolicyError("call_voice must be one of the allowed Twilio voice names")
    policy_path = Path(policy_path)
    old = validate(json.loads(policy_path.read_bytes()))
    if (old.get("call_voice") or "") == voice:
        return {"status": "no_change"}
    new = {**old, "call_voice": voice}
    validate(new)
    saved = _save_history(policy_path)
    old_sha = fingerprint(policy_path)
    _atomic_write(policy_path, json.dumps(new, indent=2) + "\n")
    new_sha = fingerprint(policy_path)
    audit.write("call_voice_changed", action_id="-", by=by, voice=voice or "default", old_sha256=old_sha,
                new_sha256=new_sha, previous_version=saved.name)
    return {"status": "changed", "call_voice": voice, "previous_version": saved.name}


def parse_retry_minutes(text) -> list:
    """'15, 15' -> [15, 15]; 'off' / '' -> []. Raises PolicyError on anything else."""
    t = str(text or "").strip().lower()
    if t in ("", "off", "none", "0"):
        return []
    try:
        mins = [int(x) for x in t.replace(" ", "").split(",") if x != ""]
    except ValueError:
        raise PolicyError("Retry times must be whole minutes, like 15, 15") from None
    if not valid_call_retry_minutes(mins):
        raise PolicyError("Up to 3 retries, each 1 to 120 minutes")
    return mins


def set_call_retries(policy_path, minutes, audit, by="owner"):
    """MISSEDCALL: save the call retry times (policy.json call_retry_minutes). [] = retries off. Each retry is a
    paid call on the owner's own Twilio. Backed up to policy_history/, written atomically, logged."""
    if not valid_call_retry_minutes(minutes):
        raise PolicyError("Up to 3 retries, each 1 to 120 minutes")
    policy_path = Path(policy_path)
    old = validate(json.loads(policy_path.read_bytes()))
    if old.get("call_retry_minutes", [15, 15]) == minutes and "call_retry_minutes" in old:
        return {"status": "no_change"}
    new = {**old, "call_retry_minutes": list(minutes)}
    validate(new)
    saved = _save_history(policy_path)
    old_sha = fingerprint(policy_path)
    _atomic_write(policy_path, json.dumps(new, indent=2) + "\n")
    new_sha = fingerprint(policy_path)
    audit.write("call_retries_changed", action_id="-", by=by, minutes=list(minutes), old_sha256=old_sha,
                new_sha256=new_sha, previous_version=saved.name)
    return {"status": "changed", "call_retry_minutes": list(minutes), "previous_version": saved.name}


def set_preferred_name(policy_path, name: str, audit, by="owner"):
    """Set the name the alert call greets you by ("Hi Trey, this is Bridge Warden."), or "" for the plain greeting.
    It cannot loosen any safety check, so no confirmation, but it is validated (letters, spaces, hyphens,
    apostrophes, max 40), backed up to policy_history/, written atomically and logged (the name itself is not logged)."""
    name = " ".join(str(name or "").split(" ")).strip(" ")
    while "  " in name:
        name = name.replace("  ", " ")
    if not valid_preferred_name(name):
        raise PolicyError("preferred_name must be empty or up to 40 letters, spaces, hyphens or apostrophes")
    policy_path = Path(policy_path)
    old = validate(json.loads(policy_path.read_bytes()))
    if (old.get("preferred_name") or "") == name:
        return {"status": "no_change"}
    new = {**old, "preferred_name": name}
    validate(new)
    saved = _save_history(policy_path)
    old_sha = fingerprint(policy_path)
    _atomic_write(policy_path, json.dumps(new, indent=2) + "\n")
    new_sha = fingerprint(policy_path)
    audit.write("preferred_name_changed", action_id="-", by=by, has_name=bool(name), old_sha256=old_sha,
                new_sha256=new_sha, previous_version=saved.name)
    return {"status": "changed", "preferred_name": name, "previous_version": saved.name}


def set_mode(policy_path, new_mode, audit, **kw):
    if new_mode not in MODES:
        raise PolicyError(f"mode must be one of {MODES}")
    p = load_file(policy_path)
    return apply(policy_path, {**p, "mode": new_mode}, audit, **kw)  # checks untouched: resume restores them


def trust(policy_path, payee, audit, category=None, remove=False, **kw):
    p = load_file(policy_path)
    t = json.loads(json.dumps(p.get("trusted", {}) or {}))
    payee = payee.strip().lower()
    if remove:
        t["payees"] = [x for x in t.get("payees", []) if x.strip().lower() != payee]
        t["categories"] = {c: [x for x in v if x.strip().lower() != payee] for c, v in t.get("categories", {}).items()}
        t["categories"] = {c: v for c, v in t["categories"].items() if v}
    elif category:
        t.setdefault("categories", {}).setdefault(category, [])
        if payee not in [x.lower() for x in t["categories"][category]]:
            t["categories"][category].append(payee)
    else:
        if payee not in [x.lower() for x in t.setdefault("payees", [])]:
            t["payees"].append(payee)
    return apply(policy_path, {**p, "trusted": t}, audit, **kw)


def versions(policy_path) -> list:
    d = history_dir(policy_path)
    return sorted(d.glob("*.json")) if d.exists() else []


def undo(policy_path, audit, **kw):
    """Restore the version saved by the last change (itself a logged, reversible change)."""
    vs = versions(policy_path)
    if not vs:
        return {"status": "nothing_to_undo"}
    target = load_file(vs[-1])
    return apply(policy_path, target, audit, note=f"undo to {vs[-1].name}", raw_text=vs[-1].read_text(), **kw)


def status_lines(policy: dict) -> list:
    m = mode(policy)
    lines = [f"Bridge Warden is {'ON' if m == 'on' else 'PAUSED' if m == 'paused' else 'OFF'}."]
    if m == "paused":
        lines.append("  " + PAUSE_TEXT)
    if m == "off":
        lines.append("  " + MASTER_OFF_LOSS)
    for n, (t, _, on, _) in CHECKS.items():
        lines.append(f"  [{'on ' if is_on(policy, n) else 'OFF'}] {n:<19} ({t}) {on}")
    tm = trusted_map(policy)
    lines.append("Trusted payees: " + (", ".join(f"{p} ({lbl})" for p, lbl in sorted(tm.items())) or "none"))
    return lines
