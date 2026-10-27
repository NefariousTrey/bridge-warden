"""LINKTOKEN 2026-10-26: Twilio's trial proxy fetched /voice with NO X-Twilio-Signature (Workers Logs:
how "no-signature", ua Java-http-client), so the Url carries a short-lived HMAC link. Python must match the Worker."""
import json
import subprocess
import urllib.parse
from pathlib import Path

from bridge_warden import notify as N

WORKER = Path(__file__).resolve().parent.parent / "call-worker"
KEY = "link-key-test-0123456789abcdef"


def test_shared_vector_matches_worker():
    m = N.link_message("/voice", "t=1&n=1&nm=Trey&e=2000000000&hop=1", "+15550001111", "ACtest")
    assert m == "bw-link-v1\n/voice\ne=2000000000&n=1&nm=Trey&t=1\n+15550001111\nACtest"
    u = N.sign_link("https://w.example/voice?t=1&n=1&nm=Trey", KEY, "+15550001111", "ACtest", now=2000000000 - 600)
    assert u.endswith("&s=G8Nw1IGRYFdkSKU6WzWXT0zG-8eH5rsZf18ljrlST-M") and "e=2000000000" in u


def test_ttl_is_short_and_capped():
    u = N.sign_link("https://w.example/voice?t=1&n=1", KEY, "+1", "AC", now=1000, ttl=99999)
    assert "e=%d" % (1000 + N.LINK_MAX_SECONDS) in u
    assert "e=1060" in N.sign_link("https://w.example/voice?t=1&n=1", KEY, "+1", "AC", now=1000, ttl=1)


def test_worker_accepts_python_link_and_rejects_changes():
    import time
    u = N.sign_link("https://bridge-warden-call.example.workers.dev/voice?t=1&n=1&nm=Mary-Jo%20O%27Neil", KEY,
                    "+15550001111", "ACtest", now=time.time())
    probe = ("import w from './src/index.js'; const env={TWILIO_AUTH_TOKEN:'x',CALL_LINK_KEY:%s}; "
             "const P={AccountSid:'ACtest',To:'+15550001111'}; const go=(u,p)=>w.fetch(new Request(u,{method:'POST',"
             "body:new URLSearchParams(p)}),env); const a=await go(%s,P); const t=await a.text(); "
             "const b=await go(%s,{...P,To:'+1555'}); console.log(JSON.stringify([a.status,t.includes(\"Hello Mary-Jo O'Neil\"),b.status]));"
             ) % (json.dumps(KEY), json.dumps(u), json.dumps(u))
    out = subprocess.run(["node", "--input-type=module", "-e", probe], cwd=WORKER, capture_output=True, text=True,
                         timeout=60)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [200, True, 403], out.stderr[-400:]


def test_adapter_signs_url_only_when_key_set():
    sent = []
    env = {"TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM_NUMBER": "+15550002222",
           "BW_OWNER_PHONE": "+15550001111", "BW_CALL_URL": "https://w.example"}
    def fake(method, url, headers, body, timeout, extra_host=None):
        sent.append(dict(urllib.parse.parse_qsl(body.decode())))
        return 201, {}, b"{}"
    for extra in ({}, {"BW_CALL_LINK_KEY": KEY}):
        a = N.TwilioCallAdapter(env={**env, **extra}, sender=fake)
        assert a.ready and a.place_call(N.TEST_NOTICE, name="Trey")["dialed"]
    assert "s=" not in sent[0]["Url"] and "&s=" in sent[1]["Url"] and "nm=Trey" in sent[1]["Url"]
    assert KEY not in json.dumps(sent)
