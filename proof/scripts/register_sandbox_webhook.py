"""NOT RUN. Needs Trey's yes. Registers ONE sandbox webhook pointing at your own HTTPS forwarder.

    .venv/bin/python proof/scripts/register_sandbox_webhook.py --url https://YOUR-TUNNEL/paypal/webhook --yes-trey-said-so

Prints only the new webhook id (not a secret). Put it in BW_PAYPAL_WEBHOOK_ID. Sandbox only: the client refuses live.
"""
import argparse
import json
import sys
from urllib.parse import urlsplit

sys.path.insert(0, ".")
from bridge_warden import acctwatch as W            # noqa: E402
from bridge_warden.paypal_client import PayPalSandbox  # noqa: E402

EVENTS = sorted(set(W.ALWAYS_RED) | set(W.MONEY_OUT) | set(W.MONEY_IN))

ap = argparse.ArgumentParser()
ap.add_argument("--url", required=True)
ap.add_argument("--yes-trey-said-so", action="store_true")
a = ap.parse_args()
u = urlsplit(a.url)
if u.scheme != "https" or not u.hostname or u.path != W.WEBHOOK_PATH:
    sys.exit("need https://<your host>" + W.WEBHOOK_PATH)
if not a.yes_trey_said_so:
    sys.exit("Not run: this creates a webhook in the PayPal sandbox app. Ask Trey first.")
c = PayPalSandbox()
r = c._call("POST", "/v1/notifications/webhooks",
            {"url": a.url, "event_types": [{"name": e} for e in EVENTS]})
print(json.dumps({"webhook_id": r.get("id"), "events": len(EVENTS)}))
