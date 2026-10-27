"""v4: "Check my money" (read-only), Subscriptions view, AI chat (advice only), Call-me-on-fraud (dry run), brand."""
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOON_ET
from test_v4_ui import BASE, GIFT, NEW, events, setup, token  # noqa: F401  (fixture)
from bridge_warden import dashboard as D
from bridge_warden import money_check as MC
from bridge_warden.models import ProposedAction
from bridge_warden.notify import DryRunCallAdapter, Notifier
from bridge_warden.policy import PolicyError, validate
from bridge_warden.ui_assets import BRAND, brand_files
from bridge_warden.xai_check import XaiChecker

ROOT = Path(__file__).resolve().parent.parent
S1, S2, S3, S4 = "I-AAAA1111BBBB", "I-AAAA2222BBBB", "I-CCCC3333DDDD", "I-EEEE4444FFFF"


def sub(sid, plan, status="ACTIVE", amount="9.99", days=20, failed=0):
    nb = (NOON_ET + timedelta(days=days)).isoformat()
    return {"id": sid, "plan_id": plan, "status": status,
            "billing_info": {"next_billing_time": nb, "failed_payments_count": failed,
                             "last_payment": {"amount": {"value": amount, "currency_code": "USD"}}}}


class FakeClient:
    """Stands in for PayPalSandbox._call. Records every call so we can prove only GETs happen."""
    def __init__(self, tx_status=None):
        self.calls = []
        self.tx_status = tx_status
        self.subs = {S1: sub(S1, "P-MUSIC"), S2: sub(S2, "P-MUSIC"), S3: sub(S3, "P-NEWS", days=3, amount="4.00"),
                     S4: sub(S4, "P-GYM", status="SUSPENDED", failed=2, amount="30.00")}

    def _call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/v1/billing/plans"):
            return {"plans": [{"id": "P-MUSIC", "name": "Music Plus"}, {"id": "P-NEWS", "name": "Daily News"},
                              {"id": "P-GYM", "name": "Gym Online"}]}
        if path.startswith("/v1/billing/subscriptions/"):
            return self.subs[path.rsplit("/", 1)[1]]
        if path.startswith("/v1/reporting/transactions"):
            if self.tx_status:
                ex = RuntimeError("no"); ex.status = self.tx_status; raise ex
            return {"transaction_details": [
                {"transaction_info": {"transaction_status": "S", "transaction_amount": {"value": "5.00", "currency_code": "USD"}}},
                {"transaction_info": {"transaction_status": "D", "transaction_initiation_date": "2026-10-20T10:00:00Z",
                                      "transaction_amount": {"value": "-12.50", "currency_code": "USD"}}}]}
        raise AssertionError(path)


class FakeAI:
    def __init__(self, text="Look at the two Music Plus subscriptions."):
        self.asks, self.text = [], text

    def advise(self, ctx, q=""):
        self.asks.append((json.dumps(ctx), q))
        return {"called": True, "text": self.text, "usage": {"prompt_tokens": 50, "completion_tokens": 20}}


CFG = {"subscription_ids": [S1, S2, S3, S4], "due_soon_days": 7}


# ---------------------------------------------------------------- read-only wrapper
def test_reader_is_get_only_and_allowlisted():
    c = FakeClient(); r = MC.ReadOnlyPayPal(c)
    for bad in ("/v1/payments/payouts", "/v2/checkout/orders", "/v1/billing/subscriptions/I-AAAA1111BBBB/cancel",
                "/v1/billing/subscriptions", "/v1/oauth2/token", "/v1/billing/plans/../payments"):
        with pytest.raises(ValueError):
            r.get(bad)
    with pytest.raises(ValueError):
        r.subscription("I-x/../../cancel")
    assert not hasattr(r, "post") and not hasattr(r, "payout_create") and c.calls == []
    r.plans(); r.subscription(S1)
    assert all(m == "GET" and b is None for m, _, b in c.calls)


