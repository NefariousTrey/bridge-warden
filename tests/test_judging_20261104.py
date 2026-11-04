# Made by @Nefarious_Trey,
# with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""v1.0.0-judging (Nov 4, 2026): judge notes, site login wording, legal notice, one README story, credit form."""
import re
from pathlib import Path

from bridge_warden import web

ROOT = Path(__file__).resolve().parents[1]
SLEEP = "The free demo server sleeps when idle, so the first load can take about a minute."
TRIAL = ("The AG Studio dashboard uses a trial license; if it lapses near the end of judging, "
         "a small watermark appears and everything still works.")
LEGAL_HEADS = ("**Acceptable Use.**", "**Disclaimer of Warranty.**", "**Limitation of Liability.**")


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_two_exact_judge_notes_on_page_and_guide():
    body = web.judges_body()
    guide = _read("JUDGE_TESTING.md")
    for line in (SLEEP, TRIAL):
        assert line in web.JUDGE_TOP_FACTS
        assert web.html.escape(line, quote=False) in body or line in body, line
        assert line in guide, line


def test_site_login_note_points_to_devpost_and_never_names_a_password():
    body = web.judges_body()
    guide = _read("JUDGE_TESTING.md")
    assert web.JUDGE_SITE_LOCK_NOTE in body and web.JUDGE_SITE_LOCK_NOTE in guide
    assert "Devpost private testing notes" in web.JUDGE_SITE_LOCK_NOTE
    assert "No sign-in needed" not in guide
    for bad in ("password", "secret", "token"):
        assert bad not in web.JUDGE_SITE_LOCK_NOTE.lower()


def test_legal_notice_in_guide_and_setup():
    readme = _read("README.md")
    notice = readme[readme.index(LEGAL_HEADS[0]):]
    notice = notice[:notice.index("Limitation of Liability.")]
    for name in ("JUDGE_TESTING.md", "SETUP_YOUR_OWN.md", "README.md"):
        t = _read(name)
        assert "### Legal notice" in t, name
        for h in LEGAL_HEADS:
            assert h in t, (name, h)
        assert notice in t, name
    assert "18 and over" in _read("SETUP_YOUR_OWN.md")


def test_readme_tells_one_story():
    readme = _read("README.md")
    assert "**Bridge Warden stands between scammers and your PayPal.**" in readme
    assert "New in v4" not in readme and "## Update 20" not in readme
    assert not re.search(r"(?i)not deployed", readme)
    assert not re.search(r"\bwe built\b", readme, re.I)
    assert "under a minute" in readme and "within 20 minutes" in readme and "44 seconds" in readme
    log = _read("CHANGELOG.md")
    assert "## New in v4: the Bridge Warden app" in log and "## Update 2026-11-02" in log


def test_drill_timing_matches_the_docs():
    from bridge_warden import notify
    assert notify.TEST_DELAY_MAX == 20 * 60 and notify.TEST_COOLDOWN == 20 * 60


def test_credit_is_two_lines_in_code_headers():
    one = "Made by @Nefarious_Trey, with Grok."
    for p in list((ROOT / "bridge_warden").rglob("*.py")) + list((ROOT / "bridge_warden" / "static").glob("bw-*.js")):
        if "vendor" in p.parts:
            continue
        assert one not in p.read_text(encoding="utf-8"), p
    for name in ("README.md", "render.yaml"):
        assert one not in _read(name), name
