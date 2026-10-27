"""v4 'Test my alert': simulated event, TEST audit, red light, notification hook, random-delay call.
Only fake transports. No real call is ever placed by these tests."""
import json
import re
from datetime import datetime

import pytest

from test_v4_ui import BASE, GIFT, NEW, setup, token  # noqa: F401  (fixture)
from bridge_warden import net
from bridge_warden.models import ProposedAction
from bridge_warden.notify import (DRILL_MINUTES, LOCK_STEPS, MENU, TEST_CALL_TEXT, TEST_COOLDOWN, TEST_NOTICE,
                                       AlertTest, DryRunCallAdapter, FraudDrill, TwilioCallAdapter, call_adapter,
                                       call_lines, menu_reply, drill_call_delay, twiml)
from bridge_warden.notify import CALL_MENU
from bridge_warden.policy import PolicyError, validate
from bridge_warden.web import SCRIPT

ENV = {"TWILIO_ACCOUNT_SID": "AC" + "0123456789abcdef" * 2, "TWILIO_AUTH_TOKEN": "tok_SECRET_value_123",
       "TWILIO_FROM_NUMBER": "+15005550006", "BW_OWNER_PHONE": "+15551230000"}
SECRETS = [ENV["TWILIO_AUTH_TOKEN"], ENV["TWILIO_ACCOUNT_SID"], ENV["BW_OWNER_PHONE"], ENV["TWILIO_FROM_NUMBER"]]


class Timers:
    """Captures scheduled calls instead of running them."""
    def __init__(self):
        self.made = []

    def __call__(self, sec, fn):
        t = type("T", (), {"start": lambda s: None})()
        self.made.append((sec, fn))
        return t


def pol(**cof):
    return {**json.loads(json.dumps(BASE)), "notify": {"call_on_fraud": cof}}


def test_script_text_is_exact():
    assert TEST_CALL_TEXT == ("This is a Bridge Warden test. If real suspicious activity happens, you'll get a call "
                              "like this explaining how to lock your PayPal.")


def test_policy_twilio_needs_experimental_flag():
    with pytest.raises(PolicyError):
        validate(pol(enabled=True, provider="twilio"))
    with pytest.raises(PolicyError):
        validate(pol(enabled=True, provider="twilio", experimental="yes"))
    with pytest.raises(PolicyError):
        validate(pol(enabled=True, provider="twilio", experimental=True, phone="+15551230000"))  # no numbers in policy
    validate(pol(enabled=True, provider="twilio", experimental=True))
    validate(pol(enabled=False, provider="dry_run", experimental=False))


def test_adapter_choice():
    assert call_adapter({}) is None
    assert isinstance(call_adapter({}, force=True), DryRunCallAdapter)
    assert isinstance(call_adapter({"call_on_fraud": {"enabled": True, "provider": "twilio"}}), DryRunCallAdapter)
    a = call_adapter({"call_on_fraud": {"enabled": True, "provider": "twilio", "experimental": True}}, env={})
    assert isinstance(a, TwilioCallAdapter) and not a.ready


def test_twilio_without_setup_is_dry_run_and_sends_nothing():
    sent = []
    a = TwilioCallAdapter(env={**ENV, "BW_OWNER_PHONE": ""}, sender=lambda *x, **k: sent.append(x))
    r = a.place_call(TEST_CALL_TEXT)
    assert r["dialed"] is False and r["cost"] == 0 and sent == []
    assert not TwilioCallAdapter(env={**ENV, "TWILIO_ACCOUNT_SID": "bad"}).ready


def test_twilio_posts_once_to_twilio_only_with_script():
    sent = []

    def fake(method, url, headers, body, timeout, extra_host=None):
        sent.append((method, url, headers, body, extra_host))
        return 201, {}, b"{}"
    a = TwilioCallAdapter(env=ENV, sender=fake)
    assert a.ready and "tok_" not in repr(a)
    r = a.place_call(TEST_CALL_TEXT)
    assert r["dialed"] is True and len(sent) == 1
    m, url, h, body, xh = sent[0]
    assert m == "POST" and url.startswith("https://api.twilio.com/2010-04-01/Accounts/AC") and xh == "api.twilio.com"
    assert h["Authorization"].startswith("Basic ")
    assert b"Bridge+Warden+test" in body and b"lock+your+PayPal" in body
    assert "tok_" not in json.dumps(r)


def test_twilio_error_never_leaks_secrets():
    def boom(*a, **k):
        raise OSError("failed for " + " ".join(SECRETS))
    r = TwilioCallAdapter(env=ENV, sender=boom).place_call("x")
    assert r["dialed"] is False and not any(s in r["error"] for s in SECRETS)


