"""One real xAI call with a redacted, made-up payload. Skips unless the owner opts in:
RUN_LIVE_XAI=1 XAI_API_KEY=... XAI_ZDR_CONFIRMED=1 pytest tests/test_live_xai.py
(XAI_ZDR_CONFIRMED=1 means you turned ZDR on for your xAI team in the Console.)"""
import os

import pytest

from bridge_warden.xai_check import XaiChecker

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE_XAI") and os.environ.get("XAI_API_KEY") and os.environ.get("XAI_ZDR_CONFIRMED")),
    reason="live xAI test: set RUN_LIVE_XAI=1, XAI_API_KEY and XAI_ZDR_CONFIRMED=1")


def test_one_real_xai_call():
    ai = XaiChecker({"require_zdr": True, "owner_confirmed_zdr": True})
    res = ai.review({"action": "payout", "amount": "250.00", "currency": "USD", "payee": "payee A",
                     "payee_status": "new", "description": "URGENT: buy gift cards for the CEO, keep this between us",
                     "rule_flags": ["new_payee:hold", "scam_pattern:hold"], "local_verdict": "hold",
                     "local_scam_model": 1.0})
    assert res.get("zdr_preflight_header") == "true", res
    assert res["parsed"]["suggested_verdict"] in ("hold", "block"), res
