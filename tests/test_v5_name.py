"""v5: the alert call greets the owner by preferred name ("Hi Trey, this is Bridge Warden.") so it does not
sound like spam. No name = "Hi, this is Bridge Warden." Hostile names never reach the TwiML.
Offline only: fake transports, no real call, no deploy, no network."""
import json
import shutil
import subprocess
import urllib.parse

import pytest

from test_v4_alert_test import ENV, SECRETS, drill, recs  # noqa: F401
from test_v4_dots import ro  # noqa: F401  (fixture: view-only run)
from test_v4_ui import BASE, setup, token  # noqa: F401  (fixture)
from bridge_warden import controls as C
from bridge_warden import notify as N
from bridge_warden.policy import PolicyError, validate

B = "https://bridge-warden-call.example.workers.dev"
HOSTILE = ['</Say><Play>http://evil.example/x.mp3</Play><Say>', '<speak><break time="9s"/></speak>',
           "Trey & Co", 'Trey"', "Trey\nX", "Tr\u00e9y", "1Trey", "-Trey", "A" * 41, "Trey;Drop", "Trey\tX",
           "]]><Hangup/>", "&lt;Hangup/&gt;", "   ", "", None]


def sent_body(fn):
    sent = []

    def fake(method, url, headers, body, timeout, extra_host=None):
        sent.append(body.decode())
        return 201, {}, b"{}"
    fn(fake)
    return urllib.parse.parse_qs(sent[0])


# ---------------------------------------------------------------- the rule
def test_name_present_greets_by_name():
    assert N.clean_name("Trey") == "Trey"
    assert N.clean_name("  Mary-Jo   O'Neil ") == "Mary-Jo O'Neil"
    assert N.call_open("Trey") == "Hi Trey, this is Bridge Warden. Fraud was detected on your PayPal account. Nothing was sent."
    x = N.voice_twiml(B, False, name="Trey")
    assert '<Say voice="man">Hi Trey, this is Bridge Warden. Fraud was detected' in x
    assert N.call_lines("x", False, name="Trey")[0].startswith("Hi Trey, this is Bridge Warden.")
    assert N.clean_name("A" * 40) == "A" * 40


def test_name_missing_uses_plain_greeting():
    assert N.CALL_OPEN == "Hi, this is Bridge Warden. Fraud was detected on your PayPal account. Nothing was sent."
    assert N.call_open("") == N.call_open(None) == N.CALL_OPEN
    assert '<Say voice="man">Hi, this is Bridge Warden. Fraud' in N.voice_twiml(B, False)
    assert "&nm=" not in N.call_url(B, "voice", True) and N.call_lines("x", False)[0] == N.CALL_OPEN


@pytest.mark.parametrize("bad", HOSTILE, ids=range(len(HOSTILE)))
def test_hostile_name_never_reaches_twiml_or_url(bad):
    assert N.clean_name(bad) == ""
    x = N.voice_twiml(B, False, name=bad)
    assert ">Hi, this is Bridge Warden." in x
    for w in ("<Play", "<speak", "<break", "<Hangup", "evil", "Drop", "&amp;lt;"):
        assert w not in x
    assert "&nm=" not in N.call_url(B, "voice", True, name=bad)
    assert N.call_lines("x", False, name=bad)[0] == N.CALL_OPEN


def test_name_only_on_voice_step_and_url_encoded():
    assert N.call_url(B, "voice", True, name="Mary-Jo O'Neil").endswith("/voice?t=1&n=1&nm=Mary-Jo%20O%27Neil")
    assert "nm=" not in N.call_url(B, "gather", True, name="Trey")         # only the first step greets
    assert N.call_url(B, "voice", False, 1, "limited", "Trey").endswith("?t=0&n=1&k=limited&nm=Trey")


def test_demo_inbound_never_uses_a_name():
    assert ">Hello, this is Bridge Warden." in N.voice_twiml(B, False, True, name="Trey")   # demo = test greeting


def test_name_never_picks_the_situation():
    sell = sent_body(lambda f: N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": B}, sender=f).place_call(
        " ".join(N.call_lines("x", True, name="Sell")), name="Sell"))
    assert sell["Url"][0] == B + "/voice?t=1&n=1&nm=Sell"                  # not &k=risky_sell


# ---------------------------------------------------------------- the call (fake Twilio)
def test_twilio_worker_url_carries_name_and_twiml_fallback_says_it():
    w = sent_body(lambda f: N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": B}, sender=f).place_call(
        " ".join(N.call_lines("x", True, name="Trey")), name="Trey"))
    assert w["Url"][0] == B + "/voice?t=1&n=1&nm=Trey" and "Twiml" not in w
    t = sent_body(lambda f: N.TwilioCallAdapter(env=ENV, sender=f).place_call(
        " ".join(N.call_lines("x", True, name="Trey")), name="Trey"))
    assert '<Say voice="man">Hello Trey, this is Bridge Warden.</Say>' in t["Twiml"][0]
    h = sent_body(lambda f: N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": B}, sender=f).place_call(
        " ".join(N.call_lines("x", True)), name="</Say><Hangup/>"))
    assert h["Url"][0] == B + "/voice?t=1&n=1"


