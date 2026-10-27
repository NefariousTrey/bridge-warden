"""after calls and actions, re-read PayPal + the log. Mismatch -> yellow + pause; red is never downgraded."""
import inspect

from bridge_warden import callaudit as C, dashboard as D, lawful as LAW, notify as N
from bridge_warden.models import ProposedAction

W = "writer@personal.example.com"


def _pay(gate, amt="20.00"):
    return gate.propose(ProposedAction("payout", amt, "USD", W, "payout for completed blog post"))


def test_clean_stays_green(gate):
    out = _pay(gate)
    assert out["verdict"] == "allow"
    assert C.run(gate, "after_alert_call")["ok"] is True
    assert C.attention(gate) is None and D.status(gate)["state"] == "green"


def test_landed_twice_goes_yellow_and_pauses(gate):
    out = _pay(gate)
    ex = next(r for r in gate.audit.records() if r["event"] == "executed")
    gate.audit.write("executed", action_id=out["action_id"], proposal=ex["proposal"], result=ex["result"])
    res = C.run(gate, "after_alert_call")
    assert res["ok"] is False and "more than once" in " ".join(res["problems"])
    st = D.status(gate)
    assert st["state"] == "gray" and st["check"] is True and "Check needed" in st["text"]
    nxt = _pay(gate, "21.00")   # automatic actions wait
    assert nxt["verdict"] == "hold" and len(gate.paypal.calls) == 1
    assert any(r["event"] == C.ALERT_EVENT for r in gate.audit.records())


def test_paypal_says_not_landed(gate):
    gate.paypal.payout_status = lambda b: {"payout_batch_id": b, "batch_status": "DENIED", "item_status": None}
    _pay(gate)    # the post-action check reads PayPal right away
    assert C.attention(gate) and "did not go through" in C.attention(gate)["note"]


def test_paypal_pending_is_fine(gate):
    gate.paypal.payout_status = lambda b: {"payout_batch_id": b, "batch_status": "PENDING", "item_status": "UNCLAIMED"}
    _pay(gate)
    assert C.attention(gate) is None


def test_started_never_finished(gate):
    gate.audit.write("executing", action_id="x-1", proposal={"amount": "5.00"})
    assert "never logged how it ended" in " ".join(C.problems(gate))


def test_red_is_not_overwritten(gate):
    held = gate.propose(ProposedAction("payout", "120.00", "USD", "designer@personal.example.com", "logo design invoice"))
    assert held["verdict"] == "hold"
    C.simulate(gate)
    assert C.attention(gate)
    assert D.status(gate)["state"] == "red"


def test_clearing_resumes(gate):
    C.simulate(gate)
    assert _pay(gate)["verdict"] == "hold"
    assert C.clear(gate) is True and C.attention(gate) is None
    assert D.status(gate)["state"] == "red"  # the held one still waits for the owner
    assert _pay(gate, "22.00")["verdict"] == "allow"
    assert C.clear(gate) is False


def test_clean_recheck_clears(gate):
    C.simulate(gate)
    assert C.run(gate, "after_action")["ok"] is True
    assert C.attention(gate) is None
    assert any(r["event"] == C.CHECK_EVENT and r.get("ok") is True for r in gate.audit.records())


def test_simulation_is_marked_test(gate):
    r = C.simulate(gate)
    assert r["simulated"] and C.attention(gate)["simulated"] is True
    assert C.attention(gate)["note"].startswith("TEST")


def test_email_only_when_set_up(gate):
    class Em:
        ready, sent = True, []

        def send(self, s, b):
            Em.sent.append((s, b))
            return {"sent": True}
    gate.audit.write("executing", action_id="x-2", proposal={})
    C.run(gate, "after_alert_call", email=Em())
    assert len(Em.sent) == 1 and "attention" in Em.sent[0][0]

    class Off:
        ready = False
    gate.audit.write("executing", action_id="x-3", proposal={})
    assert C.run(gate, "after_alert_call", email=Off())["email"]["sent"] is False


def test_hooks_wired_and_no_listening():
    src = inspect.getsource(C)
    assert "transcri" not in src.replace("does NOT hear or transcribe", "")
    assert "callaudit" in inspect.getsource(N.FraudDrill) and "alerts" not in inspect.getsource(N.FraudDrill)
    from bridge_warden import alerts as A, gate as G
    assert "state_check" in inspect.getsource(A.Alerts._place)
    assert "state_check" in inspect.getsource(G.Gate._execute)


def test_ai_disclaimer_everywhere():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert LAW.AI_NOTE == ("Bridge Warden is an AI and can make mistakes. It works from your PayPal data and is built "
                           "to catch most problems, but it doesn't replace your own eyes. Check your PayPal activity "
                           "yourself from time to time.")
    for f in ("README.md", "SETUP_YOUR_OWN.md", "proof/JUDGE_TESTING.md"):
        t = (root / f).read_text()
        assert LAW.AI_NOTE in t and "re-reads your PayPal state" in t, f
    web = (root / "bridge_warden/web.py").read_text()
    assert "LAW.AI_NOTE" in web
    assert "AI_NOTE_SHORT" in (root / "bridge_warden/cli.py").read_text()


def test_facts_rule_in_rule_and_worker():
    import pathlib
    line = ("Use only facts from the user's PayPal data. Never invent names, amounts, dates, or events that PayPal "
            "does not show. If you are unsure, say so and check first; do not guess.")
    assert LAW.RULE.endswith(line)
    js = (pathlib.Path(__file__).resolve().parent.parent / "call-worker/src/index.js").read_text()
    assert line.replace("'", "\\'") in js or line in js


# ------------------------------------------------------------------ the app (Dev mode simulation + clear button)
from test_v4_ui import setup, token  # noqa: E402,F401  (fixture)
from test_devmode import dev_on, light, press  # noqa: E402


def test_dev_mode_simulates_yellow_check_and_clear_resumes(setup):
    dev_on(setup)
    r, _ = press(setup, "Simulate check")
    assert r.status == 303
    _, html = setup.get("/settings")
    assert "Check needed" in html and "TEST" in html and C.SIM_NOTE in html
    _, home = setup.get("/")
    assert light(home) in ("gray", "yellow")
    r, _ = press(setup, "Clear the check")
    assert r.status == 303 and C.attention(setup.app.gate if hasattr(setup, "app") else setup.gate) is None
    _, html = setup.get("/settings")
    assert "Clear the check" not in html
