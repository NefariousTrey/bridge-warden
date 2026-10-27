# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0.
"""Light / Dark theme (Trey, Oct 26 2026 10:12 PM ET). Light is the default: white header + white logo.
Dark: dark header and page + navy logo. Saved per browser (bw_theme cookie) and, for the owner, in policy.json.
Server-rendered on <html data-theme>, so no flash and no inline styles or scripts (strict CSP)."""
import json
import re

import pytest

from bridge_warden import controls as C
from bridge_warden import web
from bridge_warden.policy import PolicyError, validate
from test_v4_dots import BASE, _server, token
from test_v4_judge import clean_env, jsrv, login as jlogin, req as jreq          # noqa: F401 (fixtures)
import test_v5_render_hosted as HT

LIGHT = '<html lang="en" data-theme="light">'
DARK = '<html lang="en" data-theme="dark">'


def is_light(body):
    return LIGHT in body and DARK not in body


def is_dark(body):
    return DARK in body and LIGHT not in body


@pytest.fixture
def s(tmp_path):
    S, srv = _server(tmp_path)
    yield S
    srv.shutdown()


@pytest.fixture
def ro(tmp_path):
    S, srv = _server(tmp_path, writable=False)
    yield S
    srv.shutdown()


def test_policy_and_prefs_default_light():
    assert C.ui_prefs(BASE)["theme"] == "light"
    assert C.ui_prefs({**BASE, "ui": {"theme": "dark"}})["theme"] == "dark"
    assert validate({**BASE, "ui": {"theme": "dark", "colorblind_mode": True}})
    for bad in ("Dark", "", "purple", None, 1):
        with pytest.raises(PolicyError):
            validate({**BASE, "ui": {"theme": bad}})


def test_page_markup_has_both_logo_sets_and_css_picks_one():
    p = web.page("T", "<h1>Hi</h1>", "home", None)
    assert p.startswith("<!doctype html>" + LIGHT)                 # Light by default
    assert '<header class="top top-light">' in p
    for suf in ("", "-yellow", "-red"):
        assert f'th-light" src="/assets/brand/bw-mark-white-v7b{suf}.png"' in p
        assert f'th-dark" src="/assets/brand/bw-mark-navy-v7b{suf}.png"' in p
    assert "html:not([data-theme=dark]) .bw-mark .th-dark,html[data-theme=dark] .bw-mark .th-light{display:none!important}" in web.STYLE
    assert "html[data-theme=dark] header.top.top-light{background:var(--navy)" in web.STYLE
    assert "style=" not in p.split("</style>")[1] and "<script>" in p      # no inline style attrs; same hashed script
    assert web.theme_html(p, "dark").startswith("<!doctype html>" + DARK)
    assert web.theme_html(p, "light") == p and web.theme_html(p, "evil") == p


def test_cookie_parse_only_light_or_dark():
    assert web.theme_from_cookie("bw_theme=dark") == "dark"
    assert web.theme_from_cookie("a=b; bw_theme=light") == "light"
    for bad in ("", "bw_theme=DARK", "bw_theme=<x>", "bw_theme=dark\"", "bw_theme"):
        assert web.theme_from_cookie(bad) is None


def test_csp_unchanged_and_style_hash_matches(s):
    r, body = s.get("/")
    assert r.getheader("Content-Security-Policy") == web.HEADERS["Content-Security-Policy"]
    assert web.STYLE_HASH in r.getheader("Content-Security-Policy") and "unsafe" not in r.getheader("Content-Security-Policy")


def test_owner_toggle_sets_cookie_and_saves_pref(s):
    assert is_light(s.get("/")[1]) and is_light(s.get("/settings")[1])
    page = s.get("/settings")[1]
    assert "Theme: Light or Dark" in page
    r, _ = s.post("/act", token=token(page, "Use the Dark theme"))
    assert r.status == 303 and r.getheader("Location") == "/settings"
    ck = r.getheader("Set-Cookie")
    assert ck.startswith("bw_theme=dark;") and "HttpOnly" in ck and "SameSite=Strict" in ck and "Path=/" in ck
    assert json.loads(s.pf.read_text())["ui"]["theme"] == "dark"               # saved for the owner
    assert any(x["event"] == "ui_pref_changed" for x in s.gate.audit.records())
    for p in ("/", "/money", "/history", "/settings"):                          # no cookie sent: saved pref wins
        assert is_dark(s.get(p)[1]), p
    r, _ = s.post("/act", token=token(s.get("/settings")[1], "Use the Light theme"))
    assert r.getheader("Set-Cookie").startswith("bw_theme=light;")
    assert json.loads(s.pf.read_text())["ui"]["theme"] == "light" and is_light(s.get("/")[1])


