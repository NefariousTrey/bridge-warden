"""FREEALERTS + MISSEDCALL (2026-10-26): in-app always, free email, call retries. No network, no real calls/emails."""
import inspect
import json
import threading
from datetime import timedelta

import pytest

from conftest import NOON_ET
from test_v4_ui import BASE, GIFT, events, setup, token  # noqa: F401  (fixture)
from test_devmode import dev_on
from bridge_warden import alerts as A
from bridge_warden import controls, dashboard
from bridge_warden import hosted as Ho
from bridge_warden import judge
from bridge_warden import notify as N
from bridge_warden.models import ProposedAction
from bridge_warden.policy import PolicyError, validate

SMTP_ENV = {"BW_SMTP_HOST": "smtp.example.com", "BW_SMTP_PORT": "587", "BW_SMTP_USER": "me@example.com",
            "BW_SMTP_PASSWORD": "app-pass-1234", "BW_ALERT_EMAIL_FROM": "me@example.com",
            "BW_ALERT_EMAIL_TO": "me@example.com"}


class FakeSMTP:
    sent = []

    def __init__(self, host, port, fail=False):
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, msg):
        if self.fail:
            raise OSError("smtp down app-pass-1234")
        FakeSMTP.sent.append(msg)


def email(fail=False):
    FakeSMTP.sent = []
    return A.EmailAlerter(env=SMTP_ENV, smtp_factory=lambda h, p: FakeSMTP(h, p, fail))


class FakeTwilio(N.CallAdapter):
    name, real, ready = "twilio", True, True

    def __init__(self, fail=False):
        self.calls, self.n, self.fail, self.status = [], 0, fail, {}

    def place_call(self, text, name="", voice=None):
        if self.fail:
            raise RuntimeError("twilio down")
        self.n += 1
        self.calls.append(text)
        return {"dialed": True, "status": 201, "call_sid": "CA" + f"{self.n:032x}"}

    def call_status(self, sid):
        return self.status.get(sid)


def block(gate):
    return gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))


def mk(gate, caller, em=None, now=None):
    now = now if now is not None else [NOON_ET]
    return A.Alerts(gate, caller=caller, email=em if em is not None else A.EmailAlerter(env={}),
                    clock=lambda: now[0]), now


# ---------------------------------------------------------------- free fallbacks
def test_no_twilio_no_email_still_logged_and_red(gate):
    r = block(gate)
    al, _ = mk(gate, None)
    out = al.fire(r["action_id"])
    assert out == {"in_app": True}
    assert dashboard.status(gate)["state"] == "red"
    ev = [x for x in gate.audit.records() if x["event"] == "alert_raised"]
    assert len(ev) == 1 and ev[0]["channels"] == ["in_app"] and ev[0]["for_action"] == r["action_id"]


def test_no_twilio_email_goes_at_once_without_details(gate):
    r = block(gate)
    al, _ = mk(gate, None, email())
    out = al.fire(r["action_id"])
    assert out["email"]["sent"] and len(FakeSMTP.sent) == 1
    body = FakeSMTP.sent[0].get_content()
    assert "250" not in body and "support-desk" not in body and "http" not in body
    assert [x for x in gate.audit.records() if x["event"] == "email_sent"]


def test_email_failure_never_blocks_and_hides_secret(gate):
    r = block(gate)
    al, _ = mk(gate, None, email(fail=True))
    out = al.fire(r["action_id"])
    assert out["in_app"] and not out["email"]["sent"]
    rec = [x for x in gate.audit.records() if x["event"] == "would_email_owner"][-1]
    assert "app-pass-1234" not in json.dumps(rec)


def test_call_failure_still_emails(gate):
    r = block(gate)
    al, _ = mk(gate, FakeTwilio(fail=True), email())
    out = al.fire(r["action_id"])
    assert "error" in out["call"] and out["email"]["sent"]


def test_email_off_unless_fully_configured():
    assert not A.EmailAlerter(env={}).ready
    assert not A.EmailAlerter(env={**SMTP_ENV, "BW_ALERT_EMAIL_TO": "not an address"}).ready
    assert not A.EmailAlerter(env={**SMTP_ENV, "BW_SMTP_PASSWORD": ""}).ready     # user without password
    assert A.EmailAlerter(env=SMTP_ENV).ready
    assert "app-pass" not in repr(A.EmailAlerter(env=SMTP_ENV))


def test_notifier_works_with_email_only(gate, monkeypatch):
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)
    n = N.Notifier(gate)
    assert n.caller is None and n.enabled
    n.email = email()
    n.check()
    block(gate)
    assert n.check() is True and len(FakeSMTP.sent) == 1


