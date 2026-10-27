"""ACCTWATCH (2026-10-26): PayPal webhooks -> verified -> same checks -> red light + call at once. All mocked."""
import json
import statistics
import time
import urllib.request
from datetime import timedelta

import pytest

from conftest import NOON_ET
from test_v5_alerts import FakeTwilio, block
from bridge_warden import acctwatch as W
from bridge_warden import alerts as A
from bridge_warden import dashboard
from bridge_warden import notify as N


def hdr(tid="TX-00000001", at=NOON_ET, cert="https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1"):
    return {"PayPal-Auth-Algo": "SHA256withRSA", "PayPal-Cert-Url": cert, "PayPal-Transmission-Id": tid,
            "PayPal-Transmission-Sig": "c2ln", "PayPal-Transmission-Time": at.isoformat().replace("+00:00", "Z")}


def ev(eid="WH-0000000000000001", et="PAYMENT.PAYOUTS-ITEM.SUCCEEDED", value="900.00", **res):
    r = {"payout_item_id": "ITEM0000000001", "payout_item": {"amount": {"value": value, "currency": "USD"},
                                                             "receiver": "stranger@example.com"}, **res}
    if et.startswith("PAYMENT.CAPTURE"):
        r = {"id": "CAP000000001", "amount": {"value": value, "currency_code": "USD"}, **res}
    return json.dumps({"id": eid, "event_type": et, "resource": r}).encode()


class Verifier:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0

    def __call__(self, h, raw):
        self.calls += 1
        return self.ok


def watch(gate, ok=True, env=None, cancel=None):
    tw = FakeTwilio()
    al = A.Alerts(gate, caller=tw, email=A.EmailAlerter(env={}), clock=lambda: NOON_ET)
    v = Verifier(ok)
    return W.AccountWatch(gate, verifier=v, alerts=al, env=env or {}, clock=lambda: NOON_ET, cancel=cancel), v, tw


def test_verified_outside_payout_turns_red_and_calls_at_once(gate):
    w, v, tw = watch(gate)
    code, why, res = w.receive(hdr(), ev())
    assert (code, why) == (200, "ok") and res["red"] and v.calls == 1
    assert tw.n == 1 and "money may have moved" in tw.calls[0]
    assert "Nothing was sent" not in tw.calls[0]
    st = dashboard.status(gate)
    assert st["state"] == "red"
    ms = res["ms"]
    assert 0 <= ms["t_verified"] <= ms["t_checked"] <= ms["t_call_request"] < 2000
    t = [r for r in gate.audit.records() if r["event"] == "acctwatch_timing"]
    assert t and t[-1]["ms"] == ms
    assert (gate.audit.path.parent / "acctwatch_latency.jsonl").read_text().strip()


@pytest.mark.parametrize("et", ["CUSTOMER.DISPUTE.CREATED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED",
                                "RISK.DISPUTE.CREATED", "PAYMENT.PAYOUTS-ITEM.UNCLAIMED"])
def test_red_events(gate, et):
    w, _, tw = watch(gate)
    assert w.receive(hdr(), ev(et=et))[2]["red"] and tw.n == 1


def test_unverified_refused_nothing_red(gate):
    w, v, tw = watch(gate, ok=False)
    assert w.receive(hdr(), ev())[:2] == (400, "not verified by PayPal")
    assert tw.n == 0 and dashboard.status(gate)["state"] != "red"
    assert [r for r in gate.audit.records() if r["event"] == "acctwatch_refused"]


@pytest.mark.parametrize("h,why", [
    ({}, "missing PayPal headers"),
    ({"PayPal-Auth-Algo": "none"}, "wrong algorithm"),
    ({"PayPal-Cert-Url": "https://evil.example/cert"}, "cert not from PayPal sandbox"),
    ({"PayPal-Cert-Url": "https://api.paypal.com/cert"}, "cert not from PayPal sandbox"),     # live: refused
    ({"PayPal-Transmission-Id": "x"}, "bad transmission id"),
    ({"PayPal-Transmission-Time": (NOON_ET - timedelta(minutes=6)).isoformat()}, "too old or from the future (replay?)"),
])
def test_cheap_checks_before_paypal_is_asked(gate, h, why):
    w, v, _ = watch(gate)
    hh = {} if not h else {**hdr(), **h}
    assert w.receive(hh, ev())[:2] == (400, why) and v.calls == 0


def test_replay_and_duplicate_event(gate):
    w, v, tw = watch(gate)
    assert w.receive(hdr(), ev())[0] == 200
    assert w.receive(hdr(), ev())[:2] == (409, "replayed transmission")
    assert w.receive(hdr(tid="TX-00000002"), ev())[:2] == (200, "already handled")     # PayPal resend
    assert tw.n == 1


def test_dev_mode_never_asks_paypal(gate):
    gate.dev_lock = lambda: True
    w, v, tw = watch(gate)
    assert w.receive(hdr(), ev())[0] == 503 and v.calls == 0 and tw.n == 0