def test_net_allows_twilio_only_when_asked():
    with pytest.raises(net.BlockedTarget):
        net.check_url("https://api.twilio.com/x")
    net.check_url("https://api.twilio.com/x", extra_host="api.twilio.com")
    with pytest.raises(net.BlockedTarget):
        net.check_url("https://evil.example/x", extra_host="evil.example")    # only listed opt-in hosts
    with pytest.raises(net.BlockedTarget):
        net.check_url("http://api.twilio.com/x", extra_host="api.twilio.com")  # https only


class FakeAI:
    def __init__(self, text="A 480 dollar gift-card payment to a new payee was stopped. Nothing was sent."):
        self.calls, self.text = [], text

    def advise(self, ctx, q=""):
        self.calls.append((ctx, q))
        return {"called": True, "text": self.text, "usage": {"prompt_tokens": 200, "completion_tokens": 30}}


def recs(gate, ev):
    return [x for x in gate.audit.records() if x["event"] == ev]


def drill(gate, **kw):
    t, now = Timers(), [0.0]
    kw.setdefault("wall", lambda: datetime(2026, 10, 26, 19, 46))
    d = FraudDrill(gate, clock=lambda: now[0], timer=t, **kw)
    gate.hold_all = d.hold_reason
    return d, t, now


def test_drill_start_logs_test_one_redacted_ai_message_and_schedules_random_call(gate):
    ai = FakeAI()
    gate.ai = ai
    d, t, now = drill(gate)
    r = d.start()
    assert r["started"] and r["provider"] == "dry_run" and r["real"] is False and r["ai"] is True
    assert len(ai.calls) == 1
    ctx, q = ai.calls[0]
    assert ctx["label"] == "TEST" and "payee A" in ctx["payee"] and "TEST DRILL" in q and "exactly as if" in q
    assert "@" not in json.dumps(ctx) and d.what == ai.text and d.what_by == "ai"
    ev = recs(gate, "alert_test")[-1]
    assert ev["label"] == "TEST" and "No real payment" in ev["note"] and "Nothing sent to PayPal" in ev["note"]
    assert ev["minutes"] == DRILL_MINUTES == 15
    assert len(t.made) == 1 and t.made[0][0] == 973 and not recs(gate, "alert_test_call")   # 19:46 -> 973 s, unannounced
    t.made[0][1]()
    c = recs(gate, "alert_test_call")[-1]
    assert c["label"] == "TEST" and c["dialed"] is False and c["provider"] == "dry_run"


def test_drill_without_ai_uses_local_words(gate):
    d, _, _ = drill(gate)
    assert d.start()["ai"] is False and d.what_by == "local" and "Nothing was sent" in d.what


def test_drill_holds_every_money_action_and_blocks_approval(gate):
    d, _, now = drill(gate)
    ok = ProposedAction("payout", "12.00", "USD", NEW, "lunch")
    d.start()
    r = gate.propose(ok)
    assert r["verdict"] == "hold" and "result" not in r and gate.paypal.calls == [] if hasattr(gate.paypal, "calls") \
        else r["verdict"] == "hold"
    assert any("Fraud drill" in x for x in r["reasons"])
    aid, h = r["action_id"], r["proposal_hash"]
    assert gate.decide(aid, True, expected_hash=h)["status"] == "paused_not_paid"   # no approvals during a drill
    now[0] = DRILL_MINUTES * 60 + 1                                                  # auto-expires
    assert not d.active() and recs(gate, "alert_test_ended")[-1]["why"] == "expired"
    assert gate.decide(aid, True, expected_hash=h)["status"] == "approved"           # owner still decides after


def test_drill_never_loosens_a_block(gate):
    d, _, _ = drill(gate)
    d.start()
    assert gate.propose(ProposedAction("payout", "480.00", "USD", NEW, GIFT))["verdict"] == "block"


def test_drill_end_and_choice_cancel_the_call_and_say_it_was_a_test(gate):
    d, t, _ = drill(gate)
    d.start()
    d.choose("lock_help")
    e = recs(gate, "alert_test_ended")[-1]
    assert e["call_cancelled"] is True and "This was a test" in e["note"] and e["label"] == "TEST"
    assert recs(gate, "alert_test_choice")[-1]["choice"] == "lock_help"
    t.made[0][1]()
    assert not recs(gate, "alert_test_call")       # ended before the ring: no call
    assert not d.end("again")