def test_browser_cookie_wins_over_saved_pref(s):
    sess = f"{web.COOKIE}={s.app.session}"
    r, body = s.req("GET", "/", headers={"Cookie": sess + "; bw_theme=dark"})
    assert is_dark(body)
    r, body = s.req("GET", "/", headers={"Cookie": sess + "; bw_theme=bogus"})
    assert is_light(body)                                                      # junk cookie ignored = default


def test_view_only_toggle_is_session_only(ro):
    r, _ = ro.post("/act", token=token(ro.get("/settings")[1], "Use the Dark theme"))
    assert r.status == 303 and r.getheader("Set-Cookie").startswith("bw_theme=dark;")
    assert "ui" not in json.loads(ro.pf.read_text()) and ro.app.ui_session["theme"] == "dark"


def test_grid_v3_has_dark_params_and_v2_kept():
    v3 = (web.STATIC_DIR / "bw-grid-v3.js").read_text()
    assert "document.documentElement.getAttribute('data-theme') === 'dark'" in v3
    assert "browserColorScheme: 'dark'" in v3 and "browserColorScheme: 'light'" in v3
    assert "bw-grid-v3.js" in web.GRID_FILES and (web.STATIC_DIR / "bw-grid-v2.js").exists()


def test_dark_history_page_keeps_grid_and_csp(s):
    from bridge_warden.models import ProposedAction
    s.gate.propose(ProposedAction("payout", "120.00", "USD", "designer@personal.example.com", "logo design invoice"))
    sess = f"{web.COOKIE}={s.app.session}"
    r, body = s.req("GET", "/history", headers={"Cookie": sess + "; bw_theme=dark"})
    assert r.status == 200 and is_dark(body) and "bw-grid-v3.js" in body
    assert "unsafe-inline" not in r.getheader("Content-Security-Policy")


def test_hear_page_follows_cookie(s):
    sess = f"{web.COOKIE}={s.app.session}"
    for t in ("light", "dark"):
        r, body = s.req("GET", "/hear", headers={"Cookie": f"{sess}; bw_theme={t}"})
        if r.status == 200:
            assert (is_dark if t == "dark" else is_light)(body)


def test_judge_theme_is_per_browser_and_never_writes_policy(jsrv):
    srv, _ = jsrv
    app = srv.bw_app
    pub = jreq(srv, "GET", "/")[2]
    assert is_light(pub)                                                       # public landing: Light default
    assert is_dark(jreq(srv, "GET", "/", headers={"Cookie": "bw_theme=dark"})[2])
    ck = jlogin(srv)
    jreq(srv, "GET", "/settings", headers={"Cookie": ck})
    tok = next(k for k, v in app.nonces.items() if v[0] == "ui:theme_dark")
    code, h, _ = jreq(srv, "POST", "/act", headers={"Cookie": ck, "Origin": f"http://127.0.0.1:{srv.server_address[1]}",
                                                     "Content-Type": "application/x-www-form-urlencoded"},
                      body=f"token={tok}")
    assert code == 303 and h["Set-Cookie"].startswith("bw_theme=dark;")
    assert "theme" not in app.ui_session                                       # shared demo: nothing shared changed
    assert is_light(jreq(srv, "GET", "/", headers={"Cookie": ck})[2])          # judge B (no theme cookie): Light
    for p in ("/", "/history", "/settings"):                                   # judge A (dark cookie): Dark
        assert is_dark(jreq(srv, "GET", p, headers={"Cookie": ck + "; bw_theme=dark"})[2]), p


def test_hosted_login_and_pages_follow_cookie_secure(tmp_path):
    gen = HT.srv.__wrapped__(tmp_path)
    s, app, *_ = next(gen)
    try:
        assert is_light(HT.req(s, "GET", "/login")[2])
        assert is_dark(HT.req(s, "GET", "/login", headers={"Cookie": "bw_theme=dark"})[2])
        ck = HT.login(s)
        HT.req(s, "GET", "/settings", headers={"Cookie": ck})
        tok = next(k for k, v in app.nonces.items() if v[0] == "ui:theme_dark")
        st, h, _ = HT.req(s, "POST", "/act", "token=" + tok, {"Cookie": ck, "Origin": "https://" + HT.HOST,
                                                              "Content-Type": "application/x-www-form-urlencoded"})
        assert st == 303 and h["set-cookie"].startswith("bw_theme=dark;") and "Secure" in h["set-cookie"]
        assert is_dark(HT.req(s, "GET", "/", headers={"Cookie": ck + "; bw_theme=dark"})[2])
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
