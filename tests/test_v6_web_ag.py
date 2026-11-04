"""v6 web: the BW AG Grid agent on History, the two read-only chats, the money map grid, the AG Studio chat proxy,
"I'm sure" on Send, Dev-mode TEST issues, and real-only usage lines.
Made by @Nefarious_Trey,
with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache 2.0.
Fakes only: fake PayPal, fake xAI transport, fake Twilio. Nothing real is called."""
import html
import json
import re

import pytest

from test_v4_ui import NEW, setup, token  # noqa: F401  (fixture)
from bridge_warden import ag_agent as AG
from bridge_warden import ag_studio as STUDIO
from bridge_warden import dashboard as D
from bridge_warden import help_chat as H
from bridge_warden import notify as N
from bridge_warden import web as W
from bridge_warden.models import ProposedAction

SECRET = "xai-" + "S3cr3tKeyNeverLogged" * 3


def ev(gate, name):
    return [r for r in gate.audit.records() if r.get("event") == name]


def light(page):
    """The light as the owner sees it. A yellow (paused) light is drawn with the st-gray class."""
    c = re.search(r'class="status st-(\w+)"', page).group(1)
    return {"gray": "yellow"}.get(c, c)


def dev_on(s):
    _, html = s.get("/settings")
    assert s.post("/act", token=token(html, "Turn on Dev mode"))[0].status == 303
    assert s.gate.dev.on()


def press(s, label, where="/history", **extra):
    _, html = s.get(where)
    return s.post("/act", token=token(html, label), **extra)


def ignore_token(html, iid):
    m = re.search(r'<form method="post" action="/act" class="ag-ignore">(.*?)</form>', html, re.S)
    assert m and f'id="sure-{iid}"' in m.group(1)
    return re.search(r'name="token" value="([^"]+)"', m.group(1)).group(1)


def issue_ids(gate):
    return [i["id"] for i in AG.issues(gate.audit.records())]


# ------------------------------------------------------------------ "I'm sure" on a held payment
def test_held_send_needs_im_sure(setup):
    setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    _, page = setup.get("/")
    assert html.escape(AG.SURE_SEND) in page and 'data-sure="send-' in page
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    setup.post("/decide", nonce=n, d="yes")
    assert setup.gate.paypal.calls == [] and ev(setup.gate, "owner_send_refused")
    assert D.status(setup.gate)["state"] == "red"


# ------------------------------------------------------------------ Dev mode: every light step, owner clicks only
def test_dev_red_issue_full_walk(setup):
    dev_on(setup)
    g = setup.app.gate          # in Dev mode the app runs on the TEST gate
    assert press(setup, "Raise TEST red", "/settings")[0].status == 303
    _, h = setup.get("/history")
    assert light(h) == "red" and "I've seen this" in h and AG.NAME in h
    iid = issue_ids(g)[-1]
    # no fixed / ignore offered while red: red never goes straight to green
    assert f"ag:fixed:{iid}" not in h and 'class="ag-ignore"' not in h
    assert press(setup, "I've seen this")[0].status == 303
    _, h = setup.get("/history")
    assert light(h) == "yellow" and html.escape(AG.RECOMMEND) in h and html.escape(AG.SURE_TEXT) in h
    # ignore without the tick: refused, still yellow
    setup.post("/act", token=ignore_token(h, iid))
    _, h = setup.get("/history")
    assert light(h) == "yellow" and "tick" in h
    # with the tick: green
    setup.post("/act", token=ignore_token(h, iid), sure="yes")
    _, h = setup.get("/history")
    assert light(h) == "green"
    kinds = [r["event"] for r in g.audit.records() if r["event"].startswith("ag_agent_")]
    assert kinds.count(AG.ISSUE) == 1 and AG.SEEN in kinds and AG.IGNORED in kinds
    assert setup.gate.paypal.calls == [] and g.paypal is None   # the TEST gate has no PayPal at all


def test_dev_yellow_issue_fixed_by_owner(setup):
    dev_on(setup)
    press(setup, "Raise TEST yellow", "/settings")
    _, h = setup.get("/history")
    assert light(h) == "yellow"
    assert press(setup, "It's fixed, confirm")[0].status == 303
    _, h = setup.get("/history")
    assert light(h) == "green" and ev(setup.app.gate, AG.FIXED)