def test_drill_cooldown_and_no_double_start(gate):
    d, _, now = drill(gate)
    assert d.start()["started"]
    assert d.start()["started"] is False
    d.end("x")
    assert d.start()["started"] is False and recs(gate, "alert_test_refused")
    now[0] = TEST_COOLDOWN + 1
    assert d.start()["started"]
    assert AlertTest is FraudDrill


def test_cooldown_is_20_minutes_server_side(gate):
    from bridge_warden.notify import COOLDOWN_SAY
    assert TEST_COOLDOWN == 20 * 60
    d, t, now = drill(gate, wall=lambda: datetime(2026, 10, 26, 1, 40))   # 140 s call
    assert d.start()["started"]
    t.made[0][1]()
    d.end("owner")
    now[0] = 19 * 60 + 59                                                 # still inside 20 minutes: blocked
    assert d.start()["started"] is False and recs(gate, "alert_test_refused")[-1]["note"] == COOLDOWN_SAY
    now[0] = 20 * 60                                                      # 20 minutes later: allowed
    assert d.start()["started"]


def test_web_cooldown_message_is_exact_with_no_time_left(setup):
    from bridge_warden.notify import COOLDOWN_SAY
    s = setup
    _, page = s.get("/settings")
    s.post("/act", token=token(page, "Test my alert"))
    _, page = s.get("/settings")
    s.post("/act", token=token(s.get("/")[1], "End drill now"))           # drill over, cooldown still on
    _, page = s.get("/settings")
    s.post("/act", token=token(page, "Test my alert"))                     # pressed again inside 20 minutes
    _, page = s.get("/settings")
    assert COOLDOWN_SAY in page and "Test started." in page
    assert not re.search(r"\d+\s*min\.", page) and "Try again in" not in page and "Next test possible" not in page


def test_call_script_asks_and_ends_with_test_notice():
    lines = call_lines("Something happened.", test=True)
    assert CALL_MENU in lines and lines[-1] == TEST_NOTICE and TEST_CALL_TEXT in TEST_NOTICE   # v3 press-or-say menu
    assert "Press or say 1" in CALL_MENU and "Press 4 or say other." in CALL_MENU
    assert "What do you want me to do?" in MENU and "keep everything blocked" in MENU and "lock your PayPal" in MENU
    assert TEST_NOTICE not in call_lines("x", test=False)             # real events: no test notice
    assert menu_reply("2", True)[1:-1] == list(LOCK_STEPS) and menu_reply("2", True)[-1] == TEST_NOTICE
    assert menu_reply("1", False) == ["Okay. Everything stays blocked until you say otherwise in the app."]
    for c in "123x":
        assert not any(w in " ".join(menu_reply(c, False)).lower() for w in ("approved", "sent the payment"))
    x = twiml(["a <b>", MENU])
    assert "<Gather" not in x and "&lt;b&gt;" in x                    # no callback = no Gather; escaped
    assert '<Gather input="dtmf speech"' in twiml(["a", MENU, "c"], "https://my.example/voice")
    assert "<Gather" not in twiml(["a", MENU], "http://insecure/voice")


def test_real_drill_call_with_fake_twilio(gate):
    gate.engine.p["notify"] = {"call_on_fraud": {"enabled": True, "provider": "twilio", "experimental": True}}
    sent = []
    d, t, _ = drill(gate, env=ENV, sender=lambda *a, **k: sent.append(a) or (201, {}, b""))
    assert d.start()["real"] is True and sent == []
    t.made[0][1]()
    assert len(sent) == 1
    body = sent[0][3].decode()
    assert "Press+or+say+1" in body and "This+was+a+test" in body      # v3 call script
    c = recs(gate, "alert_test_call")[-1]
    assert c["dialed"] is True and not any(x in json.dumps(c) for x in SECRETS)


# ---------------------------------------------------------------- web
def test_web_drill_flow_red_choices_and_test_reveal(setup):
    s = setup
    s.app.alert_test.timer = Timers()
    _, page = s.get("/settings")
    assert "Test my alert" in page and "Bridge Warden charges nothing" in page and "15 minutes" in page
    _, st = s.get("/status.json")
    assert set(json.loads(st)) == {"state", "waiting", "blocked", "seq"}
    r, _ = s.post("/act", token=token(page, "Test my alert"))
    assert r.status in (302, 303)
    d = json.loads(s.get("/status.json")[1])
    assert d["state"] == "red" and isinstance(d["test"], int)
    _, home = s.get("/")
    assert "Test started." in home and "DRILL" in home and "What do you want me to do?" in home
    assert "Report to PayPal" in home and "End drill now" in home
    s.post("/act", token=token(home, "Keep everything blocked"))
    _, home = s.get("/")
    assert "This was a test" in home and "<b>What do you want me to do?</b>" not in home
    assert json.loads(s.get("/status.json")[1])["state"] == "green"
    assert s.app.gate.engine.p.get("mode", "on") != "paused"         # drill choice changed nothing real


