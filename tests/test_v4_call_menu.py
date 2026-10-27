"""Press-or-say phone menu (CALL_SCRIPT_v3, 2026-10-26): digit + speech mapping, option 4 ('other'),
repeat-once, safe end, Worker parity, robots.txt. Offline only: no call, no tunnel, no deploy, no network."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_v4_alert_test import ENV
from test_v4_ui import setup  # noqa: F401  (fixture)
from bridge_warden import notify as N
from bridge_warden.web import AI_BOTS, HEADERS, ROBOTS_TXT

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "call-worker"
_V = json.loads((WORKER / "test" / "vectors.json").read_text())
VECTORS, WALK_VECTORS = _V["cases"], _V["walk_cases"]
B = "https://bridge-warden-call.example.workers.dev"


@pytest.mark.parametrize("c", VECTORS, ids=lambda c: f"{c['digits'] or '-'}|{c['speech'] or '-'}")
def test_digit_and_speech_mapping(c):
    assert N.match_choice(c["digits"], c["speech"]) == c["want"]


def test_menu_words_press_or_say_and_option_4_never_a_human():
    m = N.CALL_MENU
    for k in ("Press or say 1", "Press or say 2", "Press or say 3", "Press 4 or say other."):
        assert k in m
    every = " ".join([m, N.OTHER_ASK, N.OTHER_FALLBACK, N.NOT_HEARD, N.NO_CHOICE]
                     + sum(N.CALL_REPLIES.values(), [])).lower()
    for w in ("agent", "person", "human", "someone", "transfer", "connecting you"):
        assert w not in every
    for w in ("agent", "person", "someone"):
        assert N.match_choice(None, w) is None                 # these words never mean option 4


def test_voice_twiml_gathers_dtmf_and_speech():
    x = N.voice_twiml(B, True)
    assert x.startswith("<Response>") and N.call_open("", test=True) in x and N.CALL_ADVICE in x
    assert '<Gather input="dtmf speech" numDigits="1"' in x and f'hints="{N.HINTS}"' in x
    assert f'action="{B}/gather?t=1&amp;n=1"' in x and "<Redirect" in x


@pytest.mark.parametrize("d", ["1", "2", "3"])
def test_test_call_any_choice_says_just_a_test_then_walks(d):
    x = N.gather_twiml(B, True, 1, d, "")
    assert x.index(N.TEST_JUST) < x.index(N.IF_REAL) < x.index("Step 1 of 7")
    assert N.WALK["prompt"] in x and f'hints="{N.WALK_HINTS}"' in x
    assert f'action="{B}/walk?t=1&amp;k=unauthorized&amp;i=0&amp;a=&amp;x=0"' in x


@pytest.mark.parametrize("d", ["1", "2"])
def test_real_call_1_and_2_walk_without_test_line(d):
    x = N.gather_twiml(B, False, 1, d, "")
    assert N.CALL_REPLIES[d][0] in x and N.WALK["lead_real"] in x and "Step 1 of" in x
    assert N.SAFE_END not in x and N.TEST_JUST not in x and "/walk?t=0" in x


def test_real_call_3_thanks_and_ends():
    x = N.gather_twiml(B, False, 1, "3", "")
    assert all(line in x for line in N.CALL_REPLIES["3"]) and x.endswith("<Hangup/></Response>")
    assert N.SAFE_END not in x


def test_option_4_asks_what_they_need_with_one_speech_gather():
    for how in (("4", ""), ("", "Four."), ("", "other"), ("", "something else")):
        x = N.gather_twiml(B, True, 1, *how)
        assert N.OTHER_ASK in x and 'input="speech"' in x and x.count("<Gather") == 1
        assert f"{B}/other?t=1&amp;n=1" in x


def test_option_4_answer_offline_ai_and_never_a_human():
    class AI:
        def __init__(self, text):
            self.text, self.seen = text, []

        def advise(self, ctx, q):
            self.seen.append((ctx, q))
            return {"text": self.text}
    t = N.other_twiml(B, True, 1, "what is going on", AI("x"))                 # test: always the walk, no AI
    assert N.TEST_JUST in t and "Step 1 of" in t
    x = N.other_twiml(B, False, 1, "what is going on", None)                    # offline: explain + menu again
    assert N.OTHER_FALLBACK in x and N.CALL_MENU in x and "/gather?t=0&amp;n=2" in x
    assert N.CALL_REPLIES["2"][0] in N.other_twiml(B, False, 1, "I want to report it")
    ok = AI("Open PayPal yourself and check your recent activity.")
    y = N.other_twiml(B, False, 1, "what is going on", ok)
    assert "Open PayPal yourself" in y and N.CALL_MENU in y
    ctx, q = ok.seen[0]
    assert "Never say a human" in q
    z = N.other_twiml(B, False, 1, "what is going on", AI("A person will help you now."))
    assert "person" not in z and N.OTHER_FALLBACK in z                         # human claim dropped
    last = N.other_twiml(B, False, 2, "what is going on", ok)
    assert "<Gather" not in last and N.SAFE_END not in last


def test_unclear_speech_uses_ai_only_for_1_to_4_and_survives_ai_errors():
    class AI:
        def __init__(self, text):
            self.text = text

        def advise(self, ctx, q):
            if self.text is None:
                raise OSError("down")
            return {"text": self.text}
    assert N.pick_choice(None, "the middle choice please", AI("2")) == "2"
    assert N.pick_choice(None, "the middle choice please", AI("7")) is None
    assert N.pick_choice(None, "the middle choice please", AI(None)) is None
    assert N.pick_choice("3", "", AI("1")) == "3"                              # keypad wins, no AI call


def test_unknown_repeats_menu_once_then_ends_safely():
    a = N.gather_twiml(B, False, 1, "", "banana")
    assert N.NOT_HEARD in a and N.CALL_MENU in a and "/gather?t=0&amp;n=2" in a
    b = N.gather_twiml(B, False, 2, "", "banana")
    assert "<Gather" not in b and N.NO_CHOICE in b and N.SAFE_END not in b
    assert N.gather_twiml(B, False, 1, "9", "") == a
    t = N.gather_twiml(B, True, 1, "", "")                                    # test call, silence: menu once
    assert N.CALL_MENU in t and "/gather?t=1&amp;n=2" in t
    e = N.gather_twiml(B, True, 2, "", "")
    assert N.NO_CHOICE in e and N.TEST_JUST in e and e.endswith(f"{N.SAFE_END}</Say><Hangup/></Response>")


def test_call_base_https_only():
    assert N.call_base(B + "/") == B
    for bad in ("http://x.workers.dev", "https://x.dev/?k=secret", "", "javascript:x", "https://a b"):
        assert N.call_base(bad) == ""


def test_twilio_uses_worker_url_when_set_and_twiml_when_not():
    sent = []

    def fake(method, url, headers, body, timeout, extra_host=None):
        sent.append(body.decode())
        return 201, {}, b"{}"
    N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": B}, sender=fake).place_call(" ".join(N.call_lines("x", True)))
    assert "Url=https%3A%2F%2Fbridge-warden-call.example.workers.dev%2Fvoice%3Ft%3D1%26n%3D1" in sent[0]
    assert "Twiml=" not in sent[0]
    N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": "http://insecure"}, sender=fake).place_call("Hi.")
    assert "Twiml=" in sent[1] and "Url=" not in sent[1]


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_worker_matches_python_twiml_and_passes_its_own_tests():
    r = subprocess.run([NODE, "test/test_worker.mjs"], cwd=WORKER, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    probe = """import {voiceTwiml, gatherTwiml, otherTwiml, walkTwiml} from './src/index.js';
