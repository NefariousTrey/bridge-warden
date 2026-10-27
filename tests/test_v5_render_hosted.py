# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0.
"""v5: your own copy on Render (render.yaml + `python -m bridge_warden hosted`). Call menu served by the app
itself (no Cloudflare Worker), with the same Twilio-signature OR signed-link check as the Worker."""
import http.client
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from bridge_warden import hosted as Ho
from bridge_warden import notify as N
from bridge_warden import web

ROOT = Path(__file__).resolve().parent.parent
HOST = "bw-test.onrender.com"
LOGIN = "L" * 40
LINK = "K" * 40
SID = "AC" + "0" * 32


def env_for(tmp_path, **more):
    e = {"RENDER_EXTERNAL_HOSTNAME": HOST, "BW_LOGIN_KEY": LOGIN, "BW_CALL_LINK_KEY": LINK,
         "TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": "tok-" + "x" * 28, "TWILIO_FROM_NUMBER": "+15550001111",
         "BW_OWNER_PHONE": "+15550002222", "BW_PREFERRED_NAME": "Trey", "BW_DATA_DIR": str(tmp_path / "data")}
    e.update(more)
    return e


@pytest.fixture
def srv(tmp_path):
    sent = []

    def sender(method, url, headers, body, timeout, **kw):
        sent.append((url, urllib.parse.parse_qs(body.decode())))
        return 201, {}, b"{}"
    env = env_for(tmp_path)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=sender)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s, app, env, sent
    s.shutdown()
    s.server_close()


def req(s, method, path, body=None, headers=None, host=HOST):
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10)
    h = {"Host": host, **(headers or {})}
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace"))
    c.close()
    return out


def login(s):
    st, h, _ = req(s, "POST", "/login", urllib.parse.urlencode({"k": LOGIN}),
                   {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HOST})
    assert st == 303
    return h["set-cookie"].split(";")[0]


# ---- settings ---------------------------------------------------------------------------------------------------
def test_refuses_without_host_or_strong_login_key(tmp_path):
    with pytest.raises(Ho.HostedRefused):
        Ho.hosted_settings({"BW_LOGIN_KEY": LOGIN})
    with pytest.raises(Ho.HostedRefused) as ex:
        Ho.hosted_settings({"RENDER_EXTERNAL_HOSTNAME": HOST, "BW_LOGIN_KEY": "short-key"})
    assert "short-key" not in str(ex.value)        # never echo the key
    with pytest.raises(Ho.HostedRefused):
        Ho.hosted_settings({"RENDER_EXTERNAL_HOSTNAME": "evil host/", "BW_LOGIN_KEY": LOGIN})
    assert Ho.hosted_settings({"RENDER_EXTERNAL_HOSTNAME": HOST, "BW_PUBLIC_HOST": "bw.example.com",
                               "BW_LOGIN_KEY": LOGIN})["host"] == "bw.example.com"   # your own domain wins


def test_local_serve_is_still_localhost_only():
    import inspect
    assert "127.0.0.1" in inspect.getsource(web.serve)


def test_prepare_policy_once_and_twilio_only_when_ready(tmp_path):
    p = Ho.prepare_policy(tmp_path / "a", env_for(tmp_path))
    pol = json.loads(p.read_text())
    assert pol["preferred_name"] == "Trey"
    assert pol["notify"]["call_on_fraud"] == {"enabled": True, "provider": "twilio", "experimental": True}
    p.write_text('{"mine": 1}')
    assert Ho.prepare_policy(tmp_path / "a", env_for(tmp_path)).read_text() == '{"mine": 1}'   # never overwritten
    p2 = Ho.prepare_policy(tmp_path / "b", env_for(tmp_path, TWILIO_AUTH_TOKEN=""))
    c = json.loads(p2.read_text()).get("notify", {}).get("call_on_fraud", {})
    assert c.get("provider") != "twilio"


# ---- web: host, login, cookie -------------------------------------------------------------------------------------
def test_wrong_host_refused_health_ok(srv):
    s, *_ = srv
    assert req(s, "GET", "/", host="evil.example.com")[0] == 421
    assert req(s, "GET", "/healthz", host="10.0.0.5:10000")[0] == 200
    st, h, _ = req(s, "GET", "/")
    assert st == 303 and h["location"] == "/login" and "max-age" in h["strict-transport-security"]
    assert req(s, "GET", "/history")[1].get("location") == "/login"