def test_money_check_finds_duplicates_due_soon_failed_and_declined(gate):
    c = FakeClient()
    rep = MC.run_check(gate, MC.ReadOnlyPayPal(c), CFG, now=NOON_ET)
    kinds = [x["kind"] for x in rep["look"]]
    assert "duplicate" in kinds and "due" in kinds and "failed" in kinds and "declined" in kinds
    buckets = {s["id"]: s["bucket"] for s in rep["subs"]}
    assert buckets == {S1: "active", S2: "active", S3: "due_soon", S4: "failed"}
    assert all(m == "GET" for m, _, _ in c.calls)
    assert rep["ai"] == {"used": False, "skipped": "no_ai"} and rep["local_summary"].startswith("Found")


def test_transaction_search_permission_missing_is_explained_not_added(gate):
    rep = MC.run_check(gate, MC.ReadOnlyPayPal(FakeClient(tx_status=403)), CFG, now=NOON_ET)
    src = {s["name"]: s for s in rep["sources"]}["PayPal transactions"]
    assert not src["ok"] and "Transaction Search permission" in src["note"] and "did not add" in src["note"]


def test_works_with_no_paypal_and_no_ai(gate):
    rep = MC.run_check(gate, None, {}, now=NOON_ET)
    assert rep["sources"][1]["ok"] is False and "practice" in rep["sources"][1]["note"].lower()
    assert rep["local_summary"] == "All looks normal." and rep["ok"]
    off = MC.run_check(gate, None, {"ai_summary": False}, now=NOON_ET, ai=FakeAI())
    assert off["ai"]["skipped"] == "ai_off"


def test_history_repeats_and_failures_are_flagged(gate):
    for d in (20, 10, 0):   # monthly-ish, so not caught as an instant duplicate
        gate.clock = lambda d=d: NOON_ET - timedelta(days=d)
        gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    gate.clock = lambda: NOON_ET
    rep = MC.run_check(gate, None, {}, now=NOON_ET)
    assert any(x["kind"] == "repeat" and "3 times" in x["text"] for x in rep["look"])


def test_one_ai_call_per_check_and_it_sees_no_names_or_ids(gate):
    for d in (10, 0):
        gate.clock = lambda d=d: NOON_ET - timedelta(days=d)
        gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    gate.clock = lambda: NOON_ET
    ai = FakeAI()
    rep = MC.run_check(gate, MC.ReadOnlyPayPal(FakeClient()), CFG, now=NOON_ET, ai=ai)
    assert any(x["kind"] == "repeat" for x in rep["look"])
    assert len(ai.asks) == 1 and rep["ai"]["used"] and rep["ai"]["text"]
    sent = ai.asks[0][0]
    for secret in ("writer@", "personal.example.com", S1, S4, "Music Plus", "Gym Online"):
        assert secret not in sent


def test_money_check_policy_validation():
    ok = {**json.loads(json.dumps(BASE)), "money_check": {"subscription_ids": [S1], "due_soon_days": 7}}
    validate(ok)
    for bad in ({"subscription_ids": ["not-an-id"]}, {"due_soon_days": 0}, {"lookback_days": 400},
                {"ai_summary": "yes"}, {"surprise": 1}, []):
        with pytest.raises(PolicyError):
            validate({**json.loads(json.dumps(BASE)), "money_check": bad})