def test_nonce_is_single_use_and_cross_site_refused(setup):
    dev_on(setup)
    press(setup, "Raise TEST red", "/settings")
    _, h = setup.get("/history")
    t = token(h, "I've seen this")
    bad = setup.req("POST", "/act", f"token={t}", {**setup.ck, "Content-Type": "application/x-www-form-urlencoded",
                                                   "Origin": "https://evil.example"})[0]
    assert bad.status in (400, 403)
    assert setup.post("/act", token=t)[0].status == 303
    setup.post("/act", token=t)        # replay
    assert len(ev(setup.app.gate, AG.SEEN)) == 1


def test_scan_button_is_read_only(setup):
    assert press(setup, f"Run the {AG.NAME} now")[0].status == 303
    assert ev(setup.gate, AG.SCAN)[-1]["read_only"] is True and setup.gate.paypal.calls == []


# ------------------------------------------------------------------ two chats, two lanes
def chat_token(page, lane):
    m = re.search(r'<form method="post" action="/act">((?:(?!</form>).)*id="q-' + lane + r'"(?:(?!</form>).)*)</form>',
                  page, re.S)
    assert m, lane
    return re.search(r'name="token" value="([^"]+)"', m.group(1)).group(1)


def test_two_chats_labeled_and_no_key_means_no_cost(setup):
    setup.gate.ai = None
    for lane, where in ((H.HISTORY, "/history"), (H.NOW, "/")):
        _, page = setup.get(where)
        assert f'id="chat-{lane}"' in page and "cannot press any button" in page
        assert setup.post("/act", token=chat_token(page, lane), q="next")[0].status == 303
        assert setup.post("/act", token=chat_token(setup.get(where)[1], lane), q="Why is food so high?")[0].status == 303
        _, page = setup.get(where)
        assert "No AI call, no cost." in page
    assert ev(setup.gate, "help_chat_asked") and setup.gate.paypal.calls == []
    _, home = setup.get("/")
    assert 'id="chat-history"' not in home       # each lane on its own page


# ------------------------------------------------------------------ money map grid
def test_money_map_json_needs_login_and_is_owner_only(setup):
    assert setup.req("GET", "/money-map.json")[0].status == 401
    r, body = setup.get("/money-map.json")
    assert r.status == 200
    json.loads(body)
    assert "/money-map.json" in W.ROBOTS_TXT and "/ag-studio/" in W.ROBOTS_TXT


# ------------------------------------------------------------------ AG Studio chat proxy
class FakeAI:
    def __init__(self, key=SECRET, zdr="true", status=200, skip=None):
        self.cfg = {"model": "grok-test", "timeout_seconds": 5, "require_zdr": True}
        self._key, self._zdr_state, self.sent, self.zdr, self.status, self.skip = key, None, [], zdr, status, skip

    def skip_reason(self):
        return self.skip

    def _budget_reason(self):
        return None

    def _preflight_zdr(self):
        self._zdr_state = True

    def _headers(self):
        return {"Authorization": "Bearer " + self._key}

    def _send_counted(self, method, url, headers, body, timeout):
        self.sent.append((url, json.loads(body)))
        out = {"id": "r1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Food is top."}]},
                                      {"type": "function_call", "call_id": "c1", "name": "bw_subscriptions",
                                       "arguments": "{}"}],
               "usage": {"input_tokens": 12, "output_tokens": 5, "cost_in_usd_ticks": 123456}}
        return self.status, {"x-zero-data-retention": self.zdr}, json.dumps(out).encode()

    def _record(self, ok):
        pass

    def _scrub(self, s):
        return s.replace(self._key, "[key]")


REQ = {"input": [{"role": "user", "content": "Where does my money go?"}],
       "tools": [{"type": "function", "name": "bw_spending_categories", "description": "x", "parameters": {}}]}

needs_studio = pytest.mark.skipif(not STUDIO.ready(), reason="AG Studio not fetched (scripts/fetch_ag_studio.sh)")


def _post(s, body, ctype="application/json", origin="same"):
    h = {**s.ck, "Content-Type": ctype}
    if origin == "same":
        h["Origin"] = _ORIGIN[0]
    elif origin:
        h["Origin"] = origin
    raw = body if isinstance(body, str) else json.dumps(body)
    return s.req("POST", "/ag-studio/v1/responses", raw, h)


_ORIGIN = [None]


@pytest.fixture
def st(setup):
    # the fixture's own same-origin header value
    import test_v4_ui as T  # noqa: F401
    _ORIGIN[0] = None
    for cell in setup.post.__closure__ or ():
        v = cell.cell_contents
        if isinstance(v, dict) and "Origin" in v:
            _ORIGIN[0] = v["Origin"]
    assert _ORIGIN[0]
    return setup


