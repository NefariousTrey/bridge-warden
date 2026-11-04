# Made by @Nefarious_Trey,
# with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""DEPLOYBUTTON 2026-11-02 (Trey: a one-click Deploy to Render button).
render.yaml makes a full Bridge Warden on the judge's OWN free Render account. Every box Render asks is optional:
"none" counts as empty, no Twilio = Hear the call, no xAI = local rules, no PayPal = webhook off, and a fresh copy
opens in Dev mode with sample data (BW_DEMO_DATA=on). Everything is offline: fake keys, a recording sender."""
import json
import re
import threading
from pathlib import Path

import pytest

from bridge_warden import hosted as Ho
from bridge_warden import notify as N
from bridge_warden import web
import test_v5_render_hosted as HT
from test_judgefix_20261101 import _events, _press, _twilio_hits

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ONLY = {"RENDER_EXTERNAL_HOSTNAME": HT.HOST, "BW_LOGIN_KEY": HT.LOGIN, "BW_CALL_LINK_KEY": HT.LINK}
OPTIONAL = ("BW_OWNER_PHONE", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "XAI_API_KEY",
            "PAYPAL_CLIENT_ID", "PAYPAL_SANDBOX_SECRET", "BW_PAYPAL_WEBHOOK_ID")


def _serve(env):
    sent = []

    def sender(method, url, headers, body, timeout, **kw):
        sent.append(url)
        return 201, {}, b'{"sid": "CA' + b"1" * 32 + b'"}'
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=sender)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, app, sent


def _stop(s, app):
    try:
        app.alert_test.end("test over")
    except Exception:
        pass
    s.shutdown()
    s.server_close()


def _yaml():
    return (ROOT / "render.yaml").read_text(encoding="utf-8")


def _env_blocks(y):
    return dict(re.findall(r"- key: (\S+)[^\n]*\n\s+((?:sync: false|generateValue: true|value: \S+))", y))


# ---- render.yaml ------------------------------------------------------------------------------------------------
def test_blueprint_asks_only_for_the_boxes_trey_listed():
    b = _env_blocks(_yaml())
    for k in OPTIONAL:
        assert b[k] == "sync: false", k                       # secrets: Render asks, never in the repo
    assert b["BW_LOGIN_KEY"] == b["BW_CALL_LINK_KEY"] == "generateValue: true"
    assert b["BW_DEMO_DATA"] == 'value: "on"' and b["BW_FREE_PLAN"] == 'value: "on"'
    asked = {k for k, v in b.items() if v == "sync: false"}
    assert asked == set(OPTIONAL)                              # nothing else to fill in
    assert re.search(r"^\s+plan: free$", _yaml(), re.M) and "disk:" not in re.sub(r"#.*", "", _yaml())


def test_blueprint_uses_only_fields_in_render_docs():
    """No 'description' field exists for envVars (render.com/docs/blueprint-spec), so descriptions are comments."""
    body = re.sub(r"#.*", "", _yaml())
    assert "description" not in body
    for k in re.findall(r"^\s+(?:- )?([A-Za-z]+):", body, re.M):
        assert k in {"services", "type", "name", "runtime", "plan", "buildCommand", "startCommand",
                     "healthCheckPath", "autoDeployTrigger", "envVars", "key", "value", "generateValue", "sync",
                     "region"}, k   # PREFLIP: region is in the blueprint spec (default oregon)
    for k in OPTIONAL:
        assert re.search(r"- key: " + k + r"\s+#", _yaml()), k     # every asked box has a plain description


def test_blueprint_comments_name_each_box_and_the_skip_word():
    y = _yaml()
    head = y.split("services:")[0]
    for k in OPTIONAL + ("BW_LOGIN_KEY", "BW_DEMO_DATA"):
        assert k in head, k
    assert "type: none" in head and "EVERY ONE IS OPTIONAL" in head
    assert "github.com/NefariousTrey/bridge-warden" in head and "public" in head


# ---- "none" = empty ---------------------------------------------------------------------------------------------
def test_skip_words_drop_only_optional_boxes():
    env = {**REQUIRED_ONLY, "TWILIO_ACCOUNT_SID": "none", "XAI_API_KEY": " None ", "PAYPAL_CLIENT_ID": "-",
           "BW_OWNER_PHONE": "+15550002222", "BW_SITE_LOCK_PASSWORD": "skip"}
    gone = Ho.drop_skip_words(env)
    assert set(gone) == {"TWILIO_ACCOUNT_SID", "XAI_API_KEY", "PAYPAL_CLIENT_ID", "BW_SITE_LOCK_PASSWORD"}
    assert env["BW_OWNER_PHONE"] == "+15550002222" and env["BW_LOGIN_KEY"] == HT.LOGIN
    assert "BW_LOGIN_KEY" not in Ho.PROMPTED_OPTIONAL and "BW_CALL_LINK_KEY" not in Ho.PROMPTED_OPTIONAL


# ---- works with only the generated values -----------------------------------------------------------------------
@pytest.mark.parametrize("fill", ["absent", "none"])
def test_fresh_copy_works_with_nothing_filled_in(tmp_path, fill):
    env = {**REQUIRED_ONLY, "BW_DATA_DIR": str(tmp_path / "data"), "BW_DEMO_DATA": "on", "BW_FREE_PLAN": "on"}
    if fill == "none":
        env.update({k: "none" for k in OPTIONAL})
    s, app, sent = _serve(env)
    try:
        assert app.gate.ai is None                             # no xAI key: local rules only
        assert app.paypal_watch is None                        # no PayPal boxes: webhook route off
        assert not N.TwilioCallAdapter(env=env).ready          # no Twilio
        assert HT.req(s, "GET", "/healthz")[0] == 200
        st, _, _ = HT.req(s, "POST", "/paypal-webhook", "{}", {"Content-Type": "application/json"})
        assert st in (400, 404, 503)
        ck = HT.login(s)
        for p in ("/", "/history", "/settings", "/hear", "/judges"):
            st, _, body = HT.req(s, "GET", p, headers={"Cookie": ck})
            assert st == 200, p
        assert app.real_gate.dev.on()                          # Dev mode on: sample data shows
        assert "TEST" in HT.req(s, "GET", "/history", headers={"Cookie": ck})[2]
        st, h, _ = _press(s, ck, "/settings", "Test my alert")
        assert st == 303 and h["location"] == "/hear?from=notwilio"
        st, _, hear = HT.req(s, "GET", "/hear?from=notwilio", headers={"Cookie": ck})
        assert st == 200 and web.NO_TWILIO_SAY.split(".")[0] in hear
        shown = [r for r in app.gate.audit.records() if r.get("event") == "alert_test_no_twilio"]   # Dev mode:
        assert len(shown) == 1 and shown[0]["dialed"] is False                     # the History you see
        assert _events(app, "alert_test") == []
        assert _twilio_hits(sent) == [] and sent == []         # nothing sent anywhere
        rec = json.dumps(app.real_gate.audit.records())
        assert HT.LOGIN not in rec and HT.LINK not in rec
    finally:
        _stop(s, app)


def test_demo_data_turns_on_once_and_off_stays_off(tmp_path):
    env = {**REQUIRED_ONLY, "BW_DATA_DIR": str(tmp_path / "data"), "BW_DEMO_DATA": "on"}
    s, app, _ = _serve(dict(env))
    try:
        assert app.real_gate.dev.on()
        r = _events(app, "dev_mode_on")
        assert len(r) == 1 and r[0]["by"] == "first start (BW_DEMO_DATA)"
        app.real_gate.dev.set(False)                           # owner turned it off
    finally:
        _stop(s, app)
    s, app, _ = _serve(dict(env))                              # restart, same folder (paid disk)
    try:
        assert not app.real_gate.dev.on() and len(_events(app, "dev_mode_on")) == 1
    finally:
        _stop(s, app)


@pytest.mark.parametrize("val", [None, "", "off"])
def test_without_demo_data_nothing_changes(tmp_path, val):
    env = HT.env_for(tmp_path)
    if val is not None:
        env["BW_DEMO_DATA"] = val
    s, app, _ = _serve(env)
    try:
        assert not app.real_gate.dev.on() and _events(app, "dev_mode_on") == []
    finally:
        _stop(s, app)


def test_owner_with_twilio_still_starts_the_real_drill(tmp_path):
    """The owner path (Trey's live copy has Twilio, no BW_DEMO_DATA) is unchanged."""
    env = HT.env_for(tmp_path)
    s, app, sent = _serve(env)
    try:
        st, h, _ = _press(s, HT.login(s), "/settings", "Test my alert")
        assert st == 303 and h["location"] == "/"
        assert _events(app, "alert_test")[-1]["provider"] == "twilio"
        assert _events(app, "alert_test_no_twilio") == []
    finally:
        _stop(s, app)


def test_owner_with_call_on_fraud_off_keeps_todays_behavior(tmp_path):
    env = HT.env_for(tmp_path)
    s, app, _ = _serve(env)
    try:
        app.alert_test.gate.engine.p.setdefault("notify", {})["call_on_fraud"] = {"enabled": False}
        assert web._twilio_ready(app)                         # env decides, not the switch
    finally:
        _stop(s, app)


# ---- the button ---------------------------------------------------------------------------------------------------
def test_deploy_button_on_judges_page_and_docs():
    url = "https://render.com/deploy?repo=https://github.com/NefariousTrey/bridge-warden"
    assert web.DEPLOY_URL == url
    b = web.judges_body()
    assert f'id="jg-deploy" href="{url}"' in b and "Deploy to Render" in b
    for x in web.DEPLOY_STEPS + (web.DEPLOY_COST_LINE,):
        assert web.html.escape(x) in b, x
    assert "render.com/images" not in b                        # the page CSP blocks outside images: text button
    for f in ("README.md", "JUDGE_TESTING.md", "SETUP_YOUR_OWN.md"):
        t = (ROOT / f).read_text(encoding="utf-8")
        assert url in t, f
        assert "YOUR_USER/YOUR_REPO" not in t, f
    jt = (ROOT / "JUDGE_TESTING.md").read_text(encoding="utf-8")
    for x in web.DEPLOY_STEPS:
        assert x in jt, x
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "your own** Twilio account" in readme and "only works while this GitHub repo is public" in readme


def test_new_words_have_no_em_dash():
    for x in web.DEPLOY_STEPS + (web.DEPLOY_COST_LINE, web.NO_TWILIO_SAY, web.JUDGE_TOP_FACTS[5]):
        assert "\u2014" not in x
    assert "\u2014" not in _yaml()