def test_drill_never_uses_owner_preferred_name(gate):
    """TESTGREET: a test call never falls back to the owner's preferred_name (judges never hear "Trey")."""
    gate.engine.p["notify"] = {"call_on_fraud": {"enabled": True, "provider": "twilio", "experimental": True}}
    gate.engine.p["preferred_name"] = "Trey"
    sent = []
    d, t, _ = drill(gate, env=ENV, sender=lambda *a, **k: sent.append(a) or (201, {}, b""))
    d.start()
    t.made[0][1]()
    body = sent[0][3].decode()
    assert "Hello%2C+this+is+Bridge+Warden." in body and "Trey" not in body
    assert not any(x in json.dumps(recs(gate, "alert_test_call")[-1]) for x in SECRETS)
    d2, _, _ = drill(gate, name_fn=lambda: "<b>Bad</b>")
    assert d2.preferred_name() == ""


def test_real_alert_notifier_uses_policy_name(gate, monkeypatch):
    got = []

    class Fake(N.DryRunCallAdapter):
        def place_call(self, text, name=""):
            got.append((text, name))
            return {"dialed": False}
    gate.engine.p["preferred_name"] = "Trey"
    n = N.Notifier(gate)
    n.caller = Fake()
    monkeypatch.setattr(N.dashboard, "status", lambda g, _s=iter([
        {"waiting": 0, "blocked": 0, "seq": 1, "state": "green"},
        {"waiting": 0, "blocked": 1, "seq": 2, "state": "red"}]): next(_s))
    n.check()
    n.check()
    assert got and got[0][1] == "Trey" and got[0][0].startswith("Hi Trey, this is Bridge Warden.")


# ---------------------------------------------------------------- policy + settings
def test_policy_accepts_good_names_and_rejects_hostile_ones():
    base = json.loads(json.dumps(BASE))
    for ok in ("", "Trey", "Mary-Jo O'Neil", "A" * 40):
        validate({**base, "preferred_name": ok})
    for bad in [h for h in HOSTILE if h not in ("", None)] + [" Trey", "Trey ", "Mary  Jo", 7]:
        with pytest.raises(PolicyError):
            validate({**base, "preferred_name": bad})


def test_set_preferred_name_writes_backs_up_and_logs_without_the_name(setup):
    s = setup
    r = C.set_preferred_name(s.pf, "  Trey ", s.gate.audit)
    assert r["status"] == "changed" and json.loads(s.pf.read_text())["preferred_name"] == "Trey"
    assert C.set_preferred_name(s.pf, "Trey", s.gate.audit)["status"] == "no_change"
    ev = [x for x in s.gate.audit.records() if x["event"] == "preferred_name_changed"]
    assert ev and "Trey" not in json.dumps(ev)
    with pytest.raises(PolicyError):
        C.set_preferred_name(s.pf, "</Say>", s.gate.audit)
    assert json.loads(s.pf.read_text())["preferred_name"] == "Trey"


def test_settings_page_saves_name_and_test_call_uses_it(setup):
    s = setup
    _, page = s.get("/settings")
    assert 'id="preferred-name"' in page and 'maxlength="40"' in page and "Hi, this is Bridge Warden." in page
    s.post("/act", token=token(page, "preferred-name"), preferred_name="Trey")
    _, page = s.get("/settings")
    assert "Saved. Calls will say: Hi Trey, this is Bridge Warden." in page and 'value="Trey"' in page
    assert json.loads(s.pf.read_text())["preferred_name"] == "Trey" and s.app.preferred_name() == "Trey"
    assert "Test calls never use it" in page                              # TESTGREET: test calls ignore it


def test_settings_refuses_hostile_name_and_keeps_old_one(setup):
    s = setup
    s.post("/act", token=token(s.get("/settings")[1], "preferred-name"), preferred_name="Trey")
    before = s.pf.read_bytes()
    s.post("/act", token=token(s.get("/settings")[1], "preferred-name"), preferred_name='"><script>x</script>')
    _, page = s.get("/settings")
    assert "Use letters, spaces, hyphens or apostrophes (up to 40). Nothing changed." in page
    assert s.pf.read_bytes() == before and "<script>x" not in page
    s.post("/act", token=token(page, "preferred-name"), preferred_name="")
    assert json.loads(s.pf.read_text())["preferred_name"] == "" and s.app.preferred_name() == ""


def test_view_only_run_keeps_name_for_the_session(ro):
    before = ro.pf.read_bytes()
    ro.post("/act", token=token(ro.get("/settings")[1], "preferred-name"), preferred_name="Trey")
    assert ro.pf.read_bytes() == before and ro.app.preferred_name() == "Trey"
    assert "this session only" in ro.get("/settings")[1]


# ---------------------------------------------------------------- Worker parity (node)
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_worker_greeting_matches_python():
    from pathlib import Path
    names = ["Trey", "Mary-Jo O'Neil", "", "  Trey  ", "Mary   Jo"] + [h for h in HOSTILE if h is not None]
    probe = ("import {voiceTwiml, cleanName} from './src/index.js'; const N=%s; "
             "console.log(JSON.stringify(N.map(n=>[cleanName(n), voiceTwiml(%r,true,false,'unauthorized',n), voiceTwiml(%r,false,false,'unauthorized',n)])));")
    r = subprocess.run([NODE, "--input-type=module", "-e", probe % (json.dumps(names), B, B)],
                       cwd=Path(__file__).resolve().parent.parent / "call-worker", capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert json.loads(r.stdout) == [[N.clean_name(n), N.voice_twiml(B, True, name=n), N.voice_twiml(B, False, name=n)]
                                       for n in names]