@needs_studio
def test_studio_no_key_is_graceful(st):
    st.gate.ai = None
    r, body = _post(st, REQ)
    assert r.status == 503 and "AI not used" in body and ev(st.gate, STUDIO.EVENT)[-1]["sent"] is False


@needs_studio
def test_studio_answer_has_real_usage_and_key_never_logged(st, tmp_path):
    st.gate.ai = FakeAI()
    r, body = _post(st, REQ)
    assert r.status == 200
    d = json.loads(body)
    assert "12 in + 5 out tokens" in d["bw_usage"] and "$0.00001" in d["bw_usage"] and H.NO_LIMIT in d["bw_usage"]
    url, sent = st.gate.ai.sent[-1]
    assert url == STUDIO.XAI_RESPONSES_URL and sent["store"] is False and sent["stream"] is False
    assert sent["model"] == "grok-test" and sent["max_output_tokens"] == STUDIO.MAX_OUTPUT_TOKENS
    assert sent["instructions"].startswith(STUDIO.STUDIO_RULES)
    rec = ev(st.gate, STUDIO.EVENT)[-1]
    assert rec["tools_called"] == ["bw_subscriptions"] and rec["usage"]["prompt_tokens"] == 12
    log = (st.gate.audit.path.read_text(encoding="utf-8") if hasattr(st.gate.audit, "path") else json.dumps(st.gate.audit.records()))
    assert SECRET not in log and "Where does my money go" not in log
    assert SECRET not in body


@needs_studio
def test_studio_zdr_false_answer_thrown_away(st):
    st.gate.ai = FakeAI(zdr="false")
    r, body = _post(st, REQ)
    assert r.status == 503 and "Food is top" not in body
    r, _ = _post(st, REQ)          # and no further call is made
    assert r.status == 503 and len(st.gate.ai.sent) == 1


@needs_studio
@pytest.mark.parametrize("why,kw", [
    ("cross-site", dict(origin="https://evil.example")),
    ("no origin", dict(origin=None)),
    ("content type", dict(ctype="text/plain")),
])
def test_studio_refusals(st, why, kw):
    st.gate.ai = FakeAI()
    r, _ = _post(st, REQ, **kw)
    assert r.status >= 400 and st.gate.ai.sent == [], why


@needs_studio
def test_studio_refuses_bad_bodies(st):
    st.gate.ai = FakeAI()
    for body in ("not json", {"input": "x"}, {"input": [{"role": "user", "content": "mail me at a@b.example.com"}]},
                 {**REQ, "tools": [{"type": "web_search"}]},
                 {"input": [{"role": "user", "content": "x"}] * (STUDIO.MAX_ITEMS + 1)}):
        r, _ = _post(st, body)
        assert r.status == 400, body
    r, _ = _post(st, "x" * (STUDIO.MAX_BODY + 10))
    assert r.status == 413
    assert st.gate.ai.sent == []


@needs_studio
def test_studio_needs_login(st):
    r, _ = st.req("POST", "/ag-studio/v1/responses", json.dumps(REQ),
                  {"Content-Type": "application/json", "Origin": _ORIGIN[0]})
    assert r.status == 401
    assert st.req("GET", "/ag-studio/config.json")[0].status == 401


@needs_studio
def test_studio_rate_limited(st):
    st.gate.ai = FakeAI()
    codes = [_post(st, REQ)[0].status for _ in range(W.STUDIO_TURNS_PER_10_MIN + 2)]
    assert codes.count(200) == W.STUDIO_TURNS_PER_10_MIN and codes[-1] == 429


@needs_studio
def test_studio_config_key_from_env_only(st, monkeypatch):
    monkeypatch.setenv(STUDIO.LICENSE_ENV, "AGKEY-" + "x" * 20)
    r, body = st.get("/ag-studio/config.json")
    assert r.status == 200 and json.loads(body)["license_key"].startswith("AGKEY-")
    assert "AGKEY-" not in json.dumps(st.gate.audit.records())
    # real AG keys contain spaces (allowed, see test_v6_ag_license_key.py); control chars are refused
    monkeypatch.setenv(STUDIO.LICENSE_ENV, "bad key\twith a tab")
    assert json.loads(st.get("/ag-studio/config.json")[1])["license_key"] == ""


