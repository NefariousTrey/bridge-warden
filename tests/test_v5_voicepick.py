"""VOICEPICK 2026-10-26 (Trey): each owner picks their call voice in Settings (policy.json "call_voice").
Same allow-list as the Worker; unknown = free "man". The pick rides as a SIGNED &v= on the call link (Worker /
hosted) or is applied to inline TwiML. No pick = the server default (BW_CALL_VOICE / the Worker's CALL_VOICE).
Dev mode: Settings write the sample policy, so a pick only reaches test calls. The test form's voice is for that
one test call. Offline only: fake transports, nothing dials."""
import json
import urllib.parse

import pytest

from test_v4_alert_test import ENV, Timers, drill  # noqa: F401
from test_v4_ui import setup, token  # noqa: F401  (fixture)
from test_devmode import dev_on
from test_v5_render_hosted import HOST, LINK, SID, env_for
from bridge_warden import controls
from bridge_warden import hosted as Ho
from bridge_warden import notify as N
from bridge_warden.policy import PolicyError, valid_call_voice

B = "https://bridge-warden-call.example.workers.dev"
TWILIO = {"call_on_fraud": {"enabled": True, "provider": "twilio", "experimental": True}}
CHARON = "Google.en-US-Chirp3-HD-Charon"
BAD = ['Google.x" a="', "Google.evil<x>", "</Say><Play>x</Play>", "x" * 90, "Google.", "robot",
       "Google.en-US-Neural2-F", "Google.en-US-Wavenet-D"]                         # non-Chirp names = free voice


# ---------------------------------------------------------------- choices, tiers, costs, precedence
def test_choices_all_allowed_with_tier_and_cost():
    assert N.VOICE_CHOICES[0][0] == CHARON and ("man", "Basic man (Twilio, robotic)") in N.VOICE_CHOICES
    for v, _ in N.VOICE_CHOICES:
        assert N.voice_of(v) == v and valid_call_voice(v)
    assert N.voice_tier("man") == "Free" and N.voice_cost("man") == "free"
    assert N.voice_tier(CHARON) == "Generative" and N.voice_cost(CHARON) == "~$0.039 per call + ~$0.014/min"
    assert N.voice_tier("Google.en-US-Chirp3-HD-Fenrir") == "Generative" and N.voice_cost("Google.en-US-Chirp3-HD-Kore").startswith("~$0.039")
    assert N.voice_tier("Google.en-US-Neural2-F") == "Free"                           # Chirp only; others = free voice
    assert N.voice_tier("<bad>") == "Free"                                            # unknown = free voice


def test_precedence_pick_then_server_default():
    assert N.pick_voice("Google.en-US-Chirp3-HD-Leda", {"BW_CALL_VOICE": CHARON}) == "Google.en-US-Chirp3-HD-Leda"
    assert N.pick_voice("", {"BW_CALL_VOICE": "Google.en-US-Chirp3-HD-Puck"}) == "Google.en-US-Chirp3-HD-Puck"
    assert N.pick_voice("", {"BW_CALL_URL": B}) == CHARON                              # our Worker's CALL_VOICE
    assert N.pick_voice("", {}) == "man"                                               # inline, nothing set
    for bad in BAD:
        assert N.pick_voice(bad, {}) == "man" and not valid_call_voice(bad)


def test_call_url_signs_v():
    u = N.call_url(B, "voice", True, name="Sam", voice="Google.en-US-Chirp3-HD-Kore")
    assert u.endswith("/voice?t=1&n=1&nm=Sam&v=Google.en-US-Chirp3-HD-Kore") and "v" in N.LINK_KEYS
    assert "&v=" not in N.call_url(B, "voice", True)
    s = N.sign_link(u, "k" * 32, "+15550001111", "ACx")
    m1 = N.link_message("/voice", urllib.parse.urlsplit(s).query, "+1", "AC")
    m2 = N.link_message("/voice", urllib.parse.urlsplit(s).query.replace("Kore", "Puck"), "+1", "AC")
    assert "v=Google.en-US-Chirp3-HD-Kore" in m1 and m1 != m2                                # v is covered by the token


