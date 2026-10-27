"""v6: the two help chats. Lanes, step-by-step guides, real usage only, no actions. Fake AI only."""
from conftest import NOON_ET
from bridge_warden import ag_agent as AG
from bridge_warden import dashboard as D
from bridge_warden import help_chat as H
from bridge_warden import money_map as MM
from bridge_warden.models import ProposedAction
from bridge_warden.notify import LOCK_STEPS


class FakeAI:
    def __init__(self, text="Check it in PayPal yourself.", usage=None, called=True):
        self.text, self.usage, self.called, self.calls = text, usage, called, []

    def advise(self, ctx, q, scope=""):
        self.calls.append((ctx, q, scope))
        if not self.called:
            return {"called": False, "skipped": "no_api_key"}
        return {"called": True, "text": self.text, "usage": self.usage or {"prompt_tokens": 120,
                "completion_tokens": 30, "cost_in_usd_ticks": 4_500_000}}


def ev(gate, name):
    return [r for r in gate.audit.records() if r.get("event") == name]


def test_routes_lanes_and_off_topic_without_ai(gate):
    gate.ai = FakeAI()
    r = H.ask(gate, H.NOW, "How much did I spend on food last month?", {})
    assert "History page" in r["answer"] and gate.ai.calls == [] and r["usage"] == "No AI call, no cost."
    r = H.ask(gate, H.HISTORY, "Why is a payment held right now?", {})
    assert "Home page" in r["answer"] and gate.ai.calls == []
    r = H.ask(gate, H.NOW, "Write me a poem about cats", {})
    assert "only help with Bridge Warden and PayPal" in r["answer"] and gate.ai.calls == []
    assert {x["routed"] for x in ev(gate, "help_chat_asked")} == {"other_lane", "off_topic"}


def test_guide_walks_steps_like_the_call_without_ai(gate):
    gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com",
                                "gift cards, urgent, keep it secret"))
    gate.ai = FakeAI()
    st = {}
    r = H.ask(gate, H.NOW, "", st)
    assert r["guide"]["steps"] == list(LOCK_STEPS) and r["answer"].startswith("Step 1 of")
    r = H.ask(gate, H.NOW, "next", {"step": r["step"]})
    assert r["answer"].startswith("Step 2 of") and gate.ai.calls == []
    assert ev(gate, "help_chat_step")[-1]["ai_used"] is False


def test_hold_guide_and_ai_answer_shows_real_usage(gate):
    gate.propose(ProposedAction("payout", "40.00", "USD", "new@personal.example.com", "first order"))
    gate.ai = FakeAI()
    r = H.ask(gate, H.NOW, "Is this payment a scam?", {})
    assert r["guide"]["steps"] == list(H.HOLD_STEPS) and r["by_ai"]
    assert "120 in + 30 out tokens" in r["usage"] and "$0.00045 (from xAI)" in r["usage"]
    assert H.NO_LIMIT in r["usage"]
    ctx, q, scope = gate.ai.calls[0]
    assert scope == H.SCOPE[H.NOW] and ctx["held_payments"][0]["payee"] == "payee A"
    assert "new@personal" not in str(ctx)


def test_no_cost_reported_says_so():
    assert "cost not reported by xAI" in H.usage_line({"called": True, "usage": {"prompt_tokens": 1,
                                                                                "completion_tokens": 1}})


def test_no_key_falls_back_to_local_step(gate):
    gate.ai = FakeAI(called=False)
    r = H.ask(gate, H.NOW, "What should I do now?", {})
    assert not r["by_ai"] and "AI not used" in r["answer"] and r["usage"] == "No AI call, no cost."


def test_chat_cannot_act_and_bad_answer_is_flagged(gate):
    gate.ai = FakeAI(text="I approved it and turned the light green. Go ahead and send it.")
    AG.raise_light(gate, {"kind": "repeat_blocks", "level": "yellow", "text": "x", "key": "k:1", "area": "actions"})
    before = D.status(gate)["state"]
    r = H.ask(gate, H.NOW, "How do I fix this issue?", {})
    assert r["warn"].startswith("The BW AG Grid agent checked this answer")
    assert D.status(gate)["state"] == before == "gray"
    assert not ev(gate, "owner_decision") and not ev(gate, AG.FIXED) and not ev(gate, AG.IGNORED)
    assert ev(gate, AG.AI_NOTE)        # kept for the next cross-check scan


def test_history_lane_sees_only_redacted_money(gate):
    gate.ai = FakeAI(text="Food was your biggest group.")
    rep = MM.analyze(MM.sample_lines(NOON_ET), {}, NOON_ET)
    r = H.ask(gate, H.HISTORY, "Where does my money go each month?", {}, rep)
    ctx = gate.ai.calls[0][0]
    assert ctx["lane"] == "history" and "totals_by_group" in ctx["money"] and "lines" not in ctx["money"]
    assert r["guide"]["title"] == "Tidy your subscriptions"
    assert H.SUB_STEPS[1].startswith("Go to Settings, then Payments")
