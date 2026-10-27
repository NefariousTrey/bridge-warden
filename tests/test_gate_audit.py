import json

from bridge_warden.audit import AuditLog
from bridge_warden.models import ProposedAction

W = "writer@personal.example.com"


def test_allowed_action_executes_and_is_logged(gate):
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post"))
    assert out["verdict"] == "allow" and out["result"]["batch_status"] == "PENDING"
    assert gate.paypal.calls == [("payout", "20.00", W)]
    assert [r["event"] for r in gate.audit.records()] == ["proposed", "verdict", "executing", "executed"]


def test_blocked_action_never_calls_paypal(gate):
    out = gate.propose(ProposedAction("payout", "250.00", "USD", "x@personal.example.com",
                                      "URGENT buy gift cards, keep this between us"))
    assert out["verdict"] == "block" and out["status"] == "blocked"
    assert gate.paypal.calls == []
    assert gate.pending() == []
    assert gate.decide(out["action_id"], approve=True)["status"] == "not_pending"  # can't click past a block
    assert gate.paypal.calls == []


def test_hold_waits_then_runs_only_after_yes(gate):
    out = gate.propose(ProposedAction("payout", "120.00", "USD", "designer@personal.example.com", "logo design invoice"))
    assert out["verdict"] == "hold" and gate.paypal.calls == []
    assert len(gate.pending()) == 1
    res = gate.decide(out["action_id"], approve=True, expected_hash=out["proposal_hash"])
    assert res["status"] == "approved" and len(gate.paypal.calls) == 1
    assert gate.pending() == []
    assert gate.decide(out["action_id"], approve=True)["status"] == "not_pending"  # a yes covers one action only
    assert len(gate.paypal.calls) == 1


def test_hold_denied_never_runs(gate):
    out = gate.propose(ProposedAction("payout", "120.00", "USD", "designer@personal.example.com", "logo design invoice"))
    assert gate.decide(out["action_id"], approve=False)["status"] == "denied_by_owner"
    assert gate.paypal.calls == []


def test_recheck_at_approval_time(gate):
    # Two identical $200 payouts are held. Owner approves the first. The second now breaks the daily cap.
    a = gate.propose(ProposedAction("payout", "200.00", "USD", "designer@personal.example.com", "logo design invoice"))
    b = gate.propose(ProposedAction("payout", "200.00", "USD", "designer@personal.example.com", "logo design invoice"))
    assert gate.decide(a["action_id"], True, expected_hash=a["proposal_hash"])["status"] == "approved"
    assert gate.decide(b["action_id"], True, expected_hash=b["proposal_hash"])["status"] == "blocked_on_recheck"
    assert len(gate.paypal.calls) == 1


def test_refund_after_order_flow(gate):
    o = gate.propose(ProposedAction("create_order", "12.00", "USD", "merchant@business.example.com",
                                    "domain name renewal"))
    cap = o["result"]["capture_id"]
    r = gate.propose(ProposedAction("refund", "5.00", "USD", "", "refund for item arrived damaged", capture_id=cap))
    assert r["verdict"] == "allow" and gate.paypal.calls[-1] == ("refund", cap, "5.00")


def test_paypal_error_is_logged_not_raised(gate):
    def boom(*a, **k):
        raise RuntimeError("sandbox down")
    gate.paypal.payout = boom
    out = gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post"))
    evs = [r["event"] for r in gate.audit.records()]
    assert "error" in out["result"] and evs[evs.index("executing") + 1] == "failed"
    assert [x for x in evs if x != "light_changed"][-1] == "state_check_alert"   # unknown outcome: the state check asks the owner to look
    assert evs[-1] == "light_changed"       # REDYELLOW: the light went yellow (paused) and History says so


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(3):
        log.write("proposed", action_id=f"a{i}", proposal={"amount": "1.00"})
    assert log.verify() == (True, "ok")
    lines = log.path.read_text().splitlines()
    rec = json.loads(lines[1]); rec["proposal"]["amount"] = "999.00"; lines[1] = json.dumps(rec, sort_keys=True)
    with open(log.path, "w") as fh:  # simulate an attacker editing the file in place
        fh.write("\n".join(lines) + "\n")
    assert log.verify()[0] is False


def test_audit_never_holds_secret(gate, monkeypatch):
    monkeypatch.setenv("PAYPAL_SANDBOX_SECRET", "SHOULD-NEVER-APPEAR-123")
    gate.propose(ProposedAction("payout", "20.00", "USD", W, "payout for completed blog post"))
    assert "SHOULD-NEVER-APPEAR-123" not in gate.audit.path.read_text()