@needs_studio
def test_studio_data_is_redacted(st):
    r, body = st.get("/ag-studio/data.json")
    assert r.status == 200
    d = json.loads(body)
    assert "@" not in body and set(d["rows"][0]) <= {"month", "group", "kind", "amount", "flag"} if d.get("rows") else True


@needs_studio
def test_history_page_loads_studio_with_csp(st):
    """v6 fix 2026-10-27: AG Studio sets inline style attributes. On History's strict CSP they were blocked and its
    layout spilled over the owner's buttons. Now it lives in its own framed page; History keeps its strict CSP."""
    r, h = st.get("/history")
    csp = r.getheader("Content-Security-Policy")
    assert 'id="bw-studio-frame"' in h and 'src="/ag-studio/panel"' in h and "commercial" in h
    assert 'sandbox="allow-scripts allow-same-origin"' in h          # no forms, no popups, no top navigation
    assert "frame-src 'self'" in csp and "unsafe-inline" not in csp
    assert STUDIO.static("vendor/" + STUDIO.BUNDLE)[1] not in csp     # Studio scripts never run on History itself
    assert "ag-studio.min.js" not in h
    r2, p = st.get("/ag-studio/panel")
    pc = r2.getheader("Content-Security-Policy")
    assert r2.status == 200 and 'id="bw-studio"' in p and 'id="bw-studio-usage"' in p
    assert STUDIO.static("vendor/" + STUDIO.BUNDLE)[1] in pc and STUDIO.static(STUDIO.GLUE)[1] in pc
    assert "script-src 'sha256-" in pc and "'unsafe-inline'" in pc.split("style-src")[1].split(";")[0]
    assert "unsafe-inline" not in pc.split("script-src")[1].split(";")[0] and "unsafe-eval" not in pc
    assert "form-action 'none'" in pc and "frame-ancestors 'self'" in pc and "<form" not in p
    assert r2.getheader("X-Frame-Options") == "SAMEORIGIN" and "http" not in pc


def test_studio_panel_needs_login_and_is_404_without_studio(st, monkeypatch):
    r, _ = st.req("GET", "/ag-studio/panel")          # no cookie
    assert r.status == 401
    monkeypatch.setattr(STUDIO, "PINNED_SHA256", "0" * 64)
    r, _ = st.get("/ag-studio/panel")
    assert r.status == 404
    r, h = st.get("/history")
    assert 'id="bw-studio-frame"' not in h and "frame-src" not in r.getheader("Content-Security-Policy")


def test_changed_vendor_file_is_never_served(monkeypatch):
    monkeypatch.setattr(STUDIO, "PINNED_SHA256", "0" * 64)
    assert STUDIO.bundle() is None and not STUDIO.ready() and STUDIO.static("vendor/" + STUDIO.BUNDLE) is None
    assert STUDIO.csp_hashes() == ""


# ------------------------------------------------------------------ Twilio usage: real numbers only
class FakeTw:
    ready = True

    def __init__(self, use, bal):
        self.use, self.bal = use, bal

    def call_usage(self, sid):
        return self.use

    def balance(self):
        return self.bal


def test_call_usage_line_real_only(setup, monkeypatch):
    assert W.call_usage_line(setup.app, {"dialed": False}) == "No real call, no cost."
    assert "did not give a call id" in W.call_usage_line(setup.app, {"dialed": True})
    monkeypatch.setattr(N, "TwilioCallAdapter", lambda env=None: FakeTw(
        {"duration_seconds": "31", "price": "-0.0140", "price_unit": "USD"}, {"balance": "14.20", "currency": "USD"}))
    line = W.call_usage_line(setup.app, {"dialed": True, "call_sid": "CA" + "a" * 32})
    assert "31 seconds" in line and "0.0140 USD (from Twilio)" in line and "14.20 USD" in line
    monkeypatch.setattr(N, "TwilioCallAdapter", lambda env=None: FakeTw(None, None))
    line = W.call_usage_line(setup.app, {"dialed": True, "call_sid": "CA" + "b" * 32})
    assert "no cost posted yet" in line and H.NO_LIMIT in line


def test_event_words_cover_new_events():
    for k in (AG.ISSUE, AG.SEEN, AG.FIXED, AG.IGNORED, AG.SCAN, AG.AI_NOTE, AG.STEP_REFUSED, STUDIO.EVENT,
              "help_chat_asked", "help_chat_step", "owner_send_refused"):
        assert k in W.EVENT_WORDS, k