# ---------------------------------------------------------------- policy + controls
def test_policy_and_set_call_voice(setup):
    s = setup
    path = s.gate.policy_info["path"]
    assert controls.set_call_voice(path, "Google.en-US-Chirp3-HD-Leda", s.gate.audit, by="t")["status"] == "changed"
    assert json.loads(open(path, encoding="utf-8").read())["call_voice"] == "Google.en-US-Chirp3-HD-Leda"
    assert controls.set_call_voice(path, "Google.en-US-Chirp3-HD-Leda", s.gate.audit, by="t")["status"] == "no_change"
    for bad in BAD:
        with pytest.raises(PolicyError):
            controls.set_call_voice(path, bad, s.gate.audit, by="t")
    assert json.loads(open(path, encoding="utf-8").read())["call_voice"] == "Google.en-US-Chirp3-HD-Leda"
    assert N.saved_voice(s.gate) == "Google.en-US-Chirp3-HD-Leda"                                     # read fresh from disk
    controls.set_call_voice(path, "", s.gate.audit, by="t")
    assert N.saved_voice(s.gate) is None                                               # no pick = server default
    ev = [r for r in s.gate.audit.records() if r["event"] == "call_voice_changed"]
    assert [r["voice"] for r in ev] == ["Google.en-US-Chirp3-HD-Leda", "default"]


# ---------------------------------------------------------------- calls (fake transport)
def _sent(gate, env, **start):
    gate.engine.p["notify"] = TWILIO
    sent = []
    d, t, _ = drill(gate, env=env, sender=lambda *a, **k: sent.append(a) or (201, {}, b""), **start.pop("kw", {}))
    assert d.start(**start)["started"]
    t.made[0][1]()
    return urllib.parse.parse_qs(sent[0][3].decode())


def test_drill_voice_inline_and_worker(gate):
    gate.engine.p["call_voice"] = "Google.en-US-Chirp3-HD-Kore"
    b = _sent(gate, ENV)
    assert '<Say voice="Google.en-US-Chirp3-HD-Kore" language="en-US">Hello, this is Bridge Warden.' in b["Twiml"][0]
    b = _sent(gate, {**ENV, "BW_CALL_URL": B})
    assert b["Url"][0] == B + "/voice?t=1&n=1&v=Google.en-US-Chirp3-HD-Kore"
    b = _sent(gate, {**ENV, "BW_CALL_URL": B}, call_voice="Google.en-US-Chirp3-HD-Puck")           # this test call only
    assert b["Url"][0].endswith("&v=Google.en-US-Chirp3-HD-Puck") and gate.engine.p["call_voice"] == "Google.en-US-Chirp3-HD-Kore"
    b = _sent(gate, ENV, call_voice='Google.x" a="')                                    # unknown = free
    assert '<Say voice="man">' in b["Twiml"][0] and 'a="' not in b["Twiml"][0].replace('voice="man"', "")
    gate.engine.p.pop("call_voice")
    assert _sent(gate, {**ENV, "BW_CALL_URL": B})["Url"][0] == B + "/voice?t=1&n=1"   # no pick: Worker decides
    assert _sent(gate, ENV, kw={"voice_fn": lambda: "woman"})["Twiml"][0].count('<Say voice="woman"') >= 1


def test_real_alert_uses_saved_voice(setup, monkeypatch):
    s = setup
    got = []

    class Fake(N.DryRunCallAdapter):
        def place_call(self, text, name="", voice=None):
            got.append(voice)
            return {"dialed": False}
    controls.set_call_voice(s.gate.policy_info["path"], "Google.en-US-Chirp3-HD-Fenrir", s.gate.audit, by="t")
    n = N.Notifier(s.gate)
    n.caller = Fake()
    monkeypatch.setattr(N.dashboard, "status", lambda g, _s=iter([
        {"waiting": 0, "blocked": 0, "seq": 1, "state": "green"},
        {"waiting": 0, "blocked": 1, "seq": 2, "state": "red"}]): next(_s))
    n.check()
    n.check()
    assert got == ["Google.en-US-Chirp3-HD-Fenrir"]


