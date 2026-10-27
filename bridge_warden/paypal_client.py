"""Minimal PayPal REST client. SANDBOX ONLY.

The client secret is read from the PAYPAL_SANDBOX_SECRET environment variable at runtime.
It is never printed, logged or written to disk by this code.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

from . import net
from .guard import CAPTURE_ID, scrub

SANDBOX = "https://api-m.sandbox.paypal.com"
# Public test card from PayPal's sandbox docs. Lets a demo order complete without a browser login.
SANDBOX_TEST_CARD = {"number": "4111111111111111", "expiry": "2030-12", "security_code": "123", "name": "Sandbox Buyer"}


TIMEOUT = 30
RETRIES = 2  # only for 429/5xx/network errors, always with the SAME PayPal-Request-Id (PayPal de-duplicates)


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: dict):
        body = body if isinstance(body, dict) else {}
        self.status = status
        self.body = {k: scrub(str(body[k]))[:300] for k in ("name", "message", "debug_id") if k in body}
        super().__init__(f"PayPal API error {status}: {self.body.get('name')} {self.body.get('message', '')}".strip())


def _safe_id(value, what: str) -> str:
    """Ids go into URL paths. Only plain letters, digits and dashes; never '../' or '?'."""
    if not isinstance(value, str) or not CAPTURE_ID.match(value):
        raise ValueError(f"invalid {what}")
    return value


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"name": "NON_JSON_RESPONSE"}


class PayPalSandbox:
    def __init__(self, client_id: str | None = None, secret: str | None = None, base_url: str = SANDBOX):
        if base_url.rstrip("/") != SANDBOX:
            raise ValueError("This build only talks to the PayPal sandbox.")
        self.base = SANDBOX
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self._secret = secret or os.environ.get("PAYPAL_SANDBOX_SECRET", "")
        if not self.client_id or not self._secret:
            raise RuntimeError("Set PAYPAL_CLIENT_ID and PAYPAL_SANDBOX_SECRET (sandbox app credentials).")
        self._token, self._token_exp = None, 0.0

    def __repr__(self) -> str:  # never show the secret
        return f"PayPalSandbox(client_id={self.client_id[:6]}..., base={self.base})"

    # --- transport -------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None, request_id: str | None = None) -> dict:
        """Every call: pinned sandbox host, TLS verified, no redirects, 30 s timeout, retries with the same
        PayPal-Request-Id (so a retry can never pay twice), errors scrubbed of secrets."""
        headers = {"Authorization": "Bearer " + self.token(), "Content-Type": "application/json",
                   "PayPal-Request-Id": request_id or str(uuid.uuid4())}
        data = json.dumps(body).encode() if body is not None else None
        status, _, raw = net.request(method, self.base + path, headers, data, TIMEOUT, retries=RETRIES)
        if status >= 400:
            raise PayPalError(status, _json(raw))
        return _json(raw)

    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self._secret}".encode()).decode()
        status, _, raw = net.request("POST", self.base + "/v1/oauth2/token", {
            "Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"},
            b"grant_type=client_credentials", TIMEOUT, retries=RETRIES)
        out = _json(raw)
        if status >= 400 or not isinstance(out.get("access_token"), str):
            raise PayPalError(status if status >= 400 else 502, {"name": "AUTH_FAILED"})
        self._token, self._token_exp = out["access_token"], time.time() + int(out.get("expires_in", 300))
        return self._token

    # --- money actions (only ever called by the gate after a pass) --------
    def create_and_capture_order(self, amount: str, currency: str, description: str, ref: str) -> dict:
        """Orders v2: create a CAPTURE order paid with the sandbox test card, then make sure it is captured."""
        order = self._call("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": ref[:256], "description": description[:127] or "Agent purchase",
                                "custom_id": ref[:127],
                                "amount": {"currency_code": currency, "value": amount}}],
            "payment_source": {"card": SANDBOX_TEST_CARD},
        }, request_id=ref + "-order")
        if order.get("status") != "COMPLETED":
            order = self._call("POST", f"/v2/checkout/orders/{_safe_id(order.get('id'), 'order id')}/capture", {}, request_id=ref + "-capture")
        cap = order["purchase_units"][0]["payments"]["captures"][0]
        return {"order_id": order["id"], "order_status": order["status"],
                "capture_id": cap["id"], "capture_status": cap["status"]}

    def payout(self, amount: str, currency: str, receiver_email: str, note: str, ref: str) -> dict:
        """Payouts v1: send money to an email address."""
        out = self._call("POST", "/v1/payments/payouts", {
            "sender_batch_header": {"sender_batch_id": ref[:127], "email_subject": "You have a payment"},
            "items": [{"recipient_type": "EMAIL", "receiver": receiver_email, "note": (note or "Payment")[:4000],
                       "sender_item_id": ref[:63], "amount": {"value": amount, "currency": currency}}],
        }, request_id=ref + "-payout")
        hdr = out["batch_header"]
        return {"payout_batch_id": hdr["payout_batch_id"], "batch_status": hdr["batch_status"]}

    def payout_status(self, batch_id: str) -> dict:
        out = self._call("GET", f"/v1/payments/payouts/{_safe_id(batch_id, 'payout batch id')}")
        items = out.get("items") or [{}]
        return {"payout_batch_id": batch_id, "batch_status": out["batch_header"]["batch_status"],
                "item_status": items[0].get("transaction_status")}

    def refund(self, capture_id: str, amount: str, currency: str, ref: str) -> dict:
        """Payments v2: refund a capture (full or partial)."""
        out = self._call("POST", f"/v2/payments/captures/{_safe_id(capture_id, 'capture id')}/refund",
                         {"amount": {"value": amount, "currency_code": currency}, "note_to_payer": "Refund"},
                         request_id=ref + "-refund")
        return {"refund_id": out["id"], "refund_status": out["status"]}
