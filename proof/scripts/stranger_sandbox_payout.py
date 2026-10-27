"""NOT RUN. Needs Trey's yes. The e2e proof: a payout made OUTSIDE Bridge Warden (straight to the PayPal sandbox
API, fake sandbox money) so PayPal sends PAYMENT.PAYOUTS-ITEM.* to acctwatch and the light goes red.

    .venv/bin/python proof/scripts/stranger_sandbox_payout.py --to SANDBOX-PERSONAL@example.com --yes-trey-said-so

Then check: audit has acctwatch_event + acctwatch_timing (ms), the dashboard is red, and (if voice is set up)
the phone rings. Sandbox only; 1.00 USD of play money.
"""
import argparse
import json
import sys
import uuid

sys.path.insert(0, ".")
from bridge_warden.paypal_client import PayPalSandbox  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--to", required=True)
ap.add_argument("--yes-trey-said-so", action="store_true")
a = ap.parse_args()
if not a.yes_trey_said_so:
    sys.exit("Not run: this sends a sandbox payout and may ring Trey's phone. Ask Trey first.")
ref = "stranger-" + uuid.uuid4().hex[:12]
r = PayPalSandbox()._call("POST", "/v1/payments/payouts", {
    "sender_batch_header": {"sender_batch_id": ref, "email_subject": "Sandbox test"},
    "items": [{"recipient_type": "EMAIL", "receiver": a.to, "sender_item_id": ref,
               "amount": {"value": "1.00", "currency": "USD"}, "note": "acctwatch e2e proof"}]}, request_id=ref)
print(json.dumps({"payout_batch_id": (r.get("batch_header") or {}).get("payout_batch_id"), "ref": ref}))
