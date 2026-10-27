"""TESTGREET 2026-10-26 (Trey): TEST calls say "Hello <name typed on the test form>, this is Bridge Warden." or
"Hello, this is Bridge Warden." They never fall back to the owner's preferred_name, so judges never hear "Trey".
Real alerts keep "Hi <preferred name>". The typed name is never logged or stored. Offline only: fake transports."""
import json
import urllib.parse

import pytest

from test_v4_alert_test import ENV, SECRETS, Timers, drill, recs  # noqa: F401
from test_v4_ui import setup, token  # noqa: F401  (fixture)
from bridge_warden import notify as N

B = "https://bridge-warden-call.example.workers.dev"
REST = " Fraud was detected on your PayPal account. Nothing was sent."
BAD = ['</Say><Play>http://evil.example/x.mp3</Play><Say>', '<speak>x</speak>', "Sam & Co", 'Sam"', "Sam\nX",
       "S\u00e1m", "1Sam", "-Sam", "A" * 41, "Sam;Drop", "]]><Hangup/>", "   "]
TWILIO = {"call_on_fraud": {"enabled": True, "provider": "twilio", "experimental": True}}


def run(gate, call_name="", env=ENV, **kw):
    gate.engine.p["notify"] = TWILIO
    gate.engine.p["preferred_name"] = "Trey"
    sent = []
    d, t, _ = drill(gate, env=env, sender=lambda *a, **k: sent.append(a) or (201, {}, b""))
    assert d.start(call_name=call_name)["started"]
    t.made[0][1]()
    return urllib.parse.parse_qs(sent[0][3].decode()), d


# ---------------------------------------------------------------- the words
def test_greeting_rule():
    assert N.call_open("Sam", test=True) == "Hello Sam, this is Bridge Warden." + REST
    assert N.call_open("", test=True) == "Hello, this is Bridge Warden." + REST
    assert N.call_open("Trey") == "Hi Trey, this is Bridge Warden." + REST                # real alert unchanged
    assert N.call_lines("x", True, name="Sam")[0].startswith("Hello Sam, this is Bridge Warden.")
    assert N.call_lines("x", True)[0].startswith("Hello, this is Bridge Warden.")
    assert N.call_lines("x", True)[-1] == N.TEST_NOTICE                                     # same test message
    assert N.call_lines("x", False, name="Trey")[0].startswith("Hi Trey,")
    assert '>Hello Sam, this is Bridge Warden. Fraud' in N.voice_twiml(B, True, name="Sam")
    assert '>Hi Trey, this is Bridge Warden. Fraud' in N.voice_twiml(B, False, name="Trey")


# ---------------------------------------------------------------- drill: name present / blank / bad
def test_drill_with_name_says_hello_name_worker_url(gate):
    b, _ = run(gate, "Mary-Jo O'Neil", env={**ENV, "BW_CALL_URL": B})
    assert b["Url"][0] == B + "/voice?t=1&n=1&nm=Mary-Jo%20O%27Neil"
    b, _ = run(gate, "Sam")
    assert '<Say voice="man">Hello Sam, this is Bridge Warden.</Say>' in b["Twiml"][0] and "Trey" not in b["Twiml"][0]


def test_drill_blank_says_hello_and_never_owner_name(gate):
    b, _ = run(gate, "")
    assert '<Say voice="man">Hello, this is Bridge Warden.</Say>' in b["Twiml"][0] and "Trey" not in b["Twiml"][0]
    b, _ = run(gate, "", env={**ENV, "BW_CALL_URL": B})
    assert b["Url"][0] == B + "/voice?t=1&n=1"                                             # no nm=Trey


@pytest.mark.parametrize("bad", BAD, ids=range(len(BAD)))
def test_drill_bad_name_gives_plain_hello(gate, bad):
    b, _ = run(gate, bad)
    x = b["Twiml"][0]
    assert '<Say voice="man">Hello, this is Bridge Warden.</Say>' in x
    for w in ("<Play", "<speak", "<Hangup", "evil", "Drop", "Trey"):
        assert w not in x
    b, _ = run(gate, bad, env={**ENV, "BW_CALL_URL": B})
    assert b["Url"][0] == B + "/voice?t=1&n=1"


def test_typed_name_never_logged_or_stored(gate):
    b, d = run(gate, "Zebulon")
    raw = gate.audit.path.read_text(encoding="utf-8")
    assert "Zebulon" not in raw and "Zebulon" not in json.dumps(vars(d), default=str)
    assert not any(s in raw for s in SECRETS)


# ---------------------------------------------------------------- the web form
def test_form_field_and_post(setup, monkeypatch):
    s = setup
    got = []
    monkeypatch.setattr(N.DryRunCallAdapter, "place_call",
                        lambda self, text, name="": got.append((text, name)) or {"dialed": False}, raising=False)
    s.app.alert_test.timer = t = Timers()
    s.gate.engine.p["preferred_name"] = "Trey"
    _, page = s.get("/settings")
    assert 'id="call-name"' in page and 'name="call_name"' in page and 'maxlength="40"' in page
    assert "What should the call call you?" in page
    s.post("/act", token=token(page, "Test my alert"), call_name="Zebulon")
    t.made[-1][1]()
    assert got[-1][0].startswith("Hello Zebulon, this is Bridge Warden.") and got[-1][1] == "Zebulon"
    raw = s.gate.audit.path.read_text(encoding="utf-8")
    assert "Zebulon" not in raw and "Zebulon" not in s.get("/")[1] and "Zebulon" not in s.get("/settings")[1]


def test_form_blank_and_hostile_post(setup, monkeypatch):
    s = setup
    got = []
    monkeypatch.setattr(N.DryRunCallAdapter, "place_call",
                        lambda self, text, name="": got.append((text, name)) or {"dialed": False}, raising=False)
    s.gate.engine.p["preferred_name"] = "Trey"
    s.app.alert_test.timer = t = Timers()
    s.post("/act", token=token(s.get("/settings")[1], "Test my alert"), call_name='"><script>x</script>')
    t.made[-1][1]()
    assert got[-1][0].startswith("Hello, this is Bridge Warden.") and got[-1][1] == "" and "Trey" not in got[-1][0]
    assert "<script>x" not in s.gate.audit.path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- Charon voice (Trey, Oct 26): allowed, free fallback kept
def test_charon_voice_allowed_and_free_fallback_kept():
    import shutil
    import subprocess
    from pathlib import Path
    v = "Google.en-US-Chirp3-HD-Charon"
    assert N.voice_of(v) == v and N.voice_of("Google.evil<x>") == N.FREE_VOICE == "man" and N.voice_of("") == "man"
    x = N.apply_voice(N.voice_twiml(B, True), v)
    assert f'<Say voice="{v}" language="en-US">Hello, this is Bridge Warden.' in x and 'voice="man"' not in x
    node = shutil.which("node")
    if node:
        probe = ("import {voiceOf} from './src/index.js'; console.log(JSON.stringify([voiceOf({CALL_VOICE:%r}), "
                 "voiceOf({CALL_VOICE:'Google.x<y>'}), voiceOf({})]));" % v)
        r = subprocess.run([node, "--input-type=module", "-e", probe], capture_output=True, text=True, timeout=60,
                           cwd=Path(__file__).resolve().parent.parent / "call-worker", encoding="utf-8")
        assert json.loads(r.stdout) == [v, "man", "man"], r.stderr[-400:]
