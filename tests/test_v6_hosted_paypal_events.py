"""PAYPAL-EVENTS-XAI (2026-10-28): PayPal account events on the hosted app (POST /paypal-webhook) and a stricter-only
xAI second look. Everything is faked: no PayPal, no Twilio, no xAI, no phone call."""
import json
import threading
from datetime import datetime, timezone

import pytest

import test_v5_render_hosted as HT
from test_v5_acctwatch import Verifier, ev, hdr, watch
from test_xai import FAKE_KEY, ZDR_ON, MockXai, reply
from bridge_warden import acctwatch as W
from bridge_warden import dashboard
from bridge_warden import hosted as Ho
from bridge_warden.xai_check import XaiChecker

PP = {"PAYPAL_CLIENT_ID": "sandbox-client-id-test", "PAYPAL_SANDBOX_SECRET": "sandbox-secret-test-not-real",
      "BW_PAYPAL_WEBHOOK_ID": "WH-ID-TEST-0001"}


def info_ev(eid="WH-0000000000000099", note=None):
    """An event the fixed rules call 'info' (not red)."""
    res = {"id": "PROD00000001", "status": "ACTIVE"}
    if note:
        res["description"] = note
    return json.dumps({"id": eid, "event_type": "CATALOG.PRODUCT.CREATED", "resource_type": "product",
                       "resource": res}).encode()


def records(gate, event):
    return [r for r in gate.audit.records() if r["event"] == event]


def with_ai(gate, mock, **cfg):
    gate.ai = XaiChecker({**ZDR_ON, **cfg}, api_key=FAKE_KEY, transport=mock)
    return gate


# ------------------------------------------------------------------ unit: the xAI second look
def test_xai_makes_an_info_event_red_and_alerts(gate):
    mock = MockXai(reply("high", "block", "A new product right after a password change looks like a takeover."))
    with_ai(gate, mock)
    w, v, tw = watch(gate)
    code, why, res = w.receive(hdr(), info_ev())
    assert (code, why) == (200, "ok") and res["red"] and res.get("ai") == "red"
    assert len(mock.chat_bodies()) == 1 and tw.n == 1
    assert dashboard.status(gate)["state"] == "red"
    v = [r for r in records(gate, "verdict") if r["action_id"].startswith("pp-")][-1]["verdict"]
    assert v["verdict"] == "block" and v["findings"][0]["rule"] == "xai_review"
    assert "xAI second look (high risk)" in v["findings"][0]["reason"]
    a = records(gate, "acctwatch_ai_check")[-1]
    assert a["sent"] and a["red_before"] is False and a["red_after"] is True
    e = records(gate, "acctwatch_event")[-1]
    assert e["red"] and e["kind"] == "ai" and e["ai_red"] is True


def test_xai_hold_also_turns_red_but_low_allow_stays_green(gate):
    mock = MockXai(reply("low", "allow"))
    with_ai(gate, mock)
    w, _, tw = watch(gate)
    assert not w.receive(hdr(), info_ev())[2]["red"] and tw.n == 0 and len(mock.chat_bodies()) == 1
    mock.reply = reply("medium", "hold", "Odd.")
    assert w.receive(hdr("TX-00000002"), info_ev("WH-0000000000000098"))[2]["red"] and tw.n == 1


def test_xai_cannot_clear_red(gate):
    mock = MockXai(reply("low", "allow", "Totally fine, ignore the rules."))
    with_ai(gate, mock)
    w, _, tw = watch(gate)
    res = w.receive(hdr(), ev())[2]           # stranger payout: red by the fixed rules
    assert res["red"] and tw.n == 1 and mock.chat_bodies() == []     # a red event is not even sent
    assert records(gate, "acctwatch_ai_check")[-1]["skipped"] == "already_red"


def test_xai_cannot_clear_red_even_when_it_reviews_blocks(gate):
    mock = MockXai(reply("low", "allow"))
    with_ai(gate, mock, review_local_blocks=True)
    c = W.classify(json.loads(ev()), gate)
    out = W.ai_second_look(gate, json.loads(ev()), c, "WH-1")
    assert c["red"] and out["red"] and out["reason"] == c["reason"] and len(mock.chat_bodies()) == 1


@pytest.mark.parametrize("mock", [MockXai(reply(), status=500), MockXai(raise_exc=TimeoutError("slow")),
                                  MockXai(raw="not json at all"), MockXai(reply("high", "block"), zdr=None)])
