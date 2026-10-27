"""v4 price sanity (Channel3, pluggable). Soft check: only ever HOLDs. Mocked: no network, no key."""
import json

from test_v4_ui import NEW, setup  # noqa: F401  (fixture)
from bridge_warden import controls, net, price_check as PC
from bridge_warden.models import ALLOW, HOLD, ProposedAction

KEY = "c3_SECRET_key_value_987"


def fake_channel3(prices, code=200):
    sent = []
    def send(method, url, headers, body, timeout, **kw):
        sent.append({"method": method, "url": url, "headers": headers, "body": json.loads(body), **kw})
        prods = [{"id": f"p{i}", "title": "x", "offers": [{"price": {"amount": p, "currency": "USD"},
                                                           "condition": "new", "availability": "InStock"}]}
                 for i, p in enumerate(prices)]
        return code, {}, json.dumps({"products": prods}).encode()
    return send, sent


def gate_with(setup, prices, code=200):
    send, sent = fake_channel3(prices, code)
    setup.gate.prices = PC.Channel3Prices(env={PC.ENV_KEY: KEY}, sender=send)
    t = setup.gate.engine.p.setdefault("known_payees", [])
    if NEW not in t:
        t.append(NEW)
    return sent


def buy(amount, text="Buying a brand-new PlayStation 5 console from marketplace seller"):
    return ProposedAction("payout", amount, "USD", NEW, text)


def test_off_without_key():
    assert PC.from_env({}) is None
    assert PC.from_env({PC.ENV_KEY: KEY}).ready
    assert KEY not in repr(PC.from_env({PC.ENV_KEY: KEY}))


def test_query_is_redacted_product_words_only():
    q = PC.product_query("Buying PS5 Slim console from bob.smith@mail.example for $40, call 555-123-4567, "
                         "see https://evil.example/x secretproject", "bob.smith@mail.example", ["secretproject"])
    assert q and "bob" not in q.lower() and "@" not in q and "555" not in q and "http" not in q
    assert "secretproject" not in q.lower() and "40" not in q and "console" in q.lower()
    assert PC.product_query("Blog post payout, October") is None   # not a purchase: no lookup at all


def test_way_below_market_is_held_with_plain_reason(setup):
    sent = gate_with(setup, [499, 520, 480, 510])
    r = setup.gate.propose(buy("40.00"))
    assert r["verdict"] == HOLD and any("far below what stores ask" in x for x in r["reasons"])
    assert len(sent) == 1 and sent[0]["url"] == PC.URL and sent[0]["extra_host"] == "api.trychannel3.com"
    assert "40" not in json.dumps(sent[0]["body"]) and NEW not in json.dumps(sent[0]["body"])
    rec = [x for x in setup.gate.audit.records() if x["event"] == "price_check"][-1]
    assert rec["flagged"] and KEY not in json.dumps(setup.gate.audit.records())


def test_fair_price_passes_and_too_few_offers_never_flags(setup):
    gate_with(setup, [52, 55, 50])
    r = setup.gate.propose(buy("45.00", "Buying a used PlayStation controller from marketplace seller"))
    assert not any("far below what stores ask" in x for x in r["reasons"])
    assert not [x for x in setup.gate.audit.records() if x["event"] == "price_check"][-1]["flagged"]
    assert PC.judge("450.00", "USD", [499, 520, 480]) is None
    assert PC.judge("40.00", "USD", [499, 520]) is None          # need 3+ store prices
    assert PC.judge("40.00", "USD", [499, 520, 480]).severity == HOLD


def test_errors_and_off_switch_never_loosen_or_block(setup):
    gate_with(setup, [], code=500)
    r = setup.gate.propose(buy("40.00"))
    assert r["verdict"] in (ALLOW, HOLD) and r.get("status") != "blocked"
    rec = [x for x in setup.gate.audit.records() if x["event"] == "price_check"][-1]
    assert "500" in rec["result"]["error"] and KEY not in rec["result"]["error"]
    sent = gate_with(setup, [499, 520, 480])
    setup.gate.engine.p.setdefault("checks", {})["price_sanity"] = False
    setup.gate.propose(buy("41.00"))
    assert sent == []   # switched off: no lookup


def test_soft_tier_and_host_is_opt_in_only():
    assert controls.tier("price_sanity") == "soft"
    assert "api.trychannel3.com" in net.OPT_IN_HOSTS
    import pytest
    with pytest.raises(net.BlockedTarget):
        net.check_url(PC.URL)                       # not reachable without the explicit opt-in
    assert net.check_url(PC.URL, extra_host=PC.HOST) == PC.URL