# ---------------------------------------------------------------- the web picker
def test_settings_picker_save_and_bad_input(setup, monkeypatch):
    s = setup
    _, page = s.get("/settings")
    assert 'id="call-voice"' in page and 'name="call_voice"' in page and "Call voice:" in page
    assert "Charon (Google, male)" in page and "~$0.039 per call + ~$0.014/min" in page and "Basic man" in page
    assert 'id="test-voice"' in page and "My saved voice" in page
    s.post("/act", token=token(page, 'id="call-voice"'), call_voice=CHARON)
    assert json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_voice"] == CHARON
    _, page = s.get("/settings")
    assert f'<option value="{CHARON}" selected>' in page
    s.post("/act", token=token(page, 'id="call-voice"'), call_voice='"><script>x</script>')
    assert json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_voice"] == CHARON
    _, page = s.get("/settings")
    assert "not on the list" in page and "<script>x" not in page
    got = []
    monkeypatch.setattr(N.DryRunCallAdapter, "place_call",
                        lambda self, text, name="", voice=None: got.append(voice) or {"dialed": False}, raising=False)
    s.app.alert_test.timer = t = Timers()
    s.post("/act", token=token(page, "Test my alert"), call_voice="Google.en-US-Chirp3-HD-Leda")
    t.made[-1][1]()
    assert got[-1] == "Google.en-US-Chirp3-HD-Leda" and json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_voice"] == CHARON


def test_dev_mode_pick_is_test_calls_only(setup):
    s = setup
    real = s.gate.policy_info["path"]
    dev_on(s)
    _, page = s.get("/settings")
    assert "Dev mode is on: this pick only changes test calls." in page
    s.post("/act", token=token(page, 'id="call-voice"'), call_voice="Google.en-US-Chirp3-HD-Leda")
    assert "call_voice" not in json.loads(open(real, encoding="utf-8").read())                          # real policy untouched
    assert N.saved_voice(s.gate) is None                                               # real alerts: unchanged
    assert s.app.call_voice() == "Google.en-US-Chirp3-HD-Leda"                                        # sample (test) calls: the pick
    assert N.saved_voice(s.app.sample_gate()) == "Google.en-US-Chirp3-HD-Leda"


# ---------------------------------------------------------------- hosted (Render) call path
def test_hosted_signed_v_and_followups(tmp_path):
    env = env_for(tmp_path)
    cfg = Ho.hosted_settings(env)
    P = {"To": "+15550002222", "AccountSid": SID}
    u = urllib.parse.urlsplit(N.sign_link(f"https://{HOST}/voice?t=1&n=1&v=Google.en-US-Chirp3-HD-Kore", LINK, P["To"], SID))
    st, body, _ = Ho.answer_call(cfg, env, u.path, u.query, P, "")
    assert st == 200 and '<Say voice="Google.en-US-Chirp3-HD-Kore" language="en-US">' in body and 'voice="man"' not in body
    act = urllib.parse.urlsplit(body.split('action="')[1].split('"')[0].replace("&amp;", "&"))
    assert "v=Google.en-US-Chirp3-HD-Kore" in act.query and "s=" in act.query
    st2, b2, _ = Ho.answer_call(cfg, env, act.path, act.query, {**P, "Digits": "1"}, "")
    assert st2 == 200 and 'voice="Google.en-US-Chirp3-HD-Kore"' in b2
    bad = u.query.replace("Kore", "Fenrir")
    assert Ho.answer_call(cfg, env, u.path, bad, P, "")[0] == 403                      # v is signed
    assert Ho.carry_voice(f'<a action="https://evil.example/gather?t=1">', f"https://{HOST}", "man").count("v=") == 0


def test_judge_pick_is_own_test_call_only(setup):
    s = setup
    s.app.judge = object()                                     # judge demo: one shared practice copy
    _, page = s.get("/settings")
    assert "Judge demo: pick a voice on the Test my alert form" in page and 'id="call-voice"' not in page
    assert 'id="test-voice"' in page
    s.post("/act", token=s.app.issue_nonce("-", "-", "voice:set"), call_voice="Google.en-US-Chirp3-HD-Leda")
    assert "call_voice" not in json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())