def test_no_webhook_id_means_not_set_up(gate):
    w = W.AccountWatch(gate, verifier=None, env={}, clock=lambda: NOON_ET)
    assert w.receive(hdr(), ev())[0] == 503
    assert W.PayPalVerifier(object(), "")(hdr(), ev()) is False


def test_verifier_embeds_raw_body():
    got = []

    class C:
        base = "https://api-m.sandbox.paypal.com"

        def token(self):
            return "tok"

    def sender(m, url, h, body, timeout):
        got.append((url, body))
        return 200, {}, b'{"verification_status": "SUCCESS"}'
    raw = b'{"id": "WH-1234567890", "z": 1.10,  "a": "b"}'                # odd spacing kept byte for byte
    h = {k.upper(): v for k, v in hdr().items()}
    assert W.PayPalVerifier(C(), "WEBHOOK123", sender)(h, raw)
    assert got[0][0].endswith("/v1/notifications/verify-webhook-signature") and raw in got[0][1]
    assert json.loads(got[0][1])["webhook_id"] == "WEBHOOK123"


def test_info_and_money_in(gate):
    w, _, tw = watch(gate)
    assert not w.receive(hdr(), ev(et="PAYMENT.CAPTURE.COMPLETED", value="5.00"))[2]["red"]
    assert w.receive(hdr(tid="TX-00000002"), ev(eid="WH-0000000000000002", et="PAYMENT.CAPTURE.COMPLETED",
                                                value="99999.00"))[2]["red"]
    assert not w.receive(hdr(tid="TX-00000003"), ev(eid="WH-0000000000000003", et="BILLING.PLAN.CREATED"))[2]["red"]
    assert tw.n == 1


def test_bridge_wardens_own_payout_is_not_red(gate):
    gate.audit.write("executed", action_id="act-1", result={"payout_batch_id": "BATCH0000001"})
    w, _, tw = watch(gate)
    res = w.receive(hdr(), ev(payout_batch_id="BATCH0000001"))[2]
    assert not res["red"] and tw.n == 0


def test_auto_cancel_off_by_default_on_when_asked(gate):
    seen = []
    w, _, _ = watch(gate, cancel=lambda i: seen.append(i) or {"transaction_status": "RETURNED"})
    assert w.receive(hdr(), ev(et="PAYMENT.PAYOUTS-ITEM.UNCLAIMED"))[2]["cancel"] == {"cancelled": False}
    assert seen == []
    w2, _, _ = watch(gate, env={"BW_ACCTWATCH_AUTOCANCEL": "on"}, cancel=lambda i: seen.append(i) or
                     {"transaction_status": "RETURNED"})
    r = w2.receive(hdr(tid="TX-00000002"), ev(eid="WH-0000000000000002", et="PAYMENT.PAYOUTS-ITEM.UNCLAIMED"))
    assert r[2]["cancel"] == {"cancelled": True} and seen == ["ITEM0000000001"]


def test_poller_off_by_default_dedupes(gate):
    class RO:
        def transactions(self, a, b):
            return [{"transaction_info": {"transaction_id": "TXN0001", "transaction_status": "S",
                                          "transaction_amount": {"value": "-400.00", "currency_code": "USD"}}}]
    w, _, tw = watch(gate)
    p = W.TransactionPoller(w, RO())
    assert p.once()[0]["red"] and p.once() == [] and tw.n == 1
    assert "3 hours" in p.LAG_NOTE


def test_server_loopback_only_and_end_to_end(gate):
    with pytest.raises(ValueError):
        W.make_server(watch(gate)[0], port=0, bind="0.0.0.0")
    w, _, tw = watch(gate)
    srv = W.make_server(w, port=0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        u = f"http://127.0.0.1:{srv.server_address[1]}"
        assert urllib.request.urlopen(u + "/healthz").status == 200
        req = urllib.request.Request(u + W.WEBHOOK_PATH, data=ev(), headers=hdr(), method="POST")
        assert urllib.request.urlopen(req).status == 200 and tw.n == 1
    finally:
        srv.shutdown()


def test_latency_well_under_two_seconds(gate):
    w, _, tw = watch(gate)
    for i in range(30):
        w.receive(hdr(tid=f"TX-{i:08d}"), ev(eid=f"WH-{i:016d}"))
    lat = [json.loads(x)["t_call_request"] for x in
           (gate.audit.path.parent / "acctwatch_latency.jsonl").read_text().splitlines()]
    assert len(lat) == 30 and tw.n == 30
    assert statistics.median(lat) < 200 and max(lat) < 2000


def test_notifier_loop_does_not_double_ring(gate):
    w, _, tw = watch(gate)
    n = N.Notifier(gate)
    n.caller = tw
    n.check()
    w.receive(hdr(), ev())
    n.check()
    assert tw.n == 1