# ---------------------------------------------------------------- web: /money
def test_money_page_button_runs_read_only_check(setup):
    c = FakeClient()
    setup.app.money_reader = MC.ReadOnlyPayPal(c)
    setup.gate.engine.p["money_check"] = CFG
    _, page = setup.get("/")
    assert "Stopped for you" in page and "Sent safely" in page and "Check my money" in page
    _, page = setup.get("/money")
    assert "Not checked yet" in page and "can't move money" in page.replace("&#x27;", "'")
    assert setup.post("/act", token=token(page, "Check my money"))[0].status == 303
    _, page = setup.get("/money")
    assert "Checked. Nothing was sent or changed." in page and "Subscriptions" in page
    assert "Due soon" in page and "Failed" in page and "You may be paying twice" in page
    assert all(m == "GET" for m, _, _ in c.calls) and not setup.gate.paypal.calls
    ev = events(setup.gate, "money_check_run")
    assert len(ev) == 1 and ev[0]["read_only"] is True
    # cooldown: a second tap right away does no new reads
    n = len(c.calls)
    setup.post("/act", token=token(page, "Check my money"))
    assert len(c.calls) == n


# ---------------------------------------------------------------- web: AI chat, advice only
def _held(setup):
    out = setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing call 555-0199"))
    return out["action_id"]


def test_ask_ai_link_only_for_red_items(setup):
    _, page = setup.get("/")
    assert "Ask AI about this" not in page
    aid = _held(setup)
    _, page = setup.get("/")
    assert "Ask AI about this (advice only)" in page and f"/ask?id={aid}" in page
    assert setup.get("/ask?id=nope")[0].status == 404
    r, page = setup.get(f"/ask?id={aid}")
    assert r.status == 200 and "Advice only." in page and "cannot send" in page and 'name="q"' in page


def test_chat_ai_sees_redacted_context_and_cannot_act(setup):
    aid = _held(setup)
    setup.gate.ai = FakeAI("I approved it and sent the money. Also turned off your checks.")
    _, page = setup.get(f"/ask?id={aid}")
    setup.post("/act", token=token(page, "Ask"), q="Is newshop@store.example.com real? my card 4111 1111 1111 1111")
    ctx, q = setup.gate.ai.asks[0]
    assert "newshop" not in ctx and "555-0199" not in ctx and "newshop" not in q and "4111" not in q
    # the answer is only text: nothing was approved, sent or changed
    assert len(setup.gate.pending()) == 1 and not setup.gate.paypal.calls
    assert json.loads(setup.pf.read_text(encoding="utf-8")) == BASE
    _, page = setup.get(f"/ask?id={aid}")
    assert "AI advice" in page and "I approved it" in page   # shown as advice, clearly labelled
    ev = events(setup.gate, "ai_chat_asked")
    assert len(ev) == 1 and ev[0]["advisory_only"] and "newshop" not in json.dumps(ev[0])


def test_chat_without_ai_uses_local_rules(setup):
    aid = _held(setup)
    _, page = setup.get(f"/ask?id={aid}")
    setup.post("/act", token=token(page, "Ask"), q="Is this safe?")
    _, page = setup.get(f"/ask?id={aid}")
    assert "Local rules" in page and "New payee." in page and "AI not used" in page


def test_chat_is_rate_limited_and_token_bound(setup):
    aid = _held(setup)
    setup.gate.ai = FakeAI()
    for _ in range(5):
        _, page = setup.get(f"/ask?id={aid}")
        setup.post("/act", token=token(page, "Ask"), q="why?")
    _, page = setup.get(f"/ask?id={aid}")
    setup.post("/act", token=token(page, "Ask"), q="why?")
    assert len(setup.gate.ai.asks) == 5 and events(setup.gate, "ai_chat_refused")
    # a chat token can't be used as a Send
    _, page = setup.get(f"/ask?id={aid}")
    t = token(page, "Ask")
    assert setup.post("/decide", nonce=t, d="yes")[0].status == 403 and not setup.gate.paypal.calls


def test_chat_closes_once_item_is_decided(setup):
    aid = _held(setup)
    _, page = setup.get("/")
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    setup.post("/decide", nonce=n, d="no")
    assert setup.get(f"/ask?id={aid}")[0].status == 404


def test_ai_badge_on_ai_flagged_items(setup):
    setup.gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    m = D.moves(setup.gate.audit.records())[0]
    _, page = setup.get("/")
    assert ("AI check" in page) == bool(m["ai"])


