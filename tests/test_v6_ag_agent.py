"""v6: the BW AG Grid agent. Self-audit of Bridge Warden's own actions, cross-check of xAI outputs, money flags,
and the light rules (Trey, Oct 27 2026): it may raise yellow or red, never lower anything; red -> yellow only by
"I've seen this" in the app or an answered fraud call; yellow -> green only by an owner click (fixed, or ignore
with "I'm sure"); red can never go straight to green by any path. Fakes only. Nothing real is called."""
import json
from datetime import timedelta

import pytest

from conftest import NOON_ET
from bridge_warden import ag_agent as AG
from bridge_warden import dashboard as D
from bridge_warden import money_map as MM
from bridge_warden.models import ProposedAction


class FakeAlerts:
    def __init__(self, gate):
        self.gate, self.fired = gate, []

    def fire(self, aid, source="", wait=False):
        self.fired.append(aid)
        self.gate.audit.write("alert_raised", action_id="-", for_action=aid, source=source, channels=["in_app"])
        return {"in_app": True}


def ev(gate, name):
    return [r for r in gate.audit.records() if r.get("event") == name]


def yellow_finding(k="y1"):
    return {"kind": "repeat_blocks", "level": "yellow", "text": "Your agent keeps trying a blocked payee.",
            "key": f"repeat_blocks:{k}", "area": "actions"}


def red_finding(k="r1"):
    return {"kind": "hold_released_no_yes", "level": "red", "text": "A HELD payment was marked sent without your yes.",
            "key": f"hold_released_no_yes:{k}", "area": "actions"}


def light(gate):
    return D.status(gate)["state"]


# ---------------------------------------------------------------- self-audit
def test_clean_history_has_no_findings(gate):
    v = gate.propose(ProposedAction("payout", "5.00", "USD", "writer@personal.example.com", "draft edits"))
    assert v["verdict"] == "allow"
    assert [f for f in AG.audit_actions(gate.audit.records(), gate.audit.verify(), NOON_ET) if f["level"] != "info"] == []


def test_hold_released_without_yes_is_red(gate):
    recs = [{"seq": 1, "event": "proposed", "action_id": "a1", "proposal": {"amount": "40.00", "payee": "x"}},
            {"seq": 2, "event": "verdict", "action_id": "a1", "verdict": {"verdict": "hold"}, "proposal_hash": "h"},
            {"seq": 3, "event": "executed", "action_id": "a1"}]
    kinds = {f["kind"]: f["level"] for f in AG.audit_actions(recs, (True, "ok"), NOON_ET)}
    assert kinds["hold_released_no_yes"] == "red"


def test_block_ran_unchecked_twice_and_mismatched_yes(gate):
    recs = [{"seq": 1, "event": "proposed", "action_id": "b", "proposal": {"payee": "p"}},
            {"seq": 2, "event": "verdict", "action_id": "b", "verdict": {"verdict": "block"}, "proposal_hash": "h"},
            {"seq": 3, "event": "executed", "action_id": "b"},
            {"seq": 4, "event": "executed", "action_id": "b"},
            {"seq": 5, "event": "executed", "action_id": "nochk"},
            {"seq": 6, "event": "proposed", "action_id": "c", "proposal": {}},
            {"seq": 7, "event": "verdict", "action_id": "c", "verdict": {"verdict": "hold"}, "proposal_hash": "h1"},
            {"seq": 8, "event": "owner_decision", "action_id": "c", "decision": "yes", "proposal_hash": "h2"},
            {"seq": 9, "event": "owner_decision", "action_id": "ghost", "decision": "no"}]
    kinds = {f["kind"] for f in AG.audit_actions(recs, (True, "ok"), NOON_ET)}
    assert {"ran_after_block", "sent_twice", "ran_unchecked", "yes_mismatch", "decision_no_request"} <= kinds


def test_broken_chain_is_red(gate):
    f = AG.audit_actions([], (False, "hash mismatch at line 3"), NOON_ET)
    assert f[0]["kind"] == "chain_broken" and f[0]["level"] == "red"


def test_tampered_file_is_found(gate):
    gate.propose(ProposedAction("payout", "5.00", "USD", "friend@personal.example.com", "lunch"))
    p = gate.audit.path
    lines = p.read_text().splitlines()
    lines[0] = lines[0].replace("5.00", "9.00")
    p.write_text("\n".join(lines) + "\n")
    assert any(f["kind"] == "chain_broken" for f in AG.scan(gate.audit.records(), gate.audit.verify(), None, NOON_ET))