# ---------------------------------------------------------------- missed call + retries (fast clock)
def test_missed_call_emails_then_retries_15_then_30(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw, email())
    al.fire(r["action_id"])
    assert tw.n == 1 and FakeSMTP.sent == []                       # voice set up: no email yet
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    assert len(FakeSMTP.sent) == 1                                 # missed: email + in-app now
    assert [x for x in gate.audit.records() if x["event"] == "alert_missed_call"]
    now[0] = NOON_ET + timedelta(minutes=14, seconds=59)
    assert al.tick() == [] and tw.n == 1
    now[0] = NOON_ET + timedelta(minutes=15)
    assert al.tick() == [r["action_id"]] and tw.n == 2
    al.on_status(call_sid="CA" + f"{2:032x}", status="busy")
    assert len(FakeSMTP.sent) == 2                                 # every missed call emails again
    now[0] = NOON_ET + timedelta(minutes=29, seconds=59)
    assert al.tick() == [] and tw.n == 2
    now[0] = NOON_ET + timedelta(minutes=30)
    assert al.tick() == [r["action_id"]] and tw.n == 3
    al.on_status(call_sid="CA" + f"{3:032x}", status="no-answer")
    now[0] = NOON_ET + timedelta(hours=5)
    assert al.tick() == [] and tw.n == 3                           # no more retries
    assert len(FakeSMTP.sent) == 3                                 # one email per missed call (3 calls, 3 emails)
    assert len([x for x in gate.audit.records() if x["event"] == "alert_missed_call"]) == 3   # in-app, each miss
    assert al.queue.read()[r["action_id"]]["done_why"] == "no_more_retries"


