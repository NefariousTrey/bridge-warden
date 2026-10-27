"""Real PayPal sandbox calls. Run with: RUN_LIVE=1 PAYPAL_SANDBOX_SECRET=... pytest tests/test_live_sandbox.py"""
import os

import pytest

from bridge_warden.audit import AuditLog
from bridge_warden.gate import Gate
from bridge_warden.models import ProposedAction

pytestmark = pytest.mark.skipif(not (os.environ.get("RUN_LIVE") and os.environ.get("PAYPAL_SANDBOX_SECRET")
                                     and os.environ.get("PAYPAL_CLIENT_ID")),
                                reason="live sandbox test: set RUN_LIVE=1, PAYPAL_CLIENT_ID and PAYPAL_SANDBOX_SECRET")


def test_live_order_refund_payout_and_block(engine, tmp_path):
    from bridge_warden.paypal_client import PayPalSandbox
    pp = PayPalSandbox(client_id=os.environ["PAYPAL_CLIENT_ID"])
    from conftest import NOON_ET
    g = Gate(engine, AuditLog(tmp_path / "live.jsonl"), pp, clock=lambda: NOON_ET)
    o = g.propose(ProposedAction("create_order", "3.00", "USD", "merchant@business.example.com", "domain name renewal"))
    assert o["verdict"] == "allow" and o["result"]["capture_status"] == "COMPLETED"
    r = g.propose(ProposedAction("refund", "1.00", "USD", "", "refund for item arrived damaged", capture_id=o["result"]["capture_id"]))
    assert r["result"]["refund_status"] == "COMPLETED"
    p = g.propose(ProposedAction("payout", "2.00", "USD", "writer@personal.example.com", "payout for completed blog post"))
    assert p["result"]["batch_status"] in ("PENDING", "PROCESSING", "SUCCESS")
    b = g.propose(ProposedAction("payout", "250.00", "USD", "x@personal.example.com", "URGENT gift cards, keep this between us"))
    assert b["verdict"] == "block" and "result" not in b