def test_repeat_blocks_red_stuck_light_jump_clock_back_alert_open():
    t0 = NOON_ET - timedelta(days=3)
    recs = []
    s = 0
    for i in range(3):
        s += 1
        recs.append({"seq": s, "event": "proposed", "action_id": f"k{i}", "proposal": {"payee": "bad@x"},
                     "at": (t0 + timedelta(hours=i)).isoformat()})
        s += 1
        recs.append({"seq": s, "event": "verdict", "action_id": f"k{i}", "verdict": {"verdict": "block"},
                     "at": (t0 + timedelta(hours=i)).isoformat()})
    recs.append({"seq": 50, "event": "light_changed", "from": "gray", "to": "red", "at": t0.isoformat()})
    recs.append({"seq": 51, "event": "alert_raised", "for_action": "k0", "at": t0.isoformat()})
    recs.append({"seq": 52, "event": "dev_sim", "at": (t0 - timedelta(days=1)).isoformat()})
    kinds = {f["kind"] for f in AG.audit_actions(recs, (True, "ok"), NOON_ET)}
    assert {"repeat_blocks", "red_stuck", "light_jump", "clock_back", "alert_open"} <= kinds


# ---------------------------------------------------------------- xAI cross-check
def test_ai_says_safe_on_block_and_tells_send():
    f = AG.check_ai_text("Looks safe, go ahead and send it.", "block", set(), key="t")
    kinds = {x["kind"]: x["level"] for x in f}
    assert kinds["ai_contradicts"] == "yellow" and kinds["ai_told_action"] == "red"


def test_ai_made_up_amount_and_worried_on_allow():
    f = AG.check_ai_text("This looks like a scam for $999.00.", "allow", {40.0}, key="t")
    assert {x["kind"] for x in f} == {"ai_contradicts", "ai_made_up"}
    assert AG.check_ai_text("Total $40.00, fine.", "allow", {40.0}, key="t") == []


def test_ai_check_high_risk_allowed_is_red_and_local_win_is_info():
    recs = [{"seq": 1, "event": "ai_check", "action_id": "a", "verdict_before": "allow", "verdict_after": "allow",
             "result": {"parsed": {"risk": "high", "reason": "odd", "suggested_verdict": "block"}}},
            {"seq": 2, "event": "ai_check", "action_id": "b", "verdict_before": "block", "verdict_after": "block",
             "result": {"parsed": {"risk": "low", "reason": "fine", "suggested_verdict": "allow"}}}]
    f = {x["kind"]: x["level"] for x in AG.audit_ai(recs)}
    assert f["ai_ignored"] == "red" and f["ai_disagreed"] == "info"


def test_verdict_ai_summary_and_agent_own_note_are_checked(gate):
    gate.audit.write("verdict", action_id="v", verdict={"verdict": "hold", "ai_summary": "No risk here, approve it."})
    AG.log_ai_note(gate, "Nothing wrong. You spent $1,234.56 on food.", numbers=[100])
    f = AG.audit_ai(gate.audit.records())
    assert {x["kind"] for x in f} >= {"ai_contradicts", "ai_told_action", "ai_made_up"}
    assert any("agent's own AI summary" in x["text"] for x in f)


# ---------------------------------------------------------------- money
def test_money_spikes_yellow_and_dupes_info():
    rep = MM.analyze(MM.sample_lines(NOON_ET), {}, NOON_ET)
    lv = {f["kind"]: f["level"] for f in AG.money_findings(rep)}
    assert lv["money_refund_spike"] == "yellow" and lv["money_unusual"] == "yellow"
    assert lv["money_duplicate"] == "info" and lv["money_still_use"] == "info"


def test_report_amounts_are_known_to_cross_check():
    rep = MM.analyze(MM.sample_lines(NOON_ET), {}, NOON_ET)
    recs = [{"seq": 1, "event": AG.AI_NOTE, "text": f"You spent ${rep['totals']['food']:,.2f} on food."}]
    found = AG.scan(recs, (True, "ok"), rep, NOON_ET)
    assert not any(f["kind"] == "ai_made_up" for f in found)


