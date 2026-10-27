"""REDYELLOW (Trey, 2026-10-27): when you respond to a red but the problem is not fixed yet, the light steps
DOWN to yellow (not red, not green) and Bridge Warden stays paused, so nothing piles up. Only a full fix turns it
green. Every color change is a timestamped History line. Sandbox / fakes only."""
from conftest import NOON_ET, FakePayPal
from test_v4_ui import GIFT, NEW, events, setup, token  # noqa: F401  (setup is a fixture)
from bridge_warden import callaudit as CA
from bridge_warden import dashboard as D
from bridge_warden import web
from bridge_warden.audit import AuditLog
from bridge_warden.gate import Gate
from bridge_warden.models import ProposedAction

W = "writer@personal.example.com"


def hold(gate, n=1):
    return gate.propose(ProposedAction("payout", "40.00", "USD", NEW, f"new seller listing {n}"))


def block(gate):
    return gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))


def ack(gate):
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=gate.audit.records()[-1]["seq"], by="owner (web)")


def lights(gate):
    return [(r["from"], r["to"]) for r in events(gate, D.LIGHT_EVENT)]


def test_ack_with_held_payment_still_open_goes_yellow_paused_and_logs(setup):
    hold(setup.gate)
    _, page = setup.get("/")
    assert "st-red" in page and D.status(setup.gate)["state"] == "red"
    assert lights(setup.gate)[-1] == ("green", "red")
    assert setup.post("/act", token=token(page, "Got it, pause until I decide"))[0].status == 303
    st = D.status(setup.gate)
    assert st["state"] == "gray" and st["fix_pause"] and st["why"] == "fix" and st["waiting"] == 1
    assert "Paused while you fix it" in st["text"]
    last = events(setup.gate, D.LIGHT_EVENT)[-1]
    assert (last["from"], last["to"], last["to_color"]) == ("red", "gray", "yellow")
    assert last["text"].startswith("Bridge Warden paused operations: light set to yellow while you fix it.")
    assert last["at"] and last["clock_at"] and last["halted"] is True
    _, hist = setup.get("/history")
    assert "Bridge Warden paused operations" in hist
    assert setup.gate.audit.verify()[0]


def test_ack_blocked_plus_held_goes_yellow_not_green(gate):
    block(gate)
    hold(gate)
    assert D.status(gate)["state"] == "red"
    ack(gate)
    assert "yellow" in web.ack_light_say(gate)
    assert D.status(gate)["state"] == "gray" and lights(gate)[-1] == ("red", "gray")


def test_resolve_after_yellow_goes_green_and_logs(gate):
    r = hold(gate)
    ack(gate)
    assert D.status(gate)["state"] == "gray"
    gate.decide(r["action_id"], False, by="owner (web)")      # you dealt with it (cancel)
    assert D.status(gate)["state"] == "gray"                  # v6: still yellow until YOUR "It's fixed"
    assert D.owner_light_ok(gate, "fixed")["ok"]
    assert D.status(gate)["state"] == "green"
    last = events(gate, D.LIGHT_EVENT)[-1]
    assert (last["from"], last["to"], last["halted"]) == ("gray", "green", False)
    assert last["text"] == "Bridge Warden resumed operations: light set to green. Everything is working."
    assert lights(gate) == [("green", "red"), ("red", "gray"), ("gray", "green")]   # every change, once each


def test_ack_with_nothing_pending_goes_straight_to_green(setup):
    block(setup.gate)
    _, page = setup.get("/")
    assert setup.post("/act", token=token(page, "Got it, I've seen the blocked ones"))[0].status == 303
    assert D.status(setup.gate)["state"] == "gray"           # v6 (Trey): red never goes straight to green
    assert lights(setup.gate) == [("green", "red"), ("red", "gray")]
    assert "yellow" in web.ack_light_say(setup.gate)
    assert D.owner_light_ok(setup.gate, "fixed")["ok"]
    assert lights(setup.gate) == [("green", "red"), ("red", "gray"), ("gray", "green")]
    assert "Everything is fixed" in web.ack_light_say(setup.gate)


