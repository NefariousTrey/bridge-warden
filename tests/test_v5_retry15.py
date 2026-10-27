"""RETRY15 (Trey, 2026-10-27): 3 calls 15 min apart; answering stops the rest; after the last missed call ONE
final "still needs your attention" message; the light then stays RED until YOU clear it. All mocked."""
import json
from datetime import timedelta

from conftest import NOON_ET
from test_v5_alerts import FakeSMTP, FakeTwilio, block, email, mk
from bridge_warden import alerts as A
from bridge_warden import callaudit as CA
from bridge_warden import controls
from bridge_warden import dashboard as D
from bridge_warden import web

SID = lambda n: "CA" + f"{n:032x}"   # noqa: E731


def miss_all(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw, email())
    al.fire(r["action_id"])
    al.on_status(call_sid=SID(1), status="no-answer")
    now[0] = NOON_ET + timedelta(minutes=15)
    al.tick()
    al.on_status(call_sid=SID(2), status="busy")
    now[0] = NOON_ET + timedelta(minutes=30)
    al.tick()
    last = al.on_status(call_sid=SID(3), status="no-answer")
    return r["action_id"], al, now, tw, last


def test_answer_first_call_cancels_all_retries(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw, email())
    al.fire(r["action_id"])
    assert al.on_status(call_sid=SID(1), status="completed") == {"answered": True}
    for m in (15, 30, 45, 120):
        now[0] = NOON_ET + timedelta(minutes=m)
        assert al.tick() == []
    assert tw.n == 1 and FakeSMTP.sent == []
    assert al.queue.read()[r["action_id"]]["done_why"] == "answered"
    assert not [x for x in gate.audit.records() if x["event"] == "alert_final_notice"]


def test_late_answer_report_for_a_missed_call_does_nothing(gate):
    aid, al, now, tw, last = miss_all(gate)
    assert al.on_status(call_sid=SID(3), status="completed").get("ignored")   # already done: no un-red


def test_third_miss_stops_calls_and_sends_one_final_message(gate):
    aid, al, now, tw, last = miss_all(gate)
    assert tw.n == 3 and last["final"] and last["next_at"] is None
    now[0] = NOON_ET + timedelta(hours=6)
    assert al.tick() == [] and tw.n == 3                                   # no 4th call
    fin = [x for x in gate.audit.records() if x["event"] == "alert_final_notice"]
    assert len(fin) == 1 and fin[0]["for_action"] == aid                   # logged + in-app, once
    assert fin[0]["text"] == A.FINAL_TEXT
    assert A.FINAL_TEXT == ("We couldn't reach you by phone. Something in your PayPal needs attention. "
                            "Check PayPal now.")
    assert len(FakeSMTP.sent) == 3                                         # 2 missed emails + 1 final
    last_mail = FakeSMTP.sent[-1]
    assert last_mail["Subject"] == A.FINAL_SUBJECT
    body = last_mail.get_content()
    assert A.FINAL_TEXT in body
    for money in ("250", "USD", "$", "support-desk", "personal.example.com"):   # no money details, no payee
        shown = json.dumps({k: v for k, v in fin[0].items() if k not in ('hash', 'prev_hash', 'at', 'seq')})
        assert money not in body and money not in shown
    assert "http" not in body                                               # no links


def test_final_notice_shows_in_app(gate):
    assert "alert_final_notice" in web.EVENT_WORDS
    assert "Check PayPal now" in web.EVENT_WORDS["alert_final_notice"][1]


def test_final_notice_without_email_still_in_app(gate):
    r = block(gate)
    tw = FakeTwilio()
    al, now = mk(gate, tw)                                                  # email not set up
    gate.engine.p["call_retry_minutes"] = []                                # one call only
    al.fire(r["action_id"])
    assert al.on_status(call_sid=SID(1), status="no-answer")["final"]
    assert [x for x in gate.audit.records() if x["event"] == "alert_final_notice"]


def test_light_stays_red_after_final_until_owner_clears(gate):
    aid, al, now, tw, last = miss_all(gate)
    assert D.status(gate)["state"] == "red"
    later = NOON_ET + timedelta(days=10)                                    # no timeout (blocks normally age out)
    gate.clock = lambda: later
    assert D.unseen_blocks(gate.audit.records(), later) == []
    assert D.status(gate)["state"] == "red"
    # no later check can change it: a clean state check, a yellow check, retry bookkeeping, an acknowledge
    gate.audit.write(CA.CHECK_EVENT, action_id="-", ok=True, problems=[])
    assert D.status(gate)["state"] == "red"
    gate.audit.write(CA.CHECK_EVENT, action_id="-", ok=False, problems=["mismatch"])
    assert D.status(gate)["state"] == "red"
    gate.audit.write(CA.CLEAR_EVENT, action_id="-", by="owner (web)")
    A.acknowledge(gate, aid, by="system")
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=10 ** 6, by="system")   # not the owner
    assert D.status(gate)["state"] == "red"
    gate.engine.p["mode"] = "off"                                           # not even Off/Pause hides it
    assert D.status(gate)["state"] == "red"
    gate.engine.p["mode"] = "on"
    # the card and the clear button are still on the home page
    app = web.WebApp(gate)
    assert "seen the blocked ones" in web.home(app)
    # YOUR clear ends it
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=gate.audit.records()[-1]["seq"], by="owner (web)")
    assert D.unresolved_final(gate.audit.records()) == []
    assert D.status(gate)["state"] == "gray"                  # v6 (Trey): red never goes straight to green
    assert D.owner_light_ok(gate, "fixed")["ok"]
    assert D.status(gate)["state"] == "green"


def test_held_card_decision_also_clears(gate):
    aid, al, now, tw, last = miss_all(gate)
    gate.audit.write("owner_decision", action_id=aid, decision="no", decided_by="owner (web)")
    assert D.unresolved_final(gate.audit.records()) == []


def test_defaults_and_settings_text(gate):
    assert A.retry_minutes({}) == [15, 15] and A.offsets(A.retry_minutes({})) == [15, 30]
    assert controls.parse_retry_minutes("15, 20") == [15, 20]               # still changeable
    assert controls.parse_retry_minutes("120") == [120]