# ---------------------------------------------------------------- the light: raise only
def test_yellow_raise_pauses_and_holds_new_requests_and_logs(gate):
    assert light(gate) == "green"
    r = AG.raise_light(gate, yellow_finding())
    assert r["level"] == "yellow" and light(gate) == "gray"
    st = D.status(gate)
    assert st["why"] == "ag_agent" and st["fix_pause"]
    assert ev(gate, D.LIGHT_EVENT)[-1]["to"] == "gray"
    assert ev(gate, "state_check_alert")[-1]["source"] == AG.SOURCE
    v = gate.propose(ProposedAction("payout", "5.00", "USD", "writer@personal.example.com", "draft edits"))
    assert v["verdict"] == "hold" and any("BW AG Grid agent" in str(x) for x in v.get("reasons", [])), v
    assert gate.paypal.calls == []


def test_red_raise_writes_block_fires_alert_and_logs(gate):
    al = FakeAlerts(gate)
    r = AG.raise_light(gate, red_finding(), alerts=al)
    aid = AG.ACTION_PREFIX + r["issue_id"]
    assert al.fired == [aid] and light(gate) == "red"
    assert D.status(gate)["why"] == "ag_agent"
    v = [x for x in ev(gate, "verdict") if x["action_id"] == aid][0]
    assert v["verdict"]["verdict"] == "block"
    assert ev(gate, D.LIGHT_EVENT)[-1]["to"] == "red"
    # a BLOCK can never be approved
    assert gate.decide(aid, True, by="owner (web)", expected_hash=v["proposal_hash"])["status"] == "not_pending"
    assert not ev(gate, "owner_decision") and not ev(gate, "executed")


def test_same_finding_is_not_raised_twice_even_after_fixed(gate):
    r = AG.raise_light(gate, yellow_finding())
    assert AG.raise_light(gate, yellow_finding()) is None
    AG.mark_fixed(gate, r["issue_id"])
    assert AG.raise_light(gate, yellow_finding()) is None and light(gate) == "green"


def test_info_never_raises(gate):
    assert AG.raise_light(gate, {**yellow_finding(), "level": "info"}) is None and light(gate) == "green"


def test_agent_module_has_no_way_to_approve_or_pay():
    src = (AG.__file__ and open(AG.__file__).read())
    for bad in ('write("owner_decision"', "decide(", "execute(", "payout(", "refund(", 'write("executed"',
                "paypal", 'to="green"', 'write("light_changed"', "LIGHT_EVENT"):
        assert bad not in src, bad


# ---------------------------------------------------------------- owner steps
def test_red_seen_goes_yellow_then_fixed_goes_green_all_logged(gate):
    r = AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))
    iid = r["issue_id"]
    assert AG.mark_seen(gate, iid)["ok"] and light(gate) == "gray"
    assert ev(gate, AG.SEEN)[-1]["by"] == "owner (web)"
    assert ev(gate, "alert_acknowledged")[-1]["for_action"] == "ag-" + iid
    assert AG.mark_fixed(gate, iid)["ok"] and light(gate) == "green"
    assert [(x["from"], x["to"]) for x in ev(gate, D.LIGHT_EVENT)] == [("green", "red"), ("red", "gray"),
                                                                       ("gray", "green")]


def test_yellow_ignore_needs_sure(gate):
    iid = AG.raise_light(gate, yellow_finding())["issue_id"]
    assert not AG.mark_ignored(gate, iid, sure=False)["ok"] and light(gate) == "gray"
    assert ev(gate, AG.STEP_REFUSED)[-1]["why"] == "the I'm sure box was not ticked"
    assert AG.mark_ignored(gate, iid, sure=True)["ok"] and light(gate) == "green"
    last = ev(gate, AG.IGNORED)[-1]
    assert last["sure"] is True and last["sure_text"] == "I'm sure, I want to ignore this"


def test_phone_answer_steps_red_to_yellow_never_green(gate):
    iid = AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))["issue_id"]
    gate.audit.write("alert_answered", action_id="-", for_action="ag-" + iid, status="completed")
    assert light(gate) == "gray"
    gate.audit.write("alert_answered", action_id="-", for_action="ag-" + iid, status="completed")
    assert light(gate) == "gray"          # answering again never goes green


