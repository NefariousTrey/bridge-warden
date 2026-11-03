# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""Oct 27 2026 (Trey): a private hosted test copy. BW_SITE_LOCK_PASSWORD set = every route needs HTTP Basic
(user "bw", constant-time), except Twilio's signed call webhooks (own checks), /healthz and /robots.txt
("Disallow: /"). Every response says noindex (header) and every page has meta noindex. The password is fake."""
import base64
import threading
import urllib.parse

import pytest

from bridge_warden import hosted as Ho
import test_v5_render_hosted as HT

PW = "fake-lock-" + "p" * 30


def basic(user="bw", pw=PW):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.fixture
def lk(tmp_path, capsys):
    env = HT.env_for(tmp_path, BW_SITE_LOCK_PASSWORD=PW)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s, app, env
    s.shutdown()
    s.server_close()


@pytest.mark.parametrize("path", ["/", "/judges", "/login", "/settings", "/history", "/assets/brand/bw-mark-white-v7b.png",
                                  "/ag-studio/config.json", "/hear", "/nope"])
def test_every_route_needs_the_password(lk, path):
    s, *_ = lk
    st, h, body = HT.req(s, "GET", path)
    assert st == 401 and h["www-authenticate"].startswith('Basic realm="Bridge Warden (private)"')
    assert "noindex" in h["x-robots-tag"] and "nofollow" in h["x-robots-tag"]
    assert PW not in body
    for bad in (basic(pw="wrong"), basic(user="admin"), basic(pw=PW + "x"), {"Authorization": "Bearer " + PW},
                {"Authorization": "Basic !!!"}):
        assert HT.req(s, "GET", path, headers=bad)[0] == 401


def test_posts_are_locked_too(lk):
    s, *_ = lk
    form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST}
    assert HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": HT.LOGIN}), form)[0] == 401
    assert HT.req(s, "POST", "/ag-studio/v1/responses", "{}", {"Content-Type": "application/json"})[0] == 401


def test_with_the_password_the_app_works_and_says_noindex(lk):
    s, *_ = lk
    st, h, body = HT.req(s, "GET", "/judges", headers=basic())
    assert st == 200 and "Judge Guide" in body
    assert '<meta name="robots" content="noindex, nofollow">' in body
    assert h["x-robots-tag"].startswith("noindex, nofollow")
    st, h, _ = HT.req(s, "GET", "/", headers=basic())
    assert st == 303 and "noindex" in h["x-robots-tag"]               # to the login form, still noindex
    form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST, **basic()}
    st, h, _ = HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": HT.LOGIN}), form)
    assert st == 303
    ck = h["set-cookie"].split(";")[0]
    st, _, home = HT.req(s, "GET", "/", headers={"Cookie": ck, **basic()})
    assert st == 200 and 'content="noindex, nofollow"' in home
    assert HT.req(s, "GET", "/", headers={"Cookie": ck})[0] == 401     # the session alone is not enough


def test_open_without_password_only_health_robots_and_signed_twilio_webhooks(lk):
    s, *_ = lk
    st, h, body = HT.req(s, "GET", "/healthz")
    assert st == 200 and body == "ok" and "noindex" in h["x-robots-tag"]
    st, h, body = HT.req(s, "GET", "/robots.txt")
    assert st == 200 and body == "User-agent: *\nDisallow: /\n" and "noindex" in h["x-robots-tag"]
    # Twilio webhooks are not behind the lock, but still refuse anything not signed by Twilio / our link key
    st, _, _ = HT.req(s, "POST", "/call-status", "CallStatus=completed",
                      {"Content-Type": "application/x-www-form-urlencoded"})
    assert st != 401 and st >= 400
    st, _, body = HT.req(s, "POST", "/voice", "Digits=1", {"Content-Type": "application/x-www-form-urlencoded"})
    assert st != 401 and st >= 400


def test_no_lock_when_unset_and_short_password_refused(tmp_path):
    assert Ho.site_lock({}) == ""
    with pytest.raises(Ho.HostedRefused) as ex:
        Ho.site_lock({"BW_SITE_LOCK_PASSWORD": "short"})
    assert "short" not in str(ex.value).replace("shorter", "")
    env = HT.env_for(tmp_path)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        st, h, body = HT.req(s, "GET", "/judges")
        assert st == 200 and "noindex, nofollow" not in h.get("x-robots-tag", "")   # public guide unchanged
    finally:
        s.shutdown()
        s.server_close()


def test_lock_ok_is_strict():
    good = basic()["Authorization"]
    assert Ho.lock_ok(good, PW)
    assert not Ho.lock_ok("", PW) and not Ho.lock_ok("Basic", PW)
    assert not Ho.lock_ok("Basic " + base64.b64encode(PW.encode()).decode(), PW)        # no "bw:" part


def test_password_never_logged(lk, capsys):
    s, app, env = lk
    HT.req(s, "GET", "/judges", headers=basic())
    HT.req(s, "GET", "/judges", headers=basic(pw="wrong-guess-123456789"))
    from pathlib import Path
    out = capsys.readouterr()
    blobs = [out.out, out.err] + [p.read_text(errors="replace", encoding="utf-8") for p in Path(env["BW_DATA_DIR"]).rglob("*")
                                  if p.is_file()]
    assert all(PW not in b and "wrong-guess" not in b for b in blobs)


def test_render_blueprints_list_the_lock_as_a_secret():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parent.parent
    for f in ("render.yaml",):
        y = (root / f).read_text(encoding="utf-8")
        # DEPLOYBUTTON 2026-11-02: no longer asked by the Deploy form (fewer boxes). Still a secret: never a value,
        # and documented as an optional add-later setting.
        assert "- key: BW_SITE_LOCK_PASSWORD" not in y or re.search(
            r"- key: BW_SITE_LOCK_PASSWORD\s+(#[^\n]*)?\n\s+sync: false", y)
        assert "BW_SITE_LOCK_PASSWORD" in y.split("services:")[0]