def test_red_survives_restart_until_acknowledged(gate, tmp_path):
    block(gate)
    assert D.status(gate)["state"] == "red"
    again = Gate(gate.engine, AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET)
    assert D.status(again)["state"] == "red"
    assert lights(again) == [("green", "red")]                # restart does not re-log or clear it
    hold(again)
    ack(again)
    assert D.status(again)["state"] == "gray"                 # still open: yellow, not green
    third = Gate(gate.engine, AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET)
    assert D.status(third)["state"] == "gray"                 # yellow survives restart too


def test_yellow_holds_new_actions_nothing_compounds(gate):
    hold(gate)
    ack(gate)
    assert D.status(gate)["state"] == "gray"
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post"))
    assert out["verdict"] == "hold" and out.get("status") == "waiting_for_owner"
    v = [r for r in gate.audit.records() if r["event"] == "verdict" and r["action_id"] == out["action_id"]][-1]
    assert "fix_pause" in {f["rule"] for f in v["verdict"]["findings"]}
    assert gate.paypal.calls == []                            # nothing ran by itself
    assert D.status(gate)["state"] == "gray"                  # held for the fix: stays yellow, no new red
    for p in gate.pending():
        gate.decide(p["proposal"]["action_id"], False, by="owner (web)")
    assert D.status(gate)["state"] == "gray"                  # v6: yellow until YOUR "It's fixed"
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post 1"))
    assert out["verdict"] == "hold" and gate.paypal.calls == []   # still paused
    for p in gate.pending():
        gate.decide(p["proposal"]["action_id"], False, by="owner (web)")
    assert D.owner_light_ok(gate, "fixed")["ok"]
    assert D.status(gate)["state"] == "green"
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post 2"))
    assert out["verdict"] == "allow" and len(gate.paypal.calls) == 1   # resumed


def test_new_problem_during_yellow_turns_red_again(gate):
    hold(gate, 1)
    ack(gate)
    assert D.status(gate)["state"] == "gray"
    block(gate)
    assert D.status(gate)["state"] == "red" and lights(gate)[-1] == ("gray", "red")


def test_ack_with_open_state_check_goes_yellow_then_clear_goes_green(gate):
    block(gate)
    CA.simulate(gate)                                         # check problem under a red: still red
    assert D.status(gate)["state"] == "red"
    ack(gate)
    st = D.status(gate)
    assert st["state"] == "gray" and st["why"] == "check" and st["fix_pause"]
    assert lights(gate)[-1] == ("red", "gray")
    assert CA.clear(gate)
    assert D.status(gate)["state"] == "gray"                  # v6: yellow until YOUR "It's fixed"
    assert D.owner_light_ok(gate, "fixed")["ok"]
    assert D.status(gate)["state"] == "green" and lights(gate)[-1] == ("gray", "green")


def test_only_the_owner_can_step_red_down(gate):
    hold(gate)
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=10 ** 6, by="system")
    assert D.status(gate)["state"] == "red"


def test_dev_simulate_buttons_still_work_and_are_not_logged_as_real(setup):
    setup.gate.dev.set(True, "red")
    st = web.with_dev(setup.app, D.status(setup.gate))
    assert st["state"] == "red" and st["dev_sim"] == "red"
    setup.gate.dev.set(True, "gray")
    assert web.with_dev(setup.app, D.status(setup.gate))["state"] == "gray"
    assert lights(setup.gate) == []                           # simulated lights never write a real light change
    _, page = setup.get("/settings")
    for label in ("Simulate pause", "Simulate check", "Simulate alert", "Back to normal"):
        assert label in page
    setup.gate.dev.set(False)


def test_history_words_and_light_line(gate):
    assert "light_changed" in web.EVENT_WORDS
    assert D.light_line("green", "red", "needs_you", "Needs you: 1 blocked.").startswith(
        "Light set to red: something bad happened. It stays red until you respond.")
    assert D.light_line("red", "gray", "fix", "x").startswith("Bridge Warden paused operations: light set to yellow")
    assert D.light_line("green", "gray", "paused", "Paused.") == "Bridge Warden paused by you: light set to yellow. Paused."
    assert D.light_line("red", "gray", "", "Hi.") == "Light set to yellow: Hi."
    hold(gate)
    html = web.other_events(gate.audit.records(), "America/New_York")
    assert "Light set to red" in html and "40" not in html.split("Light set to red")[1].split("</b>")[0]
