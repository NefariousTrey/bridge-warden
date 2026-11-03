# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""JUDGEFIX 2026-11-01 (Trey: get it as ready as possible for judging).
1. A hosted judge's "Test my alert" never reaches Twilio: no call, no text, no Twilio read. It opens /hear.
   The owner's own path still starts the real drill.
3. Plain, true words: no "billed to you" for a judge, no "your own hosted copy" for a judge login, and
   "the AI is off right now" instead of "no xAI key on this computer". Hosted Dev mode chats use xAI.
4. The AG chat with no money data says so and never asks xAI (it once guessed "Groceries is the biggest group").
5. Shared demo: a judge can't change the owner's saved call name, voice or retries.
Everything is offline: fake Twilio sender, mocked xAI, fake keys only."""
import json
import re
import threading
import urllib.parse

import pytest

from bridge_warden import ag_studio as STUDIO
from bridge_warden import help_chat as HC
from bridge_warden import hosted as Ho
from bridge_warden import judge_ai as JA
from bridge_warden import notify as N
from bridge_warden import web
from bridge_warden import web_ag as WA
from test_xai import FAKE_KEY, MockXai, make_gate, reply
import test_v5_render_hosted as HT

J1 = "judge-one-" + "a" * 20


@pytest.fixture
def hz(tmp_path, monkeypatch):
    """Hosted copy with a FULL (fake) Twilio env, a recording sender and mocked xAI."""
    monkeypatch.setattr(STUDIO, "ready", lambda: True)
    keys = tmp_path / "judges.txt"
    keys.write_text(J1 + "\n", encoding="utf-8")
    sent = []

    def sender(method, url, headers, body, timeout, **kw):
        sent.append(url)
        return 201, {}, b'{"sid": "CA' + b"1" * 32 + b'"}'
    mock = MockXai(reply())
    env = HT.env_for(tmp_path, XAI_API_KEY=FAKE_KEY, XAI_ZDR_CONFIRMED="1", BW_JUDGE_KEY_FILE=str(keys))
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=sender, xai_transport=mock)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s, app, sent, mock
    try:
        app.alert_test.end("test over")
    except Exception:
        pass
    s.shutdown()
    s.server_close()


def _login(s, k):
    st, h, _ = HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": k}),
                      {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST})
    assert st == 303
    return h["set-cookie"].split(";")[0]


def _token(body, text):
    for m in re.finditer(r'<form method="post" action="/act">(.*?)</form>', body, re.S):
        if text in m.group(1):
            return re.search(r'name="token" value="([^"]+)"', m.group(1)).group(1)
    raise AssertionError("no form for " + text)


def _press(s, ck, page, text, **more):
    st, _, body = HT.req(s, "GET", page, headers={"Cookie": ck})
    assert st == 200
    data = urllib.parse.urlencode({"token": _token(body, text), **more})
    return HT.req(s, "POST", "/act", data, {"Cookie": ck, "Content-Type": "application/x-www-form-urlencoded",
                                             "Origin": "https://" + HT.HOST})


def _events(app, name):
    return [r for r in app.real_gate.audit.records() if r.get("event") == name]


def _twilio_hits(sent):
    return [u for u in sent if "twilio.com" in str(u)]


# ---- 1. Test my alert --------------------------------------------------------------------------------------------
def test_hosted_judge_test_my_alert_opens_hear_and_never_reaches_twilio(hz):
    s, app, sent, _ = hz
    ck = _login(s, J1)
    st, _, settings = HT.req(s, "GET", "/settings", headers={"Cookie": ck})
    assert st == 200 and "Judge demo:" in settings and 'id="judge-key"' not in settings
    for _ in range(4):                                  # more than the old 3-call judge cap: still never a call
        st, h, _ = _press(s, ck, "/settings", "Test my alert")
        assert st == 303 and h["location"] == "/hear?from=test"
    assert _twilio_hits(sent) == []                    # no call, no text, no Twilio read
    assert _events(app, "alert_test") == [] and len(_events(app, "alert_test_judge_demo")) == 4
    assert not app.alert_test.pending() and not app.alert_test.active()
    st, _, hear = HT.req(s, "GET", "/hear?from=test", headers={"Cookie": ck})
    assert st == 200 and "Judge demo: no phone call is placed." in hear
    st, _, plain = HT.req(s, "GET", "/hear")
    assert st == 200 and "Judge demo: no phone call" not in plain          # the note only follows the button
    st, _, home = HT.req(s, "GET", "/", headers={"Cookie": HT.login(s)})
    assert "Judge demo: no phone call" not in home                        # no shared flash left for others
    assert J1 not in json.dumps(app.real_gate.audit.records())


def test_owner_test_my_alert_still_starts_the_real_drill(hz):
    s, app, sent, _ = hz
    ck = HT.login(s)
    st, h, _ = _press(s, ck, "/settings", "Test my alert")
    assert st == 303 and h["location"] == "/"
    r = _events(app, "alert_test")[-1]
    assert r["provider"] == "twilio"                   # the owner's own Twilio is still picked (call comes later)
    assert _events(app, "alert_test_judge_demo") == []


def test_twilio_adapter_is_not_ready_while_a_judge_acts(tmp_path):
    sent = []

    def sender(method, url, headers, body, timeout, **kw):
        sent.append(url)
        return 201, {}, b'{"sid": "CA' + b"1" * 32 + b'"}'
    env = {"TWILIO_ACCOUNT_SID": HT.SID, "TWILIO_AUTH_TOKEN": "tok-" + "x" * 28,
           "TWILIO_FROM_NUMBER": "+15550001111", "BW_OWNER_PHONE": "+15550002222"}
    ad = N.TwilioCallAdapter(env=env, sender=sender)
    assert ad.ready is True                            # the owner: ready
    c = JA.JudgeXaiCounter(tmp_path, limit=5)
    with JA.acting_as(J1, c):
        assert N.judge_acting() and ad.ready is False
        r = ad.place_call("Bridge Warden test call.")
        assert r["dialed"] is False and "Judge demo" in r["note"]
        assert ad.call_usage("CA" + "1" * 32) is None and ad.balance() is None
        assert isinstance(N.call_adapter({}, env=env, sender=sender, force=True), (N.TwilioCallAdapter,
                                                                                    N.DryRunCallAdapter))
    assert sent == [] and not N.judge_acting()
    ad.place_call("Bridge Warden test call.")          # the owner again: the real path still dials
    assert len(sent) == 1


def test_drill_started_by_a_judge_uses_the_dry_run(engine, tmp_path):
    from test_v4_alert_test import drill
    sent = []
    g = make_gate(engine, tmp_path, MockXai(reply()))
    env = {"TWILIO_ACCOUNT_SID": HT.SID, "TWILIO_AUTH_TOKEN": "tok-" + "x" * 28,
           "TWILIO_FROM_NUMBER": "+15550001111", "BW_OWNER_PHONE": "+15550002222"}
    d, t, _ = drill(g, env=env, sender=lambda *a, **k: (sent.append(a), (201, {}, b"{}"))[1])
    with JA.acting_as(J1, JA.JudgeXaiCounter(tmp_path / "c", limit=5)):
        r = d.start(judge_key=J1)
    assert r["started"] and r["provider"] == "dry_run" and r["real"] is False
    t.made[-1][1]()                                     # the timer fires later, on another thread
    assert sent == []


# ---- 3. words ----------------------------------------------------------------------------------------------------
def test_judge_sees_free_words_owner_sees_billed(tmp_path):
    owner = WA._ai_cost_words() + WA._studio_cost_words() + STUDIO._cost_note()
    assert "billed to you" in owner
    with JA.acting_as(J1, JA.JudgeXaiCounter(tmp_path, limit=7)):
        judge = WA._ai_cost_words() + WA._studio_cost_words() + STUDIO._cost_note()
    assert "billed to you" not in judge and "your own xAI key" not in judge
    assert "free to you" in judge.lower() and "7 of 7" in judge


def test_hosted_judge_pages_never_say_billed_to_you(hz):
    s, app, _, _ = hz
    ck = _login(s, J1)
    for p in ("/", "/history", "/settings"):
        st, _, body = HT.req(s, "GET", p, headers={"Cookie": ck})
        assert st == 200 and "billed to you" not in body, p
    words = web.EVENT_WORDS["hosted_login"][1]
    assert "your own hosted copy" not in words and "owner or judge key" in words


def test_plain_ai_off_words():
    assert "on this computer" not in web._skip_text("no_api_key")
    assert web._skip_text("no_api_key").startswith("the AI is off right now")
    src = open(web.__file__, encoding="utf-8").read()
    assert "Logged in to your own hosted copy" not in src and "no xAI key on this computer" not in src


def test_help_chat_without_ai_says_the_ai_is_off(engine, tmp_path):
    g = make_gate(engine, tmp_path, MockXai(reply()))
    g.ai = None
    out = HC.ask(g, "now", "What does the red light mean for my payment?", {"step": 0})
    assert "the AI is off right now" in out["answer"] and "no_api_key" not in out["answer"]


def test_hosted_dev_mode_chats_use_xai_on_render(hz):
    s, app, _, mock = hz
    assert app.chat_ai() is app.real_gate.ai                # normal view: the real client
    app.real_gate.dev.set(True)
    try:
        assert app.dev_view() and getattr(app.gate, "ai", None) is None   # the sample gate has no AI ...
        assert app.chat_ai() is app.real_gate.ai                          # ... but the chats use xAI on Render
        n = len(mock.requests)
        ck = _login(s, J1)
        st, _, body = HT.req(s, "POST", "/ag-studio/v1/responses",
                             json.dumps({"input": [{"role": "user", "content": "Biggest group?"}]}),
                             {"Cookie": ck, "Content-Type": "application/json", "Origin": "https://" + HT.HOST})
        assert st == 200, body                               # sample data is there, so xAI is asked
        assert len(mock.requests) > n
        assert json.loads(body)["bw_usage"] != STUDIO.NO_DATA_USAGE
    finally:
        app.real_gate.dev.set(False)


def test_local_dev_mode_stays_ai_free(engine, tmp_path):
    class App:
        hosted = None
        gate = type("G", (), {"ai": None})()
        real_gate = type("G", (), {"ai": object()})()
        dev_view = staticmethod(lambda: True)
    assert web.WebApp.chat_ai(App()) is None


# ---- 4. AG chat with no data -------------------------------------------------------------------------------------
def test_studio_with_no_data_answers_locally_and_sends_nothing(engine, tmp_path):
    mock = MockXai(reply())
    g = make_gate(engine, tmp_path, mock)
    raw = json.dumps({"input": [{"role": "user", "content": "Which group is biggest?"}]}).encode()
    code, body = STUDIO.proxy(g, raw, has_data=False)
    assert code == 200 and mock.requests == []
    text = body["output"][0]["content"][0]["text"]
    assert text == STUDIO.NO_DATA_SAY and "Dev mode" in text and "Groceries" not in text
    assert body["bw_usage"] == STUDIO.NO_DATA_USAGE
    last = [r for r in g.audit.records() if r.get("event") == STUDIO.EVENT][-1]
    assert last["sent"] is False and last["why"] == "no_data"
    assert "Never guess a group" in STUDIO.STUDIO_RULES


def test_hosted_studio_on_a_fresh_copy_says_no_data(hz):
    s, app, _, mock = hz
    assert WA.studio_data(app)["rows"] == []
    ck = _login(s, J1)
    st, _, body = HT.req(s, "POST", "/ag-studio/v1/responses",
                         json.dumps({"input": [{"role": "user", "content": "Which group is biggest?"}]}),
                         {"Cookie": ck, "Content-Type": "application/json", "Origin": "https://" + HT.HOST})
    assert st == 200 and mock.requests == []
    assert json.loads(body)["output"][0]["content"][0]["text"] == STUDIO.NO_DATA_SAY


# ---- 5. shared demo ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("button,field,value", [("Save", "preferred_name", "Mallory")])
def test_judge_cannot_change_the_owners_call_name(hz, button, field, value):
    s, app, _, _ = hz
    before = app.preferred_name()
    ck = _login(s, J1)
    st, _, body = HT.req(s, "GET", "/settings", headers={"Cookie": ck})
    tok = _token(body, 'id="preferred-name"')
    st, h, _ = HT.req(s, "POST", "/act", urllib.parse.urlencode({"token": tok, field: value}),
                      {"Cookie": ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST})
    assert st == 303 and h["location"] == "/settings"
    assert app.preferred_name() == before and value not in json.dumps(app.real_gate.audit.records())