const B=%r; const out=[voiceTwiml(B,true), voiceTwiml(B,false), voiceTwiml(B,false,true),
  voiceTwiml(B,true,false,'limited')];
for (const t of [true,false]) {
  for (const [d,s,n,k] of %s) out.push(await gatherTwiml(B,t,n,d,s,null,k));
  for (const [s,n,k] of %s) out.push(await otherTwiml(B,t,n,s,null,k));
  for (const [k,i,a,x,d,s] of %s) out.push(walkTwiml(B,t,k,i,a,x,d,s));
}
console.log(JSON.stringify(out));"""
    g = [["1", "", 1, "unauthorized"], ["2", "", 1, "takeover"], ["3", "", 1, "phishing"], ["4", "", 1, "x"],
         ["", "other", 1, "limited"], ["", "banana", 1, "scam_buy"], ["", "", 2, "risky_sell"],
         ["", "It was me.", 1, "fraud"], ["", "the second one", 1, "login"], ["", "", 1, "unauthorized"]]
    o = [["what now", 1, "unauthorized"], ["report it", 1, "limited"], ["", 2, "phishing"], ["it was me", 1, "x"]]
    w = [["takeover", "0", "", "0", "1", ""], ["takeover", "1", "d", "0", "", "repeat"],
         ["takeover", "1", "d", "0", "", "banana"], ["takeover", "1", "d", "2", "", "banana"],
         ["takeover", "1", "d", "1", "", ""], ["phishing", "4", "dsdd", "0", "3", ""],
         ["limited", "5", "dddds", "0", "", "done"], ["nope", "x", "zz", "-4", "1", ""],
         ["risky_sell", "99", "dd", "0", "1", ""], ["scam_buy", " 2 ", "d", "+1", "", "skip"]]
    r = subprocess.run([NODE, "--input-type=module", "-e",
                        probe % (B, json.dumps(g), json.dumps(o), json.dumps(w))],
                       cwd=WORKER, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    js = json.loads(r.stdout)
    py = [N.voice_twiml(B, True), N.voice_twiml(B, False), N.voice_twiml(B, False, True),
          N.voice_twiml(B, True, False, "limited")]
    for t in (True, False):
        py += [N.gather_twiml(B, t, n, d, s, None, k) for d, s, n, k in g]
        py += [N.other_twiml(B, t, n, s, None, k) for s, n, k in o]
        py += [N.walk_twiml(B, t, k, i, a, x, d, s) for k, i, a, x, d, s in w]
    assert js == py


def test_worker_steps_js_is_the_same_data():
    js = (WORKER / "src" / "steps.js").read_text()
    raw = js.split("export const PAYPAL_STEPS = ", 1)[1].rsplit(";", 1)[0]
    assert json.loads(raw) == N.PAYPAL_STEPS


def test_worker_config_is_workers_dev_only_with_no_secrets():
    t = (WORKER / "wrangler.toml").read_text()
    assert 'name = "bridge-warden-call"' in t and "workers_dev = true" in t
    assert "routes" not in t.replace("no routes", "") and "route =" not in t
    src = (WORKER / "src" / "index.js").read_text()
    # CALLFIX 2026-10-26: one private log line, only on a refused request, key names only (see refusedNote).
    assert src.count("console.") == 1 and "console.log(JSON.stringify(refusedNote(" in src
    assert "env.XAI_API_KEY" in src and "env.TWILIO_AUTH_TOKEN" in src
    assert "xai-" not in src.lower()


# ---------------------------------------------------------------- robots.txt
def test_robots_blocks_ai_bots_and_call_paths():
    groups, cur, seen_agent = {}, [], False
    for line in ROBOTS_TXT.splitlines():
        if line.startswith("User-agent:"):
            if not seen_agent:
                cur = []
            cur.append(line.split(":", 1)[1].strip())
            seen_agent = True
        elif line.startswith(("Allow:", "Disallow:")):
            seen_agent = False
            for a in cur:
                groups.setdefault(a, []).append(line)
    for bot in ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "CCBot", "ClaudeBot", "anthropic-ai", "Google-Extended",
                "Applebot-Extended", "PerplexityBot", "Bytespider", "Amazonbot", "meta-externalagent", "FacebookBot",
                "Diffbot", "Omgilibot", "cohere-ai", "ImagesiftBot", "img2dataset"):
        assert bot in AI_BOTS and groups[bot] == ["Disallow: /"]
    for bot in ("Googlebot", "Bingbot", "DuckDuckBot", "*"):
        for p in ("/voice", "/gather", "/other", "/walk", "/inbound", "/hear", "/api/"):
            assert f"Disallow: {p}" in groups[bot]
    assert "Allow: /$" in groups["Googlebot"] and "Disallow: /" not in groups["*"]
    assert "# Code is Apache 2.0 at the GitHub repo; get it there." in ROBOTS_TXT
    assert HEADERS["X-Robots-Tag"] == "noai, noimageai"


def test_worker_robots_is_the_same_text():
    js = (WORKER / "src" / "robots.js").read_text()
    assert "export const ROBOTS_TXT = " + json.dumps(ROBOTS_TXT) + ";" in js


def test_web_serves_robots_without_login(setup):
    resp, txt = setup.req("GET", "/robots.txt")             # no cookie: not logged in
    assert resp.status == 200 and txt == ROBOTS_TXT
    assert resp.getheader("X-Robots-Tag") == "noai, noimageai"


# ---------------------------------------------------------------- guided walk (PayPal's steps)
@pytest.mark.parametrize("c", WALK_VECTORS, ids=lambda c: f"{c['digits'] or '-'}|{c['speech'] or '-'}")
def test_walk_press_or_say(c):
    assert N.walk_choice(c["digits"], c["speech"]) == c["want"]


def test_six_situations_every_step_sourced_from_paypal_no_phone_numbers():
    import re
    assert N.PAYPAL_STEPS["fetched"] == "2026-10-26"
    assert set(N.SITUATIONS) == {"unauthorized", "takeover", "phishing", "scam_buy", "risky_sell", "limited"}
    for k, sit in N.SITUATIONS.items():
        assert 4 <= len(sit["steps"]) <= 8, k
        for st in sit["steps"]:
            assert st["source"].startswith("https://www.paypal.com/"), st
            assert st["say"] and st["short"] and len(st["say"]) < 300
            assert not re.search(r"\d{3}[\s.-]?\d{3}[\s.-]?\d{4}", st["say"])        # never speak a phone number
            for sent in st["say"].lower().split(". "):                              # "call" only as: use paypal.com, or don't
                if re.search(r"\bcall\b", sent):
                    assert "paypal.com" in sent or sent.strip().startswith(("do not", "never", "don't")), sent
        assert any("number on paypal.com" in st["say"] for st in sit["steps"]) or k in ("scam_buy", "risky_sell")


def test_walk_done_repeat_skip_silence_and_summary():
    st = N.walk_step("takeover", 0, "", 0, "1", "")
    assert (st["i"], st["done"], st["x"], st["finished"]) == (1, "d", 0, False)
    st = N.walk_step("takeover", 1, "d", 0, "", "repeat")
    assert (st["i"], st["x"], st["lead"]) == (1, 1, [])
    st = N.walk_step("takeover", 1, "d", 0, "", "banana")
    assert st["lead"] == [N.WALK["not_heard"]] and st["x"] == 1
    st = N.walk_step("takeover", 1, "d", N.WALK["max_repeats"], "", "banana")
    assert st["lead"] == [N.WALK["move_on"]] and (st["i"], st["done"]) == (2, "ds")
    st = N.walk_step("takeover", 1, "d", 1, "", "")
    assert st["finished"] and st["lead"] == [N.WALK_STOP]
    st = N.walk_step("takeover", 1, "d", 0, "3", "")
    assert st["lead"] == [N.WALK["skipped"]] and st["done"] == "ds"
    steps = N.SITUATIONS["phishing"]["steps"]
    s = N.walk_summary("phishing", "d" + "s" * (len(steps) - 1))
    assert s[0] == N.WALK["summary_lead"] and steps[0]["short"] in s[1] and s[2].startswith("Skipped: ")
    assert N.walk_summary("phishing", "")[1] == N.WALK["summary_none"]


def test_walk_end_test_vs_real():
    n = len(N.SITUATIONS["limited"]["steps"])
    t = N.walk_twiml(B, True, "limited", n - 1, "d" * (n - 1), 0, "1", "")
    assert N.WALK["summary_lead"] in t and t.endswith(f"{N.SAFE_END}</Say><Hangup/></Response>")
    assert N.WALK["real_end"] not in t
    r = N.walk_twiml(B, False, "limited", n - 1, "d" * (n - 1), 0, "1", "")
    assert N.WALK["real_end"] in r and N.SAFE_END not in r and "<Gather" not in r
    mid = N.walk_twiml(B, False, "limited", 0, "", 0, "1", "")
    assert "Step 2 of" in mid and N.SITUATIONS["limited"]["steps"][1]["say"].replace("&", "&amp;") in mid


def test_walk_state_is_clamped():
    assert N.walk_state("nope", "x", "zz", "-4") == ("unauthorized", 0, "", 0)
    assert N.walk_state("takeover", 99, "dd", 50)[1:] == (7, "ddsssss", 9)
    assert N.kind_of("fraud") == "unauthorized" and N.kind_of("login") == "takeover"


def test_alert_kind_picks_the_situation():
    assert N.alert_kind("Your account is limited") == "limited"
    assert N.alert_kind("A new login from a device") == "takeover"
    assert N.alert_kind("hello") == "unauthorized"
    assert "&k=limited" in N.call_url(B, "voice", True, 1, "limited")
    assert "&k=" not in N.call_url(B, "voice", True, 1, "unauthorized")


def test_demo_intro_on_inbound():
    x = N.voice_twiml(B, False, True)
    assert x.startswith(f'<Response><Say voice="man">{N.DEMO_INTRO}</Say>') and "/gather?t=1&amp;n=1" in x