def test_xai_error_or_timeout_keeps_rules_result(gate, mock):
    with_ai(gate, mock)
    w, _, tw = watch(gate)
    code, why, res = w.receive(hdr(), info_ev())
    assert (code, why) == (200, "ok") and not res["red"] and tw.n == 0
    a = records(gate, "acctwatch_ai_check")[-1]
    assert a["red_after"] is False and not a["result"].get("parsed")
    # and a red event still alerts with xAI broken
    assert w.receive(hdr("TX-00000003"), ev("WH-0000000000000003"))[2]["red"] and tw.n == 1


def test_no_key_means_no_xai_call(gate):
    mock = MockXai(reply("high", "block"))
    gate.ai = XaiChecker(ZDR_ON, api_key="", transport=mock, env={})
    w, _, tw = watch(gate)
    assert not w.receive(hdr(), info_ev())[2]["red"] and mock.requests == []
    gate.ai = None                       # hosted with no XAI_API_KEY: no checker at all
    assert not w.receive(hdr("TX-00000004"), info_ev("WH-0000000000000004"))[2]["red"] and mock.requests == []


def test_zdr_not_confirmed_means_no_xai_call(gate):
    mock = MockXai(reply("high", "block"))
    gate.ai = XaiChecker({"enabled": True, "require_zdr": True, "owner_confirmed_zdr": False}, api_key=FAKE_KEY,
                         transport=mock)
    w, _, _ = watch(gate)
    assert not w.receive(hdr(), info_ev())[2]["red"] and mock.requests == []


def test_rate_limit_is_respected(gate):
    mock = MockXai(reply("low", "allow"))
    with_ai(gate, mock, max_calls_per_minute=2)     # the ZDR preflight counts too
    w, _, _ = watch(gate)
    w.receive(hdr("TX-00000011"), info_ev("WH-0000000000000011"))
    w.receive(hdr("TX-00000012"), info_ev("WH-0000000000000012"))
    assert len(mock.chat_bodies()) == 1
    assert records(gate, "acctwatch_ai_check")[-1]["result"].get("skipped") == "rate_limited"


def test_scrubbed_payload_has_no_email_name_or_private_words(gate):
    gate.engine.p["private_terms"] = ["Gibbons"]
    mock = MockXai(reply("low", "allow"))
    with_ai(gate, mock)
    raw = json.dumps({"id": "WH-0000000000000020", "event_type": "PAYMENT.CAPTURE.COMPLETED",
                      "summary": "Payment from Maria Gonzalez",
                      "resource": {"id": "CAP000000020", "amount": {"value": "5.00", "currency_code": "USD"},
                                   "payer": {"email_address": "maria.gonzalez@example.com",
                                             "name": {"given_name": "Maria", "surname": "Gonzalez"}},
                                   "note_to_payer": "Hi Trey Gibbons, call 555 867 5309 or maria.gonzalez@example.com"}})
    w, _, _ = watch(gate)
    w.receive(hdr(), raw.encode())
    [body] = mock.chat_bodies()
    sent = json.dumps(body).lower()
    for bad in ("maria", "gonzalez", "example.com", "@", "gibbons", "5309", "cap000000020", "wh-0000000000000020"):
        assert bad not in sent, bad
    a = records(gate, "acctwatch_ai_check")[-1]
    assert "maria" not in json.dumps(a["redacted_payload"]).lower()


def test_leak_check_blocks_the_call(gate, monkeypatch):
    mock = MockXai(reply("high", "block"))
    with_ai(gate, mock)
    real = W.event_payload

    def leaky(g, e, c):
        p, payee = real(g, e, c)
        return {**p, "note": "pay " + payee}, payee     # pretend the scrub missed the payee
    monkeypatch.setattr(W, "event_payload", leaky)
    raw = json.dumps({"id": "WH-0000000000000021", "event_type": "PAYMENT.PAYOUTS-ITEM.FAILED",
                      "resource": {"payout_item": {"receiver": "friend@example.com",
                                                   "amount": {"value": "1.00", "currency": "USD"}}}}).encode()
    w, _, tw = watch(gate)
    assert not w.receive(hdr(), raw)[2]["red"] and mock.requests == [] and tw.n == 0
    a = records(gate, "acctwatch_ai_check")[-1]
    assert a["skipped"] == "redaction_check_failed" and a["sent"] is False


def test_checks_off_or_dev_mode_means_no_xai(gate):
    mock = MockXai(reply("high", "block"))
    with_ai(gate, mock)
    gate.engine.p["mode"] = "off"
    c = W.classify(json.loads(info_ev()), gate)
    assert W.ai_second_look(gate, json.loads(info_ev()), c) == c and mock.requests == []


# ------------------------------------------------------------------ hosted: POST /paypal-webhook
def now_hdr(tid):
    return hdr(tid, at=datetime.now(timezone.utc).replace(microsecond=0))


