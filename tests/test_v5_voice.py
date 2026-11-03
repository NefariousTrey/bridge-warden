"""VOICE 2026-10-26: the call voice is a setting. Default = Twilio's free "man" voice; natural voices opt-in."""
import json
import os
import shutil
import subprocess

import pytest

from bridge_warden import notify as N

B = "https://bw.example.workers.dev"


def test_default_is_free_voice():
    assert N.voice_of("") == "man" and N.voice_of(None) == "man"
    x = N.voice_twiml(B, True)
    assert N.apply_voice(x, "") == x and N.apply_voice(x, "man") == x


@pytest.mark.parametrize("v", ["Google.en-US-Chirp3-HD-Leda", "Google.en-US-Chirp3-HD-Kore", "Google.en-US-Chirp3-HD-Fenrir",
                               "Google.en-US-Chirp3-HD-Aoede", "woman"])
def test_known_voices(v):
    assert N.voice_of(v) == v


@pytest.mark.parametrize("v", ['Google.en-US-Chirp3-HD-Leda" x="1', "Google.<b>", "ElevenLabs.x", "google.en-US-Chirp3-HD-Leda",
                               "Google.en-US-Neural2-F", "Google.en-US-Standard-C", "x" * 200])
def test_bad_voices_fall_back(v):
    assert N.voice_of(v) == "man"


def test_natural_voice_keeps_words():
    x = N.voice_twiml(B, True)
    j = N.apply_voice(x, "Google.en-US-Chirp3-HD-Leda")
    assert 'voice="man"' not in j and j.count("<Say ") == x.count("<Say ")
    assert j.replace(' voice="Google.en-US-Chirp3-HD-Leda" language="en-US"', ' voice="man"') == x


def test_adapter_inline_twiml_uses_setting():
    sent = []

    def fake(method, url, headers, body, timeout, extra_host=None):
        sent.append(body.decode())
        return 201, {}, b"{}"
    env = {"TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+15550002222",
           "TWILIO_TO": "+15550001111"}
    env = {k: env[k] for k in env}
    keys = dict(zip(N.TWILIO_ENV, (env["TWILIO_ACCOUNT_SID"], "t", "+15550002222", "+15550001111")))
    for voice, want in (("", 'voice%3D%22man%22'), ("Google.en-US-Chirp3-HD-Leda", 'voice%3D%22Google.en-US-Chirp3-HD-Leda%22')):
        a = N.TwilioCallAdapter(env={**keys, "BW_CALL_VOICE": voice}, sender=fake)
        assert a.place_call("Hi, this is Bridge Warden. Test.")["dialed"]
        assert want in sent[-1]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_worker_voice_tests_pass():
    here = os.path.join(os.path.dirname(__file__), "..", "call-worker")
    r = subprocess.run(["node", "test/test_worker.mjs"], cwd=here, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 0 and "voice tests ok" in r.stdout