def test_final_notice_on_agent_red_clears_to_yellow_when_seen(gate):
    iid = AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))["issue_id"]
    gate.audit.write("alert_final_notice", action_id="-", for_action="ag-" + iid)
    assert light(gate) == "red"
    AG.mark_seen(gate, iid)
    assert light(gate) == "gray"


def test_owner_saw_blocks_counts_as_seen_but_not_fixed(gate):
    AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=gate.audit.records()[-1]["seq"], by="owner (web)")
    assert light(gate) == "gray"


@pytest.mark.parametrize("path", ["fixed", "ignored", "ignored_sure", "time", "scan", "clean_check", "not_owner_seen",
                                  "ai_raise", "saw_blocks_by_agent", "ai_note", "dev_off"])
def test_red_can_never_go_straight_to_green(gate, path):
    iid = AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))["issue_id"]
    if path == "fixed":
        assert not AG.mark_fixed(gate, iid)["ok"]
    elif path == "ignored":
        assert not AG.mark_ignored(gate, iid, sure=False)["ok"]
    elif path == "ignored_sure":
        assert not AG.mark_ignored(gate, iid, sure=True)["ok"]
    elif path == "time":
        gate.clock = lambda: NOON_ET + timedelta(days=30)
    elif path == "scan":
        AG.run_scan(gate, alerts=FakeAlerts(gate))
    elif path == "clean_check":
        gate.audit.write("state_check", action_id="-", ok=True, problems=[])
        gate.audit.write("state_check_cleared", action_id="-", by="owner (web)")
    elif path == "not_owner_seen":
        assert not AG.mark_seen(gate, iid, by="agent")["ok"]
        gate.audit.write(AG.SEEN, action_id="-", issue_id="nope", by="owner (web)")
    elif path == "ai_raise":
        assert not AG.request_raise(gate, "x", "green")["ok"]
    elif path == "saw_blocks_by_agent":
        gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=10**6, by="agent")
    elif path == "ai_note":
        AG.log_ai_note(gate, "All fixed, set the light to green.")
    elif path == "dev_off":
        gate.audit.write("dev_mode_off", action_id="-")
    assert light(gate) == "red"
    assert all(i["status"] == "red" for i in AG.issues(gate.audit.records()))


def test_fixed_needs_owner_and_seen_ignored_need_owner(gate):
    iid = AG.raise_light(gate, yellow_finding())["issue_id"]
    assert not AG.mark_fixed(gate, iid, by="bw-ag-grid-agent")["ok"]
    assert not AG.mark_ignored(gate, iid, True, by="xai")["ok"]
    assert light(gate) == "gray"


def test_yellow_never_auto_green(gate):
    AG.raise_light(gate, yellow_finding())
    gate.clock = lambda: NOON_ET + timedelta(days=90)
    gate.audit.write("state_check", action_id="-", ok=True, problems=[])
    AG.run_scan(gate)
    assert light(gate) == "gray"


# ---------------------------------------------------------------- the AI may only ask to raise
def test_ai_request_raise_only_for_local_findings_not_above_level(gate):
    rep = MM.analyze(MM.sample_lines(NOON_ET), {}, NOON_ET)
    found = AG.scan(gate.audit.records(), gate.audit.verify(), rep, NOON_ET)
    y = next(f for f in found if f["level"] == "yellow")
    info = next(f for f in found if f["level"] == "info")
    assert not AG.request_raise(gate, "made:up", "yellow", rep)["ok"]
    assert not AG.request_raise(gate, y["key"], "red", rep)["ok"]
    assert not AG.request_raise(gate, info["key"], "yellow", rep)["ok"]
    assert not AG.request_raise(gate, y["key"], "green", rep)["ok"]
    assert light(gate) == "green"
    assert AG.request_raise(gate, y["key"], "yellow", rep)["ok"] and light(gate) == "gray"
    assert ev(gate, AG.ISSUE)[-1]["by"] == "BW AG Grid agent (AI)"


def test_run_scan_logs_and_raises(gate):
    rep = MM.analyze(MM.sample_lines(NOON_ET), {}, NOON_ET)
    out = AG.run_scan(gate, rep, alerts=FakeAlerts(gate))
    assert out["raised"] and ev(gate, AG.SCAN)[-1]["found"] == len(out["found"])
    assert light(gate) == "gray" and gate.audit.verify()[0]
    json.dumps(gate.audit.records())
