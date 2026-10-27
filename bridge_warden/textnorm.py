"""Text hygiene for anything an agent (or an AI) writes.

Scam and injection text often hides from simple filters:
  * zero-width or other invisible characters:  "gi\u200bft cards"
  * lookalike letters from other alphabets:     "gіft" (Cyrillic i)
  * full-width or styled forms:                 "ｇｉｆｔ ｃａｒｄｓ"
  * digits standing in for letters:             "g1ft c4rds"
  * terminal escape codes that rewrite what the owner sees

normalize() -> NFKC + invisible characters removed + whitespace collapsed (used for rules, redaction, display)
skeleton()  -> normalize() + lowercase + lookalikes and digit swaps mapped to plain letters (used for matching only)
"""
from __future__ import annotations

import re
import unicodedata

# Invisible characters that are not category Cf but still render as nothing.
_EXTRA_INVISIBLE = {"\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\u034f", "\u17b4", "\u17b5"}
_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c")

# Common lookalikes (Cyrillic, Greek, others) -> Latin. Not exhaustive; NFKC handles styled/full-width forms.
_CONFUSABLES = {
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "γ": "y", "ϲ": "c", "ɡ": "g", "ɩ": "i", "ı": "i", "ȷ": "j", "ⅼ": "l", "ꞵ": "b", "ʀ": "r",
}
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "$": "s", "|": "l", "!": "i"}
_WS = re.compile(r"\s+")


def is_invisible(ch: str) -> bool:
    return unicodedata.category(ch) == "Cf" or ch in _EXTRA_INVISIBLE or ch in _BIDI


def hidden_chars(text: str) -> list:
    """Code points of invisible / direction-changing characters found in the raw text.
    A zero-width joiner inside an emoji sequence (e.g. a family emoji) is normal and not reported."""
    t = text or ""
    out = set()
    for i, c in enumerate(t):
        if not is_invisible(c):
            continue
        if c == "\u200d" and 0 < i < len(t) - 1 and unicodedata.category(t[i - 1]) in ("So", "Mn", "Sk") \
                and unicodedata.category(t[i + 1]) == "So":
            continue
        out.add(f"U+{ord(c):04X}")
    return sorted(out)


def control_chars(text: str) -> list:
    """C0/C1 control characters other than plain whitespace (escape codes, bells, backspaces...)."""
    return sorted({f"U+{ord(c):04X}" for c in (text or "")
                   if unicodedata.category(c) == "Cc" and c not in "\t\n\r"})


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = "".join(" " if unicodedata.category(c) == "Cc" else c for c in t if not is_invisible(c))
    return _WS.sub(" ", t).strip()


def skeleton(text: str) -> str:
    t = normalize(text).lower()
    t = "".join(_CONFUSABLES.get(c, c) for c in t)
    # strip accents (é -> e) so "gíft" matches too
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return "".join(_LEET.get(c, c) for c in t)


# Payee matching (v4): letters and digits that look alike in an address are folded together, so
# "paypa1.com", "paypai.com" and "paypal.com" (1 / i / l), "examp1e" (1 / l) and "g00d" (0 / o) all match.
# This is stricter than skeleton() and only used to compare payee addresses, never for scam text.
_PAYEE_FOLD = {"i": "l", "1": "l", "|": "l", "!": "l", "0": "o"}
_PAYEE_PAIRS = (("rn", "m"), ("vv", "w"), ("cl", "d"))


def payee_skeleton(text: str) -> str:
    """Lookalike-insensitive form of an address, for comparing payees only."""
    t = normalize(text).lower()
    t = "".join(_PAYEE_FOLD.get(c, c) for c in t)   # before skeleton(), so "1" and "l" end up the same
    t = skeleton(t)
    t = "".join(_PAYEE_FOLD.get(c, c) for c in t)   # skeleton() maps some lookalikes to "i"
    for a, b in _PAYEE_PAIRS:
        t = t.replace(a, b)
    return t


def lookalike_of(payee: str, named) -> tuple | None:
    """If `payee` is not one of `named` but looks like one of them, return (twin, "address" | "domain").
    "domain": same-looking domain but a different domain, e.g. bills@paypa1.com vs merchant@paypal.com."""
    p = (payee or "").strip().lower()
    named = {(x or "").strip().lower() for x in named if x}
    if not p or p in named:
        return None
    ps = payee_skeleton(p)
    for k in sorted(named):
        if payee_skeleton(k) == ps:
            return k, "address"
    if "@" in p:
        dom = p.rsplit("@", 1)[1]
        dsk = payee_skeleton(dom)
        for k in sorted(named):
            if "@" not in k:
                continue
            kd = k.rsplit("@", 1)[1]
            if kd != dom and payee_skeleton(kd) == dsk:
                return k, "domain"
    return None


def variants(text: str) -> list:
    """Texts the rules should look at: the normalized form and its de-disguised skeleton."""
    n = normalize(text)
    s = skeleton(text)
    return [n] if s == n else [n, s]


def is_plain_ascii(text: str) -> bool:
    return all(32 <= ord(c) < 127 for c in (text or ""))


def display_safe(text, limit: int = 2000) -> str:
    """For showing untrusted text to the owner (terminal or page): no escape codes, no invisible characters.
    Hidden characters are made visible as [U+XXXX] so the owner can see something was there."""
    out = []
    for c in str(text if text is not None else "")[:limit]:
        if c in "\n\r\t":
            out.append(" ")
        elif unicodedata.category(c) == "Cc" or is_invisible(c):
            out.append(f"[U+{ord(c):04X}]")
        else:
            out.append(c)
    return "".join(out)


def ascii_view(text: str) -> str:
    """Show non-ASCII characters as escapes, e.g. 'wr\\u0456ter@...', so lookalikes are obvious."""
    return (text or "").encode("ascii", "backslashreplace").decode("ascii")
