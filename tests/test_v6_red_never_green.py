"""v6, Trey's rule (Oct 27 2026): red can NEVER go straight to green, for ANY issue. Every red source steps down to
yellow (paused) when the owner responds or the problem ends; yellow -> green only by the OWNER's own click:
"It's fixed", or Ignore with "I'm sure" ticked. Off is red too: turning Bridge Warden on steps to yellow first.
Fakes only; nothing real is called."""
from datetime import timedelta

from conftest import NOON_ET
from test_v4_ui import GIFT, NEW, events, setup, token  # noqa: F401  (setup is a fixture)
from test_v5_retry15 import miss_all
from test_v6_ag_agent import FakeAlerts, red_finding
from bridge_warden import ag_agent as AG
from bridge_warden import dashboard as D
from bridge_warden import web
from bridge_warden.models import ProposedAction

W = "writer@personal.example.com"


def hold(gate, n=1):
    return gate.propose(ProposedAction("payout", "40.00", "USD", NEW, f"new seller listing {n}"))


def block(gate):
    return gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))


def ack(gate):
    gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=gate.audit.records()[-1]["seq"], by="owner (web)")


def lights(gate):
    return [(r["from"], r["to"], r.get("why", "")) for r in events(gate, D.LIGHT_EVENT)]


def never_red_to_green(gate):
    bad = [x for x in lights(gate) if x[0] == "red" and x[1] == "green"]
    assert bad == [], bad


def yellow_then_owner_ok(gate, mode="fixed", sure=False):
    st = D.status(gate)
    assert st["state"] == "gray" and st["why"] == "seen_fix" and st["fix_pause"], st
    assert D.fix_pause_reason(gate) == D.SEEN_FIX_TEXT          # yellow = paused: new requests wait
    r = D.owner_light_ok(gate, mode, sure=sure)
    assert r["ok"] and r["state"] == "green", r
    assert D.status(gate)["state"] == "green" and D.fix_pause_reason(gate) is None
    never_red_to_green(gate)


# ---- every red source --------------------------------------------------------------------------------------
def test_blocked_payment_seen_goes_yellow_then_fixed(gate):
    block(gate)
    assert D.status(gate)["state"] == "red"
    ack(gate)
    yellow_then_owner_ok(gate)


def test_held_payment_decided_straight_from_red_goes_yellow(gate):
    r = hold(gate)
    assert D.status(gate)["state"] == "red"
    gate.decide(r["action_id"], False, by="owner (web)")       # cancel it without "Got it" first
    yellow_then_owner_ok(gate)


def test_held_payment_seen_then_decided_stays_yellow_until_ok(gate):
    r = hold(gate)
    D.status(gate)
    ack(gate)
    assert D.status(gate)["why"] == "fix"
    gate.decide(r["action_id"], False, by="owner (web)")
    yellow_then_owner_ok(gate)


def test_block_aging_out_goes_yellow_not_green(gate):
    block(gate)
    assert D.status(gate)["state"] == "red"
    later = NOON_ET + timedelta(hours=D.BLOCK_SHOWN_HOURS + 1)
    gate.clock = lambda: later
    assert D.unseen_blocks(gate.audit.records(), later) == []    # time alone ended the red ...
    yellow_then_owner_ok(gate)                                   # ... but only YOU turn it green


def test_unanswered_alert_final_notice_cleared_goes_yellow(gate):
    miss_all(gate)
    assert D.status(gate)["state"] == "red" and D.status(gate)["why"] == "final"
    ack(gate)
    yellow_then_owner_ok(gate)


def test_ag_agent_red_seen_yellow_fixed_green_no_extra_click(gate):
    r = AG.raise_light(gate, red_finding(), alerts=FakeAlerts(gate))
    assert D.status(gate)["state"] == "red"
    assert D.owner_light_ok(gate, "fixed")["ok"] is False        # still red: refused
    AG.mark_seen(gate, r["issue_id"])
    assert D.status(gate)["state"] == "gray"
    AG.mark_fixed(gate, r["issue_id"])
    assert D.status(gate)["state"] == "green"                    # the agent's own fix step is the owner's OK
    never_red_to_green(gate)