def test_answer_stops_retries(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    al.fire(r["action_id"])
    assert al.on_status(call_sid="CA" + f"{1:032x}", status="completed") == {"answered": True}
    now[0] += timedelta(hours=1)
    assert al.tick() == [] and tw.n == 1


def test_machine_counts_as_missed(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, _ = mk(gate, tw)
    al.fire(r["action_id"])
    assert al.on_status(call_sid="CA" + f"{1:032x}", status="completed", answered_by="machine_start")["missed"]


def test_seen_in_app_stops_retries(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    al.fire(r["action_id"])
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=gate.audit.records()[-1]["seq"])
    now[0] += timedelta(minutes=16)
    assert al.tick() == [] and tw.n == 1
    assert [x for x in gate.audit.records() if x["event"] == "alert_retry_stopped"]


def test_retries_survive_restart_and_never_double_fire(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    al.fire(r["action_id"])
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    del al                                                          # "restart": only the file remains
    now[0] = NOON_ET + timedelta(minutes=20)
    a1, _ = mk(gate, tw, now=now)
    a2, _ = mk(gate, tw, now=now)
    res = []
    ts = [threading.Thread(target=lambda a=a: res.append(a.tick())) for a in (a1, a2, a1, a2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert tw.n == 2 and sum(len(x) for x in res) == 1              # exactly one retry call


def test_no_status_after_five_minutes_counts_as_missed(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    al.fire(r["action_id"])
    now[0] += timedelta(minutes=6)
    al.tick()
    assert al.queue.read()[r["action_id"]]["state"] == "waiting_retry"


def test_status_read_fallback(gate):
    r = block(gate)
    tw = FakeTwilio()
    tw.status["CA" + f"{1:032x}"] = {"status": "no-answer", "answered_by": ""}
    al, _ = mk(gate, tw)
    al.fire(r["action_id"])
    al.tick()
    assert al.queue.read()[r["action_id"]]["state"] == "waiting_retry"


def test_retries_off(gate):
    gate.engine.p["call_retry_minutes"] = []
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    al.fire(r["action_id"])
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    now[0] += timedelta(hours=3)
    assert al.tick() == [] and tw.n == 1


def test_dev_mode_simulates_miss_and_never_queues_a_retry(setup):
    """PREFLIP 2026-11-02: a dry-run alert never queues a retry (a later retry could reach real Twilio)."""
    s = setup
    dev_on(s)
    r = s.gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    tw = FakeTwilio(fail=True)                                       # would raise if ever used
    al, now = mk(s.gate, tw, email())
    al.fire(r["action_id"])
    miss = [x for x in s.gate.audit.records() if x["event"] == "alert_missed_call"]
    assert miss and miss[-1]["simulated"] and miss[-1]["label"] == "SIMULATED"
    assert any(x["event"] == "alert_retry_skipped" for x in s.gate.audit.records())
    now[0] += timedelta(minutes=15)
    assert al.tick() == []
    now[0] += timedelta(minutes=15)
    assert al.tick() == []
    assert tw.calls == [] and FakeSMTP.sent == []                     # no real call, no real email
    assert len([x for x in s.gate.audit.records() if x["event"] == "would_email_owner"]) == 1   # final notice, dry run


# ---------------------------------------------------------------- settings
def test_policy_retry_limits():
    base = json.loads(json.dumps(BASE))
    for ok in ([], [15], [15, 15], [15, 25], [1, 120, 60]):
        validate({**base, "call_retry_minutes": ok})
    for bad in ([0], [121], [1, 2, 3, 4], ["15"], 15, [True], [1.5]):
        with pytest.raises(PolicyError):
            validate({**base, "call_retry_minutes": bad})
    assert A.retry_minutes({}) == [15, 15] and A.offsets([15, 15]) == [15, 30]
    assert A.offsets([15, 25]) == [15, 40]                       # still changeable
    assert controls.parse_retry_minutes("15, 15") == [15, 15] and controls.parse_retry_minutes("off") == []
    with pytest.raises(PolicyError):
        controls.parse_retry_minutes("5, x")


def test_settings_retry_form_saves(setup):
    s = setup
    _, page = s.get("/settings")
    assert 'id="call-retries"' in page and "Each retry is a paid call" in page and "15 min then 15 min" in page
    assert "Email alerts (free): off" in page and "Recent alerts" in page
    s.post("/act", token=token(page, 'id="call-retries"'), call_retries="10, 20, 30")
    assert json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_retry_minutes"] == [10, 20, 30]
    _, page = s.get("/settings")
    s.post("/act", token=token(page, 'id="call-retries"'), call_retries="999")
    assert json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_retry_minutes"] == [10, 20, 30]
    _, page = s.get("/settings")
    s.post("/act", token=token(page, 'id="call-retries"'), call_retries="off")
    assert json.loads(open(s.gate.policy_info["path"], encoding="utf-8").read())["call_retry_minutes"] == []


def test_judges_get_no_retries():
    assert "alerts" not in inspect.getsource(N.FraudDrill)            # test calls never retry
    for k in ("BW_SMTP_PASSWORD", "BW_ALERT_EMAIL_TO", "BW_PAYPAL_WEBHOOK_ID"):
        assert k in judge.OWNER_SECRET_ENV                           # judge mode refuses owner alert keys


# ---------------------------------------------------------------- Twilio adapter + signed callback
def test_twilio_adapter_sends_status_callback_and_reads_sid():
    sent = []

    def sender(method, url, headers, body, timeout, **k):
        sent.append((method, url, body))
        if method == "GET":
            return 200, {}, b'{"status": "no-answer", "answered_by": "unknown"}'
        return 201, {}, json.dumps({"sid": "CA" + "a" * 32}).encode()
    env = {"TWILIO_ACCOUNT_SID": "AC" + "0" * 32, "TWILIO_AUTH_TOKEN": "t" * 32, "TWILIO_FROM_NUMBER": "+15550001111",
           "BW_OWNER_PHONE": "+15550002222", "BW_CALL_STATUS_URL": "https://me.example.com/call-status"}
    tw = N.TwilioCallAdapter(env=env, sender=sender)
    res = tw.place_call("Hello. Test.")
    assert res["call_sid"] == "CA" + "a" * 32 and b"StatusCallback=https" in sent[0][2]
    assert b"MachineDetection" not in sent[0][2]                     # paid extra: off by default
    assert tw.call_status("CA" + "a" * 32) == {"status": "no-answer", "answered_by": "unknown"}
    assert tw.call_status("not-a-sid") is None
    bad = N.TwilioCallAdapter(env={**env, "BW_CALL_STATUS_URL": "http://me.example.com/x"}, sender=sender)
    bad.place_call("Hi.")
    assert b"StatusCallback" not in sent[-1][2]


def test_signed_status_callback(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, _ = mk(gate, tw)
    al.fire(r["action_id"])
    cfg = {"host": "me.example.com", "auth_token": "tok"}
    p = {"CallSid": "CA" + f"{1:032x}", "CallStatus": "no-answer"}
    assert Ho.call_status(cfg, gate, p, "forged") == 403
    sig = A.twilio_signature("tok", "https://me.example.com/call-status", p)
    assert Ho.call_status(cfg, gate, p, sig) == 204
    assert A.RetryQueue(gate.audit.path.parent).read()[r["action_id"]]["state"] == "waiting_retry"


def test_notifier_does_not_ring_twice_for_outside_event(gate):
    from bridge_warden import acctwatch as W
    tw = FakeTwilio()
    n = N.Notifier(gate)
    n.caller = tw
    n.check()
    W.raise_red(gate, "WH-12345678-OUTSIDE", {"action": "payout", "amount": "9.00", "currency": "USD",
                                              "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "reason": "x",
                                              "source": "webhook"})
    A.Alerts(gate, caller=tw).fire("pp-WH-12345678-OUTSIDE")
    assert tw.n == 1
    n.check()
    assert tw.n == 1                                                  # the 3 s loop skips it
    block(gate)
    n.check()
    assert tw.n == 2                                                  # a normal block still rings


def test_default_is_three_calls_15_minutes_apart_and_answer_cancels_rest(gate):
    """Trey 2026-10-27: 3 calls in all - now, +15 min, +30 min. Answering stops the rest."""
    assert A.DEFAULT_RETRY_MINUTES == [15, 15]
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw, email())
    al.fire(r["action_id"])
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    now[0] = NOON_ET + timedelta(minutes=15)
    assert al.tick() == [r["action_id"]] and tw.n == 2
    al.on_status(call_sid="CA" + f"{2:032x}", status="completed")      # answered the 2nd call
    now[0] = NOON_ET + timedelta(hours=2)
    assert al.tick() == [] and tw.n == 2                               # 3rd call cancelled
    assert al.queue.read()[r["action_id"]]["done_why"] == "answered"
    assert len(FakeSMTP.sent) == 1                                      # only the one missed call emailed
