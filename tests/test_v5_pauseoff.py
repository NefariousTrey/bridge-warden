"""PAUSEOFF (Trey, 2026-10-27): Paused = yellow. Off = red. An alert you have not answered stays red (even
while paused) until you respond; then the red -> yellow rules apply. Every color change is a History line.
Sandbox / fakes only."""
import json

from conftest import NOON_ET, FakePayPal
from test_controls import pol
from test_v4_ui import GIFT, NEW, events, setup, token  # noqa: F401  (setup is a fixture)
from bridge_warden import dashboard as D
from bridge_warden import web
from bridge_warden.audit import AuditLog
from bridge_warden.gate import Gate
from bridge_warden.models import ProposedAction
from bridge_warden.rules import RiskEngine

W = "writer@personal.example.com"


def lights(gate):
    return [(r["from"], r["to"]) for r in events(gate, D.LIGHT_EVENT)]


def block(gate):
    return gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))


def mkgate(tmp_path, mode):
    return Gate(RiskEngine(pol(mode=mode)), AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET)


def test_pause_shows_yellow_and_logs_paused_by_you(setup):
    _, page = setup.get("/")
    assert D.status(setup.gate)["state"] == "green"
    setup.post("/act", token=token(page, "Pause"))
    assert json.loads(setup.pf.read_text(encoding="utf-8"))["mode"] == "paused"
    st = D.status(setup.gate)
    assert (st["state"], st["why"], st["paused"]) == ("gray", "paused", True)
    last = events(setup.gate, D.LIGHT_EVENT)[-1]
    assert (last["from"], last["to"], last["to_color"]) == ("green", "gray", "yellow")
    assert last["text"].startswith("Bridge Warden paused by you: light set to yellow.") and last["at"]
    _, page = setup.get("/")
    assert "st-gray" in page and "Status light Yellow" in page
    _, hist = setup.get("/history")
    assert "Bridge Warden paused by you" in hist


def test_resume_goes_green_and_logs(setup):
    setup.post("/act", token=token(setup.get("/")[1], "Pause"))
    setup.post("/act", token=token(setup.get("/")[1], "Resume"))
    assert D.status(setup.gate)["state"] == "green"
    assert lights(setup.gate) == [("green", "gray"), ("gray", "green")]
    assert events(setup.gate, D.LIGHT_EVENT)[-1]["text"].startswith("Bridge Warden resumed operations")


def test_off_shows_red_and_logs_turned_off(tmp_path):
    g = mkgate(tmp_path, "off")
    st = D.status(g)
    assert (st["state"], st["why"], st["mode"]) == ("red", "off", "off")
    last = events(g, D.LIGHT_EVENT)[-1]
    assert (last["from"], last["to"], last["to_color"]) == ("green", "red", "red")
    assert last["text"] == "Bridge Warden turned off: light set to red. Off. Payments are not checked."
    assert "Bridge Warden is off" in web.status_bar(st)
    assert "Bridge Warden is off" in web.ack_light_say(g)


def test_off_then_on_again_goes_yellow_then_owner_green(tmp_path):
    # v6 (Trey's rule): red never goes straight to green, Off included. On -> yellow; only the owner's OK -> green.
    D.status(mkgate(tmp_path, "off"))
    g = mkgate(tmp_path, "on")                                # restart with Bridge Warden on
    st = D.status(g)
    assert (st["state"], st["why"], st["text"]) == ("gray", "seen_fix", D.ON_TEXT)
    assert lights(g) == [("green", "red"), ("red", "gray")]
    assert events(g, D.LIGHT_EVENT)[-1]["text"].startswith("Bridge Warden turned on: light set to yellow")
    assert D.owner_light_ok(g, "fixed", by="owner (web)")["state"] == "green"
    assert lights(g) == [("green", "red"), ("red", "gray"), ("gray", "green")]


def test_off_to_paused_goes_red_to_yellow(tmp_path):
    D.status(mkgate(tmp_path, "off"))
    g = mkgate(tmp_path, "paused")
    assert D.status(g)["state"] == "gray"
    assert lights(g)[-1] == ("red", "gray")
    assert events(g, D.LIGHT_EVENT)[-1]["text"].startswith("Bridge Warden paused by you: light set to yellow.")


def test_unanswered_alert_stays_red_while_paused_until_you_respond(setup):
    block(setup.gate)
    assert D.status(setup.gate)["state"] == "red"
    setup.pf.write_text(json.dumps({**json.loads(setup.pf.read_text(encoding="utf-8")), "mode": "paused"}), encoding="utf-8")   # paused another way
    assert setup.gate.live_pause()
    st = D.status(setup.gate)
    assert (st["state"], st["why"]) == ("red", "needs_you")       # pause alone is not an answer
    setup.gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=setup.gate.audit.records()[-1]["seq"],
                           by="owner (web)")
    st = D.status(setup.gate)
    assert (st["state"], st["why"]) == ("gray", "paused")
    assert lights(setup.gate) == [("green", "red"), ("red", "gray")]


def test_keep_everything_blocked_is_an_answer_red_to_yellow(setup):
    block(setup.gate)
    _, home = setup.get("/")
    assert "st-red" in home
    setup.post("/act", token=token(home, "Keep everything blocked"))
    assert json.loads(setup.pf.read_text(encoding="utf-8"))["mode"] == "paused"
    assert D.status(setup.gate)["state"] == "gray"
    assert lights(setup.gate)[-1] == ("red", "gray")
    assert any(r.get("by") == "owner (web)" for r in events(setup.gate, "owner_saw_blocks"))


def test_requests_refused_while_paused_do_not_turn_red(tmp_path):
    g = mkgate(tmp_path, "paused")
    assert D.status(g)["state"] == "gray"
    out = g.propose(ProposedAction("payout", "5.00", "USD", W, "payout for completed blog post"))
    assert out["verdict"] == "block" and g.paypal.calls == []
    st = D.status(g)
    assert (st["state"], st["blocked"]) == ("gray", 0)            # refused for the pause only: stays yellow
    assert lights(g) == [("green", "gray")]


def test_risky_request_while_paused_still_turns_red(tmp_path):
    g = mkgate(tmp_path, "paused")
    block(g)                                                       # risky on its own, not just paused
    assert D.status(g)["state"] == "red" and g.paypal.calls == []


def test_unanswered_final_notice_stays_red_over_off(tmp_path):
    g = mkgate(tmp_path, "off")
    g.audit.write("alert_final_notice", action_id="-", for_action="a-1")
    assert D.status(g)["why"] == "final"


def test_light_lines():
    assert D.light_line("green", "gray", "paused", "P.") == "Bridge Warden paused by you: light set to yellow. P."
    assert D.light_line("green", "red", "off", "O.") == "Bridge Warden turned off: light set to red. O."
    assert D.light_line("red", "green", "ok", "x", "off").startswith("Bridge Warden turned on")
    assert D.light_line("green", "gray", "paused_safety", "P.").startswith("Bridge Warden paused for safety")


def test_dev_sims_unchanged(setup):
    setup.gate.dev.set(True, "gray")
    assert web.with_dev(setup.app, D.status(setup.gate))["state"] == "gray"
    setup.gate.dev.set(True, "red")
    assert web.with_dev(setup.app, D.status(setup.gate))["state"] == "red"
    assert lights(setup.gate) == []
    setup.gate.dev.set(False)