def test_login_form_post_only_secure_cookie(srv):
    s, app, *_ = srv
    st, _, body = req(s, "GET", "/login")
    assert st == 200 and 'type="password"' in body and LOGIN not in body
    st, h, _ = req(s, "GET", "/login?k=" + LOGIN)       # key in a URL never logs you in
    assert "set-cookie" not in h
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    assert req(s, "POST", "/login", "k=wrong", {**form, "Origin": "https://evil.example.com"})[0] == 403
    assert req(s, "POST", "/login", "k=" + LOGIN, {**form, "Origin": "http://" + HOST})[0] == 403
    assert req(s, "POST", "/login", "k=wrong", form)[0] == 401
    st, h, _ = req(s, "POST", "/login", "k=" + LOGIN, {**form, "Origin": "https://" + HOST})
    assert st == 303 and "Secure" in h["set-cookie"] and "HttpOnly" in h["set-cookie"]
    st, _, body = req(s, "GET", "/", headers={"Cookie": h["set-cookie"].split(";")[0]})
    assert st == 200 and "Runs on your own Render service." in body and "bw-mark-white-v7b" in body
    assert 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body and '<header class="top top-light">' in body     # Oct 26 10:11 PM ET: all white
    ck = {"Cookie": h["set-cookie"].split(";")[0]}
    st, _, body = req(s, "GET", "/history", headers=ck)                # used to crash: _page had no mark_back
    assert st == 200 and "bw-mark-white-v7b" in body and 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body
    assert '<header class="top top-light">' in body                     # white header on Guard History
    events = [r["event"] for r in app.gate.audit.records()]
    assert "hosted_login" in events and "hosted_login_refused" in events
    assert all(LOGIN not in json.dumps(r) for r in app.gate.audit.records())


def test_login_rate_limited(srv):
    s, *_ = srv
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    codes = [req(s, "POST", "/login", "k=nope", form)[0] for _ in range(Ho.LOGIN_FAILS_PER_MINUTE + 1)]
    assert codes[-1] == 429
    assert req(s, "POST", "/login", "k=" + LOGIN, form)[0] == 429   # even the right key waits a minute


def test_login_guard_window():
    t = [0.0]
    g = Ho.LoginGuard("k" * 40, clock=lambda: t[0])
    for _ in range(Ho.LOGIN_FAILS_PER_MINUTE):
        assert g.check("x") == "bad"
    assert g.check("k" * 40) == "slow"
    t[0] = 61
    assert g.check("k" * 40) == "ok"


# ---- the call menu (no Worker) ------------------------------------------------------------------------------------
def signed(path_query, to="+15550002222", sid=SID, now=None):
    return N.sign_link("https://" + HOST + path_query, LINK, to, sid, now=now)


def test_unsigned_call_refused(srv):
    s, *_ = srv
    assert req(s, "POST", "/voice?t=1&n=1", "To=%2B15550002222", {"Content-Type": "application/x-www-form-urlencoded"})[0] == 403
    assert req(s, "GET", "/voice?t=1&n=1")[0] == 403


def test_signed_link_works_and_follow_ups_keep_same_expiry(srv):
    s, *_ = srv
    u = urllib.parse.urlsplit(signed("/voice?t=1&n=1&nm=Trey"))
    e = urllib.parse.parse_qs(u.query)["e"][0]
    body = urllib.parse.urlencode({"To": "+15550002222", "AccountSid": SID, "CallSid": "CA1"})
    st, h, xml = req(s, "POST", u.path + "?" + u.query, body, {"Content-Type": "application/x-www-form-urlencoded"})
    assert st == 200 and h["content-type"].startswith("text/xml") and "<Response>" in xml and "Trey" in xml
    links = re.findall(r'https://' + re.escape(HOST) + r'/(?:gather|other|walk)\?[^"<\s]*', xml)
    assert links and all(("e=" + e) in x for x in links)
    nxt = urllib.parse.urlsplit(links[0].replace("&amp;", "&"))
    st2, _, xml2 = req(s, "POST", nxt.path + "?" + nxt.query, body + "&Digits=1",
                       {"Content-Type": "application/x-www-form-urlencoded"})
    assert st2 == 200 and "<Response>" in xml2
    # the same link for a different phone or account is refused
    other = body.replace("%2B15550002222", "%2B15559999999")
    assert req(s, "POST", u.path + "?" + u.query, other, {"Content-Type": "application/x-www-form-urlencoded"})[0] == 403
    # tampering with the name is refused
    bad = u.query.replace("nm=Trey", "nm=Bob")
    assert req(s, "POST", u.path + "?" + bad, body, {"Content-Type": "application/x-www-form-urlencoded"})[0] == 403


