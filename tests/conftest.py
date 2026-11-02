import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge_warden.audit import AuditLog  # noqa: E402
from bridge_warden.gate import Gate  # noqa: E402
from bridge_warden.rules import RiskEngine, load_policy  # noqa: E402

NOON_ET = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)  # 12:00 PM New York


class FakePayPal:
    def __init__(self):
        self.calls = []

    def create_and_capture_order(self, amount, currency, description, ref):
        self.calls.append(("order", amount))
        return {"order_id": "O-" + ref, "order_status": "COMPLETED", "capture_id": "C-" + ref, "capture_status": "COMPLETED"}

    def payout(self, amount, currency, receiver, note, ref):
        self.calls.append(("payout", amount, receiver))
        return {"payout_batch_id": "B-" + ref, "batch_status": "PENDING"}

    def refund(self, capture_id, amount, currency, ref):
        self.calls.append(("refund", capture_id, amount))
        return {"refund_id": "R-" + ref, "refund_status": "COMPLETED"}


@pytest.fixture
def policy():
    return load_policy(Path(__file__).resolve().parent.parent / "policy.example.json")


@pytest.fixture
def engine(policy):
    return RiskEngine(policy)


@pytest.fixture
def gate(engine, tmp_path):
    return Gate(engine, AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET)


@pytest.fixture(autouse=True)
def _judging_not_over(monkeypatch):
    """PREFLIP 2026-11-02: judge keys stop working on BW_JUDGE_UNTIL (default 2026-12-16). Keep the suite
    date-proof: tests run as if judging is still open unless a test sets BW_JUDGE_UNTIL itself."""
    from bridge_warden import notify as N
    monkeypatch.setattr(N, "JUDGE_UNTIL_DEFAULT", "2099-01-01")
