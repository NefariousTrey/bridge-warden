"""'Hear the call' browser demo (Trey, 2026-10-26): public page, no login, nothing sent anywhere, microphone only
here and only if ticked, the same words as the phone call (node runs static/call-demo.js against the Python
TwiML), and the credit line in the footer. Offline only."""
import html
import json
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest

from test_v4_ui import setup  # noqa: F401  (fixture)
from bridge_warden import judge, web
from bridge_warden import notify as N

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "bridge_warden" / "static" / "call-demo.js"
B = "https://demo.example.workers.dev"
NODE = shutil.which("node")
CREDIT = "Made by @Nefarious_Trey,<br>with Grok."


def test_hear_page_is_public_and_locked_down(setup):
    r, body = setup.req("GET", "/hear")                         # no cookie
    assert r.status == 200 and "Demo. Nothing happens to your money." in body
    assert "No phone number needed" in body
    csp = r.getheader("Content-Security-Policy")
    h = web.demo_js()[1]
    assert f"script-src '{h}'" in csp and "connect-src 'none'" in csp and "unsafe-inline" not in csp
    assert "form-action 'none'" in csp and web.SCRIPT_HASH not in csp
    assert r.getheader("Permissions-Policy") == "camera=(), microphone=(self), geolocation=(), payment=()"
    assert f'<script src="/hear.js" integrity="{h}"></script>' in body
    assert "<script>" not in body                                # no inline script; JSON data block only
    assert not re.search(r'(src|href)="https?://', body)
    js_r, js = setup.req("GET", "/hear.js")
    assert js_r.status == 200 and js == JS.read_text() and "javascript" in js_r.getheader("Content-Type")


def test_microphone_stays_off_everywhere_else(setup):
    r, _ = setup.get("/")
    assert "microphone=()" in r.getheader("Permissions-Policy")


def test_demo_data_is_the_call_data():
    body = web.hear_page()
    raw = re.search(r'id="bw-call-data">(.*?)</script>', body, re.S).group(1)
    assert "<" not in raw and json.loads(raw) == json.loads(json.dumps(N.call_demo_data()))
    for k in N.SITUATIONS:
        assert f'<option value="{k}">' in body


def test_demo_script_sends_nothing_and_mic_is_opt_in():
    js = JS.read_text()
    for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "localStorage", "http://",
                "https://", "eval(", "innerHTML", "new Function"):
        assert bad not in js, bad
    assert 'if (!$("call-mic-ok").checked)' in js                 # the mic needs the box ticked first
    assert "localService" in js                                    # on-device voice first


def test_links_and_credit_in_footer(setup):
    _, s = setup.get("/settings")
    assert 'href="/hear"' in s and CREDIT in s
    _, home = setup.get("/")
    assert CREDIT in home
    assert 'href="/hear"' in web.judge_landing() and CREDIT in web.judge_landing() and CREDIT in web.hear_page()


@pytest.fixture
def jsrv(monkeypatch):
    for k in judge.OWNER_SECRET_ENV:
        monkeypatch.delenv(k, raising=False)
    srv, j = judge.serve_judge(0, public_host="bw-demo.onrender.com", bind="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    judge.cleanup(j)


def test_hear_works_in_judge_mode_without_login(jsrv):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", jsrv.server_address[1], timeout=5)
    c.request("GET", "/hear", headers={"Host": "bw-demo.onrender.com"})
    r = c.getresponse()
    assert r.status == 200 and "Demo. Nothing happens to your money." in r.read().decode()


# ---------------------------------------------------------------- same words as the phone call
def _phone(test, kind, inputs):
    """Run one call through the real TwiML functions. Returns every spoken line, in order."""
    demo = bool(test)
    x = N.voice_twiml(B, test, demo, kind)
    said = [html.unescape(m) for m in re.findall(r'<Say voice="man">(.*?)</Say>', x)]
    for d, s in inputs:
        if "<Hangup/>" in x:
            break
        act = html.unescape(re.search(r'<Gather [^>]*action="([^"]+)"', x).group(1))
        u = urllib.parse.urlparse(act)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
        t, n, k = q["t"] == "1", int(q.get("n", 1)), q.get("k", "unauthorized")
        if u.path == "/gather":
            x = N.gather_twiml(B, t, n, d, s, None, k)
        elif u.path == "/other":
            x = N.other_twiml(B, t, n, s, None, k)
        else:
            x = N.walk_twiml(B, t, k, q["i"], q["a"], q["x"], d, s)
        said += [html.unescape(m) for m in re.findall(r'<Say voice="man">(.*?)</Say>', x)]
    return said


RUNS = [
    (True, "unauthorized", [["1", ""]] + [["1", ""]] * 7),
    (True, "takeover", [["", "the second one"], ["", "repeat"], ["", "banana"], ["", "banana"], ["3", ""],
                        ["", "done"], ["", ""], ["", ""]]),
    (True, "phishing", [["4", ""], ["", "what is this"], ["1", ""], ["", "skip"], ["", "okay"], ["1", ""], ["1", ""]]),
    (True, "limited", [["", ""], ["", ""]]),
    (False, "scam_buy", [["2", ""]] + [["", "finished"]] * 6),
    (False, "risky_sell", [["3", ""]]),
    (False, "limited", [["", "banana"], ["4", ""], ["", "what now"]]),
    (False, "takeover", [["4", ""], ["", "it was me"]]),
    (False, "fraud", [["1", ""], ["", ""], ["", ""]]),
]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_browser_demo_says_exactly_what_the_phone_says():
    probe = """const {engine} = require(%s); const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = [];
for (const [test, kind, inputs] of D.runs) {
  const E = engine(D.data); let r = E.start(test, kind, test); let said = r.say.slice(); let st = r.st;
  for (const [d, s] of inputs) { if (st.stage === 'ended') break; r = E.answer(st, d, s); said = said.concat(r.say); st = r.st; }
  out.push(said);
}
console.log(JSON.stringify(out));"""
    feed = json.dumps({"data": N.call_demo_data(), "runs": RUNS})
    r = subprocess.run([NODE, "-e", probe % json.dumps(str(JS))], input=feed, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    js = json.loads(r.stdout)
    for (test, kind, inputs), got in zip(RUNS, js):
        assert got == _phone(test, kind, inputs), (test, kind)
    assert N.TEST_JUST in js[0] and N.WALK["summary_lead"] in js[0] and N.SAFE_END == js[0][-1]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_browser_match_choice_uses_the_shared_vectors():
    v = json.loads((ROOT / "call-worker" / "test" / "vectors.json").read_text())
    probe = """const {engine} = require(%s); const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const E = engine(D.data);
console.log(JSON.stringify([D.cases.map(c => E.matchChoice(c.digits, c.speech)),
  D.walk.map(c => E.walkChoice(c.digits, c.speech))]));"""
    feed = json.dumps({"data": N.call_demo_data(), "cases": v["cases"], "walk": v["walk_cases"]})
    r = subprocess.run([NODE, "-e", probe % json.dumps(str(JS))], input=feed, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    a, b = json.loads(r.stdout)
    assert a == [c["want"] for c in v["cases"]] and b == [c["want"] for c in v["walk_cases"]]