def test_expired_link_refused(tmp_path):
    cfg = Ho.hosted_settings(env_for(tmp_path))
    u = urllib.parse.urlsplit(signed("/voice?t=1&n=1", now=time.time() - 4000))
    st, *_ = Ho.answer_call(cfg, {}, u.path, u.query, {"To": "+15550002222", "AccountSid": SID}, "")
    assert st == 403


def test_twilio_signature_accepted(tmp_path):
    env = env_for(tmp_path)
    cfg = Ho.hosted_settings(env)
    params = {"To": "+15550002222", "AccountSid": SID, "Digits": "2"}
    sig = Ho.twilio_signature(env["TWILIO_AUTH_TOKEN"], "https://" + HOST + "/gather?t=1&n=1", params)
    st, body, _ = Ho.answer_call(cfg, env, "/gather", "t=1&n=1", params, sig)
    assert st == 200 and "<Response>" in body
    assert Ho.answer_call({**cfg, "link_key": ""}, env, "/gather", "t=1&n=1", params, "bad")[0] == 403


def test_not_set_up_without_any_secret(tmp_path):
    cfg = {**Ho.hosted_settings(env_for(tmp_path)), "auth_token": "", "link_key": ""}
    st, body, _ = Ho.answer_call(cfg, {}, "/voice", "t=1", {}, "")
    assert st == 403 and "not set up" in body


def test_call_voice_choice(tmp_path):
    env = env_for(tmp_path, BW_CALL_VOICE="Polly.Joanna")
    cfg = Ho.hosted_settings(env)
    u = urllib.parse.urlsplit(signed("/voice?t=1&n=1"))
    _, body, _ = Ho.answer_call(cfg, env, u.path, u.query, {"To": "+15550002222", "AccountSid": SID}, "")
    assert 'voice="Polly.Joanna"' in body
    _, body2, _ = Ho.answer_call(cfg, {}, u.path, u.query, {"To": "+15550002222", "AccountSid": SID}, "")
    assert 'voice="man"' in body2


def test_real_call_points_back_at_this_app_and_is_accepted(srv):
    s, app, env, sent = srv
    assert env["BW_CALL_URL"] == "https://" + HOST
    a = N.TwilioCallAdapter(env=env, sender=lambda *a, **k: (sent.append(urllib.parse.parse_qs(a[3].decode())), (201, {}, b""))[1])
    assert a.place_call("Hi Trey. A payment was blocked.", name="Trey")["dialed"]
    url = sent[-1]["Url"][0]
    assert url.startswith("https://" + HOST + "/voice?") and "&s=" in url
    u = urllib.parse.urlsplit(url)
    st, *_ = Ho.answer_call(app.hosted, env, u.path, u.query, {"To": env["BW_OWNER_PHONE"], "AccountSid": SID}, "")
    assert st == 200


# ---- the Blueprint files ------------------------------------------------------------------------------------------
def test_render_yaml_self_host_blueprint():
    y = (ROOT / "render.yaml").read_text()
    assert "Made by @Nefarious_Trey, with Grok." in y and "Copyright 2026 Douglas Gibbons III" in y
    assert re.search(r"^\s+plan: free$", y, re.M)
    assert 'startCommand: "python -m bridge_warden hosted"' in y
    assert "healthCheckPath: /healthz" in y and 'autoDeployTrigger: "off"' in y
    blocks = dict(re.findall(r"- key: (\S+)\n\s+((?:sync: false|generateValue: true|value: \S+))", y))
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "BW_OWNER_PHONE",
              "BW_PREFERRED_NAME", "BW_CALL_VOICE"):
        assert blocks[k] == "sync: false", k
    assert blocks["BW_LOGIN_KEY"] == blocks["BW_CALL_LINK_KEY"] == "generateValue: true"
    assert "judge" not in re.sub(r"#.*", "", y)
    assert (ROOT / "render-judge.yaml").exists()
