# Made by @Nefarious_Trey,
# with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""Judge Guide (/judges), Oct 27 2026: a real BW page, public, plain words, big numbered steps, Light/Dark works,
no keys or logins on it, and linked from the nav, Home, the judge landing and the hosted login page."""
import re
from pathlib import Path

import pytest

from bridge_warden import web
from test_v4_dots import _server
from test_v4_judge import clean_env, jsrv, login as jlogin, req as jreq          # noqa: F401 (fixtures)
import test_v5_render_hosted as HT
from test_v5_render_hosted import srv as hsrv                                    # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent
LIGHT = '<html lang="en" data-theme="light">'
DARK = '<html lang="en" data-theme="dark">'


@pytest.fixture
def s(tmp_path):
    S, srv = _server(tmp_path)
    S.origin = f"http://127.0.0.1:{srv.server_address[1]}"
    yield S
    srv.shutdown()


def _text(body):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def check_guide(body):
    assert body.startswith("<!doctype html>")
    assert '<header class="top top-light">' in body                              # same white header
    assert 'th-light" src="/assets/brand/bw-mark-white-v7b.png"' in body          # white-fill logo, top right
    assert f"<style>{web.STYLE}</style>" in body                                  # same stylesheet (CSP hash)
    assert '<a href="/judges" aria-current="page">' in body                       # nav tab is active
    t = _text(body)
    for must in ("Judge Guide", "Try it in 6 steps", "What the lights mean", "Red never goes straight to green.",
                 "Where AG Studio shows up", "Tested in sandbox with sample data to verify it works as intended.",
                 "https://youtu.be/gcGDCPxvk98", "https://github.com/NefariousTrey/bridge-warden", "Free for judges through Dec 15, 2026.",
                 "Judge login: in the Devpost testing notes.", "Test my alert",
                 "Judge mode runs the whole flow without a phone.", "The voice call is optional (your own Twilio",
                 "The free demo server sleeps when idle, so the first load can take about a minute.", "Turn on Dev mode", "Add TEST sell", "Raise TEST red",
                 "I’ve seen this", "It’s fixed", "Hear the call", "/hear",
                 "Test my alert opens Hear the call too. It never rings a phone.",
                 "All judges share one demo copy:"):
        assert must in t, must
    assert body.count('<ol class="jg-steps"') == 1
    steps = re.search(r'<ol class="jg-steps"[^>]*>(.*?)</ol>', body, re.S).group(1)
    assert steps.count("<li>") == 6
    for old in ("3 real test calls", "Got it, I", "fixed, confirm", "Type the name you want the call to use"):
        assert old not in t, old                                   # JUDGEFIX: the old, wrong judge path is gone
    for c in ("green", "yellow", "red"):
        assert f"/assets/dots/bw-dot-trey-{c}-full-glyph-48.png" in body
    assert 'action="/judges/theme"' in body and body.count('name="t" value=') == 2
    assert "<script>" not in body                                                 # no status poll on a public page
    low = re.sub(r"<style>.*?</style>", "", body, flags=re.S).lower()
    for bad in ("cross" + "roads", "bw_login_key", "password", "secret", "token", "L" * 24, "tok-"):
        assert bad.lower() not in low, bad
    assert not re.search(r"\b(sk|xai|ghp|rk)[-_][a-z0-9]{8}", low)
    # short plain sentences: no sentence in the guide body over 20 words
    guide = _text(re.search(r'<div class="jg">(.*?)</main>', body, re.S).group(1))
    # 2026-11-04: Trey's two exact judge notes are kept word for word, so they are exempt from the 20-word rule.
    exact = (web.JUDGE_TOP_FACTS[0], web.JUDGE_TOP_FACTS[-1])
    for sent in re.split(r"(?<=[.!?])\s", guide):
        if any(sent.strip().endswith(x) for x in exact):
            continue
        assert len(sent.split()) <= 20, sent


def test_page_function_and_nav_link():
    body = web.judges_page()
    check_guide(body)
    p = web.page("Home", "<h1>x</h1>", "home", None)
    assert '<a href="/judges">' in p and 'Judges</a></li>' in p


def test_placeholders_become_links_only_for_https():
    b = web.judges_body(video="https://youtu.be/abc", repo="javascript:alert(1)")
    assert '<a href="https://youtu.be/abc" rel="noopener">' in b and 'href="javascript' not in b


def test_local_judges_public_and_linked_from_home(s):
    r, body = s.req("GET", "/judges")                                             # no login needed
    assert r.status == 200
    check_guide(web.theme_html(body, "light"))
    assert LIGHT in body
    r, home = s.get("/")
    assert r.status == 200 and 'href="/judges"' in home and "Judge Guide: how to try Bridge Warden" in home


def test_theme_toggle_on_judges(s):
    hdr = {"Content-Type": "application/x-www-form-urlencoded", "Origin": s.origin}
    r, _ = s.req("POST", "/judges/theme", "t=dark", hdr)
    assert r.status == 303 and r.getheader("Location") == "/judges"
    ck = r.getheader("Set-Cookie")
    assert ck.startswith("bw_theme=dark;") and "HttpOnly" in ck and "SameSite=Strict" in ck
    r, body = s.req("GET", "/judges", headers={"Cookie": "bw_theme=dark"})
    assert DARK in body and LIGHT not in body
    r, _ = s.req("POST", "/judges/theme", "t=light", hdr)
    assert r.getheader("Set-Cookie").startswith("bw_theme=light;")
    # refused: bad value, cross-site, wrong type
    assert s.req("POST", "/judges/theme", "t=purple", hdr)[0].status == 400
    assert s.req("POST", "/judges/theme", "t=dark", {**hdr, "Origin": "https://evil.example"})[0].status == 403
    assert s.req("POST", "/judges/theme", "t=dark", {**hdr, "Content-Type": "text/plain"})[0].status == 415


def test_judge_mode_serves_guide_and_landing_links_it(jsrv):
    srv, _ = jsrv
    st, h, body = jreq(srv, "GET", "/judges", host="bw-demo.onrender.com")
    assert st == 200
    check_guide(body)
    assert "Judge demo on practice data." in body
    st, _, land = jreq(srv, "GET", "/", host="bw-demo.onrender.com")
    assert 'href="/judges"' in land


def test_hosted_guide_is_public_and_login_links_it(hsrv):
    s, *_ = hsrv
    st, h, body = HT.req(s, "GET", "/judges")
    assert st == 200
    check_guide(body)
    assert "strict-transport-security" in h
    st, _, login = HT.req(s, "GET", "/login")
    assert 'href="/judges"' in login


def test_judge_testing_docs_match_page():
    for f in (ROOT / "proof" / "JUDGE_TESTING.md", ROOT / "JUDGE_TESTING.md"):
        t = f.read_text(encoding="utf-8")
        assert "cross" + "roads" not in t.lower()
    t = (ROOT / "JUDGE_TESTING.md").read_text(encoding="utf-8")          # the one true guide (Oct 27 audit fix)
    for must in ("Tested in sandbox with sample data to verify it works as intended.", "https://youtu.be/gcGDCPxvk98",
                 "https://github.com/NefariousTrey/bridge-warden", "Dec 15", "Judge login: in the Devpost testing notes.",
                 "Red never goes straight to green.", "AG Studio", "/judges"):
        assert must in t, must
    assert "../JUDGE_TESTING.md" in (ROOT / "proof" / "JUDGE_TESTING.md").read_text(encoding="utf-8")   # pointer only


def test_render_blueprint_free_and_secrets_not_synced():
    y = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+plan: free$", y, re.M) and "disk:" not in re.sub(r"#.*", "", y)
    keys = dict(re.findall(r"- key: (\S+)[^\n]*\n\s+((?:sync: false|generateValue: true|value: \S+))", y))
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "BW_OWNER_PHONE"):
        assert keys[k] == "sync: false"
    for k in ("BW_LOGIN_KEY", "BW_CALL_LINK_KEY"):
        assert keys[k] == "generateValue: true"
    for k in ("BW_SMTP_PASSWORD", "BW_PUBLIC_HOST", "BW_JUDGE_VIDEO_URL"):
        assert k in y                                                            # optional ones are listed (names only)



def _form_token(body, text):
    """Token of the /act form whose button shows `text`."""
    for m in re.finditer(r'<form method="post" action="/act">(.*?)</form>', body, re.S):
        if text in m.group(1):
            return re.search(r'name="token" value="([^"]+)"', m.group(1)).group(1)
    raise AssertionError("no form for " + text)


def test_no_phone_line_is_true_in_judge_mode(jsrv):
    """The /judges line says judge mode needs no phone. Prove it with NO Twilio set: start, gift-card scam (red),
    seen (yellow), fixed (green), and Test my alert starts on the dry run (no phone rings)."""
    import os
    import urllib.parse
    from bridge_warden import notify
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "BW_OWNER_PHONE"):
        assert not os.environ.get(k), k
    srv, _ = jsrv
    port = srv.server_address[1]
    ck = jlogin(srv)
    form = {"Cookie": ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://127.0.0.1:{port}"}

    def act(body, text, **more):
        data = urllib.parse.urlencode({"token": _form_token(body, text), **more})
        st, h, _ = jreq(srv, "POST", "/act", headers=form, body=data)
        assert st == 303, (text, st)
        return jreq(srv, "GET", "/", headers={"Cookie": ck})[2]

    st, _, home = jreq(srv, "GET", "/", headers={"Cookie": ck})
    assert st == 200
    gift = re.search(r"<b>Gift-card scam</b>.*?</li>", home, re.S).group(0)
    home = act(gift, "Send this request")
    assert "Got it, I" in home                                   # red: the seen button shows
    home = act(home, "seen the blocked ones")
    assert 'id="seen-fix"' in home                               # yellow: confirm card
    home = act(home, "fixed, confirm")
    assert 'id="seen-fix"' not in home
    assert isinstance(notify.call_adapter({}, env={}, force=True), notify.DryRunCallAdapter)
    for f in (ROOT / "JUDGE_TESTING.md",):
        assert ("Judge mode runs the whole flow without a phone. The voice call is optional "
                "(your own Twilio, since it's open source).") in f.read_text(encoding="utf-8")


def test_top_box_facts_match_the_code():
    """Trey's top box. Each line is checked against the code, so the page can't drift from it."""
    from bridge_warden import notify, net, judge
    b = web.judges_body()
    top = b.index('id="jg-top-h"')
    assert top < b.index("Bridge Warden watches the payments")             # the box is at the top
    for x in web.JUDGE_TOP_FACTS:
        assert web.html.escape(x) in b, x
    assert notify.JUDGE_CALL_CAP == 3            # still the cap for LOCAL judge-key test calls (not on the page)
    assert "3 real test calls" not in b                                     # JUDGEFIX: hosted judges get no calls
    assert net.PINNED_HOSTS == frozenset({"api-m.sandbox.paypal.com", "api.x.ai"})   # "PayPal is sandbox only"
    assert "TWILIO_ACCOUNT_SID" in judge.OWNER_SECRET_ENV                  # judge mode never has Twilio
    assert not re.search(r"\$\s?\d|per minute|/min\b|cents", _text(b), re.I)   # no prices
    for f in (ROOT / "JUDGE_TESTING.md",):
        t = f.read_text(encoding="utf-8")
        assert t.index("Good to know") < t.index("Try it in 6 steps")
        for x in web.JUDGE_TOP_FACTS:
            assert x in t, (f.name, x)


def test_top_box_ai_line_matches_the_judge_cap(monkeypatch):
    """Line 2: real xAI on our key, up to 1,000 messages, one shared judge cap (BW_JUDGE_XAI_CAP, default 1000)."""
    from bridge_warden import judge_ai as JA
    line = ("All AI is real xAI: help chats, Ask AI about this, the AG chat panel and the money check summary. "
            "Free to you on our key (1,000 messages in all, shared by every judge).")      # judge_ai.py: one cap for every use
    assert web.JUDGE_TOP_FACTS[1] == line and JA.DEFAULT_CAP == 1000
    monkeypatch.delenv("BW_JUDGE_XAI_CAP", raising=False)
    assert web.html.escape(line) in web.judges_body()
    monkeypatch.setenv("BW_JUDGE_XAI_CAP", "250")
    assert "(250 messages in all, shared by every judge)" in web.judges_body()
    for f in (ROOT / "JUDGE_TESTING.md",):
        assert "2. " + line in f.read_text(encoding="utf-8")
    y = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert re.search(r"- key: XAI_API_KEY\s+#[^\n]*\n\s+sync: false", y)                # env-only, never in the repo
    assert 'autoDeployTrigger: "off"' in (ROOT / "render-judge.yaml").read_text(encoding="utf-8")
    assert "autoDeploy:" not in re.sub(r"#.*", "", (ROOT / "render-judge.yaml").read_text(encoding="utf-8"))