def test_ignore_needs_im_sure(gate):
    block(gate)
    D.status(gate)
    ack(gate)
    r = D.owner_light_ok(gate, "ignored", sure=False)
    assert not r["ok"] and D.status(gate)["state"] == "gray"
    assert events(gate, "owner_light_ok_refused")
    yellow_then_owner_ok(gate, "ignored", sure=True)
    assert events(gate, D.OWNER_OK)[-1]["mode"] == "ignored" and events(gate, D.OWNER_OK)[-1]["sure"] is True


def test_ok_refused_while_red_and_for_non_owner(gate):
    block(gate)
    assert D.status(gate)["state"] == "red"
    assert D.owner_light_ok(gate, "fixed")["ok"] is False
    assert D.status(gate)["state"] == "red"
    ack(gate)
    assert D.owner_light_ok(gate, "fixed", by="BW AG Grid agent (AI)")["ok"] is False
    gate.audit.write(D.OWNER_OK, action_id="-", mode="fixed", sure=False, by="system")   # forged, not the owner
    assert D.status(gate)["state"] == "gray"
    gate.audit.write(D.OWNER_OK, action_id="-", mode="ignored", sure=False, by="owner (web)")   # no tick
    assert D.status(gate)["state"] == "gray"


def test_new_red_after_ok_needs_a_new_ok(gate):
    block(gate)
    D.status(gate)
    ack(gate)
    yellow_then_owner_ok(gate)
    block(gate)
    assert D.status(gate)["state"] == "red"
    ack(gate)
    yellow_then_owner_ok(gate)


def test_off_then_on_steps_to_yellow_never_green(gate):
    gate.engine.p["mode"] = "off"
    assert D.status(gate)["state"] == "red" and D.status(gate)["why"] == "off"
    assert D.owner_light_ok(gate, "fixed")["ok"] is False        # still red: no skipping to green while Off
    gate.engine.p["mode"] = "on"
    st = D.status(gate)
    assert st["state"] == "gray" and st["text"] == D.ON_TEXT     # back on = yellow, never straight to green
    assert D.fix_pause_reason(gate) == D.ON_TEXT
    assert D.owner_light_ok(gate, "ignored", sure=False)["ok"] is False
    assert D.owner_light_ok(gate, "fixed", by="agent")["ok"] is False   # only the owner
    assert D.owner_light_ok(gate, "fixed")["state"] == "green"
    never_red_to_green(gate)


def test_off_on_home_card_needs_owner_click(setup):
    setup.gate.engine.p["mode"] = "off"
    D.status(setup.gate)
    setup.gate.engine.p["mode"] = "on"
    _, page = setup.get("/")
    assert "Back on: confirm all is fine" in page and "st-gray" in page
    assert setup.post("/act", token=token(page, "It's fixed, confirm"))[0].status == 303
    assert D.status(setup.gate)["state"] == "green"
    never_red_to_green(setup.gate)


def test_yellow_holds_new_payments(gate):
    block(gate)
    D.status(gate)
    ack(gate)
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post"))
    assert out["verdict"] == "hold" and gate.paypal.calls == []


# ---- the owner's buttons on the home page ------------------------------------------------------------------
def test_home_card_fixed_and_ignore_buttons(setup):
    block(setup.gate)
    _, page = setup.get("/")
    assert setup.post("/act", token=token(page, "Got it, I've seen the blocked ones"))[0].status == 303
    _, page = setup.get("/")
    assert "Paused while you fix it" in page and "st-gray" in page
    assert __import__("html").escape(AG.RECOMMEND) in page and "I&#x27;m sure, I want to ignore this" in page
    assert 'id="btn-sure-light" disabled>Ignore</button>' in page
    n = page.split('class="ag-ignore">')[1].split('value="')[1].split('"')[0]
    assert setup.post("/act", token=n)[0].status == 303           # Ignore without the tick: nothing changes
    assert D.status(setup.gate)["state"] == "gray"
    _, page = setup.get("/")
    n = page.split('class="ag-ignore">')[1].split('value="')[1].split('"')[0]
    assert setup.post("/act", token=n, sure="yes")[0].status == 303
    assert D.status(setup.gate)["state"] == "green"
    never_red_to_green(setup.gate)
    assert web.ack_light_say(setup.gate).startswith("Everything is fixed")
    assert setup.gate.audit.verify()[0]