def test_web_report_during_drill_is_marked_test_and_ends_drill(setup):
    s = setup
    s.app.alert_test.timer = Timers()
    s.app.alert_test.start()
    _, rep = s.get("/report")
    assert "This was a test" in rep and "TEST DRILL - DO NOT SEND" in rep and not s.app.alert_test.active()
    assert "paypal.com/disputes" in rep and 'href="https://' not in rep


def test_web_real_incident_report_is_redacted_and_never_sent(setup):
    s = setup
    s.gate.propose(ProposedAction("payout", "480.00", "USD", NEW, GIFT))
    _, home = s.get("/")
    assert "What do you want me to do?" in home and "DRILL" not in home and "This was a test" not in home
    _, rep = s.get("/report")
    assert NEW not in rep and "480.00" in rep and "record #" in rep and "blocked, nothing sent" in rep
    assert "You send this yourself" in rep
    r = recs(s.gate, "report_prepared")[-1]
    assert r["sent"] is False and r["label"] == ""
    resp, txt = s.get("/report.txt")
    assert resp.status == 200 and "attachment" in resp.getheader("Content-Disposition") and NEW not in txt


def test_web_real_choices_only_tighten(setup):
    s = setup
    s.gate.propose(ProposedAction("payout", "480.00", "USD", NEW, GIFT))
    _, home = s.get("/")
    r, _ = s.post("/act", token=token(home, "Show me how to lock PayPal"))
    assert r.getheader("Location").endswith("/lock")
    _, lock = s.get("/lock")
    assert "can&rsquo;t lock PayPal for you" in lock and "two-step" in lock
    _, home = s.get("/")
    s.post("/act", token=token(home, "Keep everything blocked"))
    assert json.loads(s.pf.read_text(encoding="utf-8")).get("mode") == "paused"
    assert json.loads(s.get("/status.json")[1])["state"] == "gray"


def test_web_drill_token_cannot_approve(setup):
    s = setup
    _, page = s.get("/settings")
    r, _ = s.post("/decide", nonce=token(page, "Test my alert"), d="yes")
    assert r.status in (400, 403)


def test_history_shows_test_lines(setup):
    s = setup
    t = Timers()
    s.app.alert_test.timer = t
    s.app.alert_test.start()
    t.made[0][1]()
    _, hist = s.get("/history")
    assert "TEST: you started a pretend suspicious event" in hist and "TEST: would call owner" in hist


def test_script_fires_test_notification_once():
    assert "TEST drill" in SCRIPT and "sessionStorage" in SCRIPT


# --- Trey's test-call clock rule (one place: notify.drill_call_delay) -------------------------------------------
@pytest.mark.parametrize("hh,mm,want", [(0, 0, 333), (0, 3, 330), (0, 59, 274), (1, 40, 140), (19, 46, 973),
                                        (23, 59, 1179.5), (12, 0, 1200), (12, 1, 600.5)])
def test_test_call_delay_clock_rule(hh, mm, want):
    assert drill_call_delay(datetime(2026, 10, 26, hh, mm)) == want


def test_drill_uses_clock_rule_and_expiry_keeps_the_pending_call(gate):
    d, t, now = drill(gate, wall=lambda: datetime(2026, 10, 26, 23, 59))
    assert d.start()["started"] and t.made[0][0] == 1179.5           # longer than the 15-minute drill
    now[0] = DRILL_MINUTES * 60 + 1
    assert not d.active() and recs(gate, "alert_test_ended")[-1]["call_cancelled"] is False
    assert d.pending() and d.start()["started"] is False             # no second test while the call waits
    t.made[0][1]()                                                   # it still rings, once
    assert recs(gate, "alert_test_call")[-1]["label"] == "TEST" and not d.pending()


def test_settings_says_only_test_started_with_no_timing(setup):
    s = setup
    _, page = s.get("/settings")
    s.post("/act", token=token(page, "Test my alert"))
    _, page = s.get("/settings")
    note = re.search(r'<p class="fine" id="test-note" role="status">(.*?)</p>', page)
    assert note and note.group(1) == "Test started."
    assert "random moment" not in page and "next 5 minutes" not in page