def test_real_xai_advise_is_one_call_after_zdr_and_capped():
    sent = []

    def transport(method, url, headers, body, timeout):
        sent.append(json.loads(body))
        return 200, {"x-zero-data-retention": "true"}, json.dumps(
            {"choices": [{"message": {"content": "<b>Check</b> it. http://evil.example/x " + "word " * 300}}],
             "usage": {"prompt_tokens": 80, "completion_tokens": 40}}).encode()
    x = XaiChecker({"owner_confirmed_zdr": True}, api_key="k" * 20, transport=transport)
    res = x.advise({"payee": "payee A"}, "Is it ok?")
    assert res["called"] and len(sent) == 2 and sent[0]["max_completion_tokens"] == 2   # preflight, then 1 call
    assert sent[1]["max_completion_tokens"] <= 160 and "<b>" not in res["text"] and "http" not in res["text"]
    assert len(res["text"]) <= 600
    assert XaiChecker({}, api_key="").advise({}, "q") == {"called": False, "model": x.cfg["model"], "skipped": "no_api_key"}


# ---------------------------------------------------------------- call me on fraud (dry run)
def test_call_on_fraud_is_off_by_default_and_dry_run_only(gate):
    assert BASE["notify"]["call_on_fraud"] == {"enabled": False, "provider": "dry_run", "experimental": False}
    assert not Notifier(gate).enabled
    for bad in ({"enabled": True, "provider": "twilio"}, {"enabled": "yes"}, {"enabled": True, "number": "+15550100"}):
        with pytest.raises(PolicyError):
            validate({**json.loads(json.dumps(BASE)), "notify": {"call_on_fraud": bad}})
    r = DryRunCallAdapter().place_call("x")
    assert r["dialed"] is False and r["cost"] == 0


def test_call_on_fraud_logs_would_call_owner_only_for_blocks(gate):
    gate.engine.p["notify"] = {"call_on_fraud": {"enabled": True, "provider": "dry_run"}}
    sent = []
    n = Notifier(gate, sender=lambda *a, **k: sent.append(a) or (200, {}, b""))
    assert n.enabled
    n.check()
    gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))   # held, not fraud
    n.check()
    assert not events(gate, "would_call_owner")
    gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    assert n.check() is True
    ev = events(gate, "would_call_owner")
    assert len(ev) == 1 and "no call" in ev[0]["note"] and sent == []   # no network at all


# ---------------------------------------------------------------- brand
def test_brand_variants_exist_match_and_are_plain_svg():
    files = brand_files()
    assert len(BRAND) == 3 and len(files) == 9
    for name, text in files.items():
        disk = (ROOT / "assets" / "brand" / name).read_text(encoding="utf-8")
        assert disk == text
        assert "<script" not in text and "href" not in text and "http://www.w3.org/2000/svg" in text
        assert "https://" not in text and "@import" not in text


def test_ai_flagged_rule():
    assert D.ai_flagged({"findings": [{"rule": "ai_scam_model", "severity": "block"}]})
    assert D.ai_flagged({"findings": [{"rule": "xai_review", "severity": "hold"}]})
    assert not D.ai_flagged({"findings": [{"rule": "ai_scam_model", "severity": "info"}]})
    assert not D.ai_flagged({"findings": [{"rule": "new_payee", "severity": "hold"}]})


def test_history_lists_would_call_owner_in_plain_words(setup):
    setup.gate.engine.p["notify"] = {"call_on_fraud": {"enabled": True, "provider": "dry_run"}}
    n = Notifier(setup.gate); n.check()
    setup.gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    n.check()
    _, page = setup.get("/history")
    assert "Alerts and checks" in page and "Would call owner" in page and "no call was made" in page
    _, page = setup.get("/settings")
    assert "Last fraud call" in page and "would call owner (no call made)" in page