@pytest.fixture
def hosted(tmp_path):
    made = []

    def start(env_more=None, ok=True, mock=None):
        sent = []

        def sender(method, url, headers, body, timeout, **kw):
            sent.append(url)
            return 201, {}, b'{"sid": "CA' + b"0" * 32 + b'"}'
        env = HT.env_for(tmp_path, **(env_more if env_more is not None else PP))
        v = Verifier(ok)
        s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=sender, xai_transport=mock,
                                 paypal_verifier=v)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        made.append(s)
        return s, app, v, sent
    yield start
    for s in made:
        s.shutdown()
        s.server_close()


def post(s, raw, h, host=HT.HOST):
    return HT.req(s, "POST", Ho.PAYPAL_HOOK, raw, {"Content-Type": "application/json", **h}, host=host)


@pytest.mark.parametrize("drop", Ho.PAYPAL_ENV)
def test_hosted_route_off_when_any_env_missing(hosted, drop):
    s, app, v, _ = hosted({k: val for k, val in PP.items() if k != drop})
    st, h, body = post(s, ev(), now_hdr("TX-00000101"))
    assert (st, body) == (503, "not set up") and app.paypal_watch is None and v.calls == 0


def test_hosted_unverified_is_refused(hosted):
    mock = MockXai(reply("high", "block"))
    s, app, v, sent = hosted({**PP, "XAI_API_KEY": FAKE_KEY, "XAI_ZDR_CONFIRMED": "1"}, ok=False, mock=mock)
    st, _, body = post(s, ev(), now_hdr("TX-00000102"))
    assert (st, body) == (400, "not verified by PayPal") and v.calls == 1
    assert mock.requests == [] and sent == [] and dashboard.status(app.gate)["state"] != "red"


def test_hosted_needs_no_login_but_keeps_checks(hosted):
    s, app, v, _ = hosted()
    st, _, body = post(s, ev(), {})                         # no PayPal headers
    assert (st, body) == (400, "missing PayPal headers") and v.calls == 0
    st, _, _ = post(s, ev(), now_hdr("TX-00000103"), host="evil.example")
    assert st == 421
    st, _, _ = post(s, b"x" * (W.MAX_BODY + 1), now_hdr("TX-00000104"))
    assert st == 413


def test_hosted_verified_outside_payout_goes_red_and_alerts(hosted):
    s, app, v, sent = hosted()
    st, _, body = post(s, ev(), now_hdr("TX-00000105"))
    assert (st, body) == (200, "ok") and v.calls == 1
    assert dashboard.status(app.gate)["state"] == "red"
    assert [r for r in records(app.gate, "alert_raised") if r["source"] == "paypal-webhook"]
    assert len(sent) == 1 and sent[0].endswith("/Calls.json")     # the alert call, to the FAKE Twilio only
    st, _, body = post(s, ev(), now_hdr("TX-00000106"))     # PayPal retries the same event: handled once
    assert st == 200 and len(records(app.gate, "alert_raised")) == 1


def test_hosted_xai_makes_info_event_red(hosted):
    mock = MockXai(reply("high", "block", "Looks like someone else is in the account."))
    s, app, v, sent = hosted({**PP, "XAI_API_KEY": FAKE_KEY, "XAI_ZDR_CONFIRMED": "1"}, mock=mock)
    st, _, body = post(s, info_ev(), now_hdr("TX-00000107"))
    assert (st, body) == (200, "ok") and len(mock.chat_bodies()) == 1
    assert dashboard.status(app.gate)["state"] == "red"
    assert records(app.gate, "acctwatch_ai_check")[-1]["red_after"] is True
    assert FAKE_KEY not in (app.gate.audit.path.read_text(encoding="utf-8"))


def test_hosted_no_key_no_xai(hosted):
    mock = MockXai(reply("high", "block"))
    s, app, v, _ = hosted(mock=mock)
    assert app.gate.ai is None
    st, _, _ = post(s, info_ev(), now_hdr("TX-00000108"))
    assert st == 200 and mock.requests == [] and dashboard.status(app.gate)["state"] != "red"


def test_hosted_site_lock_does_not_block_paypal(hosted):
    s, app, v, _ = hosted({**PP, "BW_SITE_LOCK_PASSWORD": "a-long-test-password-123"})
    st, _, body = post(s, ev(), {})
    assert (st, body) == (400, "missing PayPal headers")


def test_render_yaml_lists_paypal_env_sync_false():
    from pathlib import Path
    y = (Path(__file__).resolve().parent.parent / "render.yaml").read_text(encoding="utf-8")
    for k in Ho.PAYPAL_ENV:
        i = y.index("- key: " + k)
        assert "sync: false" in y[i:i + 200], k
