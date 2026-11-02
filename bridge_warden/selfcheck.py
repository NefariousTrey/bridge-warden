"""Static security self-check. Scans this package's own source (and the repo's text files for leaked
secrets) for patterns that must never appear. Run: python -m bridge_warden selfcheck
It is a tripwire for regressions, not a proof; tests/test_hardening.py checks the behaviour."""
from __future__ import annotations

import os
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
ALLOWED_URLS = {"https://api-m.sandbox.paypal.com", "https://api.x.ai/v1/chat/completions",
                "https://api.x.ai/v1/responses",   # v6: AG Studio chat panel proxy (same pinned host)
                "https://api.trychannel3.com/v1/search"}  # Channel3: opt-in, owner key only (net.OPT_IN_HOSTS)
DOC_PREFIXES_V4 = ("https://docs.trychannel3.com/",)
DOC_PREFIXES = ("https://docs.x.ai/", "https://developer.paypal.com/")  # cited in comments/docstrings only
XML_NAMESPACES = {"http://www.w3.org/2000/svg"}  # an SVG name tag, never fetched (exact match only)
LOCAL_PREFIXES = ("http://127.0.0.1", "http://localhost", "http://{host}")  # the local approval page

# (pattern, why). Built from pieces so this file doesn't flag itself.
_BAD = [
    (r"verify\s*=\s*" + "False", "TLS verification turned off"),
    (r"CERT_" + "NONE", "TLS certificate checks turned off"),
    (r"_create_" + "unverified_context", "unverified TLS context"),
    (r"check_hostname\s*=\s*" + "False", "TLS hostname check turned off"),
    (r"shell\s*=\s*" + "True", "shell=True (command injection risk)"),
    (r"(?<![\w.])eval\(", "eval()"),
    (r"(?<![\w.])exec\(", "exec()"),
    (r"\bimport " + "pickle|\\bfrom " + "pickle", "pickle (unsafe deserialization)"),
    (r"print\([^)]*(_secret|secret\b|api_key|_key\b|XAI_API_KEY|PAYPAL_SANDBOX_SECRET|access_token)", "printing a secret"),
    (r"log(ging)?\.\w+\([^)]*(_secret|api_key|_key\b)", "logging a secret"),
    (r"api-m\.paypal\.com(?!\")", "live PayPal host"),
]


def _source_files():
    for p in sorted(PKG.rglob("*.py")):
        if ".bak" not in p.name and p.name != "selfcheck.py":
            yield p


def scan_text(name: str, text: str) -> list:
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0]
        for rx, why in _BAD:
            if re.search(rx, code):
                problems.append(f"{name}:{n}: {why}")
        if "urlopen" in code and name != "net.py":
            problems.append(f"{name}:{n}: network call outside net.py (bypasses host pinning/TLS rules)")
        for url in re.findall(r"https?://[^\s\"'<>)]+", code):
            base = url.rstrip("/.,")
            if base in ALLOWED_URLS or base in XML_NAMESPACES or base.startswith(DOC_PREFIXES + DOC_PREFIXES_V4 + LOCAL_PREFIXES):
                continue
            if name in ("judge.py", "cli.py") and base in ("https://{h}", "http://{h}", "https://{host}"):
                continue  # judge mode: its OWN page address (Origin check / printed link); never fetched
            if name == "notify.py" and base.startswith("https://api.twilio.com/2010-04-01/Accounts/"):
                continue  # experimental call-on-fraud: owner's own Twilio, opt-in only (net.OPT_IN_HOSTS)
            if name == "web.py" and base == "https://render.com/deploy?repo=https://github.com/NefariousTrey/bridge-warden":
                continue  # /judges Deploy to Render link: a plain link the judge clicks, never fetched by BW
            if name == "paypal_client.py" and "api-m.paypal.com" in base:
                continue  # mentioned only to refuse it
            problems.append(f"{name}:{n}: URL not on the allowlist: {base}")
    return problems


def scan_source() -> list:
    problems = []
    for p in _source_files():
        problems += scan_text(p.name, p.read_text(encoding="utf-8"))
    return problems


def scan_secrets() -> list:
    """Make sure the real secret values (if set in this shell) appear in no repo file."""
    values = [(k, os.environ.get(k, "")) for k in ("PAYPAL_SANDBOX_SECRET", "XAI_API_KEY", "CHECKER_LLM_KEY",
                                                    "CHECKER_AUDIT_KEY", "BW_JUDGE_KEY")]
    values = [(k, v) for k, v in values if len(v) >= 8]
    if not values:
        return []
    problems = []
    skip = {".venv", ".git", "__pycache__", ".pytest_cache"}
    for p in ROOT.rglob("*"):
        if p.is_dir() or any(part in skip for part in p.parts) or p.stat().st_size > 20_000_000:
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        for k, v in values:
            if v.encode() in data:
                problems.append(f"{p.relative_to(ROOT)}: contains the value of {k}")
    return problems


def run() -> list:
    return scan_source() + scan_secrets()
