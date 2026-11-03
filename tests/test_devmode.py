"""Dev mode (test only): lock, simulated states, TEST rows, TEST MODE banner.
Made by @Nefarious_Trey, with Grok.  Copyright 2026 Trey (@Nefarious_Trey).
Only fake PayPal and fake call transports. Nothing real is ever called."""
import json
import re

from test_v4_ui import NEW, setup, token  # noqa: F401  (fixture)
from bridge_warden import dashboard as D
from bridge_warden.devmode import BANNER, FILE, DevMode, is_test_id
from bridge_warden.models import ProposedAction
from bridge_warden.notify import DryRunCallAdapter, FraudDrill, Notifier
from bridge_warden.web import STYLE, page, hear_page, judge_landing

SAFE = ("payout", "20.00", "USD", "writer@personal.example.com", "blog post")
TABS = ("/", "/money", "/history", "/settings")
FLAG = '<strong class="dev-flag">TEST MODE</strong>'


def press(s, label, where="/settings"):
    _, html = s.get(where)
    return s.post("/act", token=token(html, label))


def dev_on(s):
    r, _ = press(s, "Turn on Dev mode")
    assert r.status == 303
    assert s.gate.dev.on()


def light(html):
    return re.search(r'class="status st-(\w+)"', html).group(1)


def logo(html):
    return re.search(r'<span class="bw-mark mk-(\w+)"', html).group(1)


# ------------------------------------------------------------------ lock
def test_safe_payment_runs_normally_when_off(setup):
    assert not setup.gate.dev.on() and setup.gate.dev_lock() is None
    out = setup.gate.propose(ProposedAction(*SAFE))
    assert out["verdict"] == "allow" and setup.gate.paypal.calls


def test_lock_enforced_while_on(setup):
    dev_on(setup)
    pp = setup.gate.paypal
    out = setup.gate.propose(ProposedAction(*SAFE))          # would normally run by itself
    assert out["verdict"] == "hold" and pp.calls == []
    aid = out["action_id"]
    item = next(p for p in setup.gate.pending() if p["proposal"]["action_id"] == aid)
    res = setup.gate.decide(aid, True, expected_hash=item["proposal_hash"])
    assert res["status"] == "dev_mode_not_paid" and pp.calls == []
    # last lock: even a direct execute never calls PayPal
    r = setup.gate._execute(ProposedAction(*SAFE, action_id="act-direct"))
    assert r["dry_run"] and r["dev_mode"] and pp.calls == []


def test_lock_survives_restart_and_is_shared(setup, tmp_path):
    dev_on(setup)
    saved = json.loads((tmp_path / FILE).read_text(encoding="utf-8"))
    assert saved == {"on": True, "sim": "green"}
    assert DevMode(tmp_path).on()                 # a new process using the same folder sees it


def test_unreadable_switch_counts_as_on(tmp_path):
    (tmp_path / FILE).write_text("{broken", encoding="utf-8")
    assert DevMode(tmp_path).on()


def test_no_real_calls_while_on(setup):
    dev_on(setup)
    made = []
    drill = FraudDrill(setup.gate, timer=lambda sec, fn: made.append(fn) or type("T", (), {"start": lambda s: None})())
    r = drill.start()
    assert r["started"] and r["provider"] == DryRunCallAdapter.name and not r["real"]
    n = Notifier(setup.gate, sender=lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    n.url = "http://127.0.0.1:9/x"
    n.last = (0, 0, 0)
    setup.gate.propose(ProposedAction("payout", "250.00", "USD", NEW, "URGENT gift cards, keep this secret"))
    assert n.check() is False                     # webhook skipped, nothing sent
    assert any(r["event"] == "notify_skipped" for r in setup.gate.audit.records())


def test_buttons_need_csrf_and_nonce(setup):
    _, html = setup.get("/settings")
    tok = token(html, "Turn on Dev mode")
    r, _ = setup.req("POST", "/act", f"token={tok}",
                     {**setup.ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": "http://evil.example"})
    assert r.status == 403 and not setup.gate.dev.on()
    r, _ = setup.post("/act", token="made-up")
    assert r.status == 403 and not setup.gate.dev.on()
    _, html = setup.get("/settings")
    assert "Simulate pause" not in html          # test buttons only exist while on


# ------------------------------------------------------------------ states
def test_states_change_and_logo_follows(setup):
    dev_on(setup)
    for label, state in (("Simulate pause", "gray"), ("Simulate alert", "red"), ("Back to normal", "green")):
        press(setup, label)
        _, home = setup.get("/")
        assert light(home) == state and logo(home) == state
        _, js = setup.get("/status.json")
        d = json.loads(js)
        assert d["state"] == state and d["dev"] is True
    # 2026-10-26: Dev mode pages use SAMPLE data, so the simulated states land in the sample history only
    assert [r["state"] for r in setup.app.gate.audit.records() if r["event"] == "dev_sim"] == ["gray", "red", "green"]
    assert not [r for r in setup.gate.audit.records() if r["event"] == "dev_sim"]   # real history untouched


def test_turning_off_restores_normal(setup):
    dev_on(setup)
    press(setup, "Simulate alert")
    press(setup, "Add TEST buy")
    press(setup, "Turn off Dev mode")
    assert not setup.gate.dev.on() and setup.gate.dev.sim() == "green"
    _, home = setup.get("/")
    assert light(home) == "green" and logo(home) == "green" and "TEST MODE" not in home
    assert not [p for p in setup.gate.pending() if is_test_id(p["proposal"]["action_id"])]   # test move cancelled
    out = setup.gate.propose(ProposedAction(*SAFE))
    assert out["verdict"] == "allow" and setup.gate.paypal.calls   # real guarding again
    _, js = setup.get("/status.json")
    assert "dev" not in json.loads(js)


# ------------------------------------------------------------------ TEST rows
def test_test_rows_labeled_and_never_paid(setup):
    dev_on(setup)
    press(setup, "Add TEST buy")
    press(setup, "Add TEST sell")
    sample = setup.app.gate                     # Dev mode: TEST moves go to the SAMPLE history, never the real one
    assert sample is not setup.gate and not [m for m in D.moves(setup.gate.audit.records()) if m["test"]]
    ms = [m for m in D.moves(sample.audit.records()) if m["test"] and m["action_id"].startswith("devtest-") and
          not m["action_id"].startswith("devtest-sample")]
    assert len(ms) == 2 and all(m["label"].startswith("TEST: ") and m["description"].startswith("TEST")
                                for m in ms)
    assert {m["action"] for m in ms} == {"create_order", "refund"}
    _, rows = setup.get("/moves.json")
    test_rows = [r for r in json.loads(rows)["rows"] if r["id"].startswith("devtest-")
                 and not r["id"].startswith("devtest-sample")]
    assert len(test_rows) == 2 and all(r["result"].startswith("TEST: ") and r["item"].startswith("TEST: ")
                                       for r in test_rows)
    _, hist = setup.get("/history")
    assert hist.count(">TEST: ") >= 2 and "TEST: Dev mode turned on" in hist
    # test moves never turn the real light red
    assert D.status(setup.gate)["state"] == "green" and D.status(sample)["state"] == "green"
    # and can never be paid, even after Dev mode is off
    for p in sample.pending():
        if is_test_id(p["proposal"]["action_id"]):
            setup.gate.dev.set(False)
            r = sample.decide(p["proposal"]["action_id"], True, expected_hash=p["proposal_hash"])
            assert r["status"] == "dev_mode_not_paid"
    assert setup.gate.paypal.calls == []


# ------------------------------------------------------------------ TEST MODE banner
def test_test_mode_banner_on_every_tab_only_when_on(setup):
    for path in TABS:
        _, html = setup.get(path)
        assert "TEST MODE" not in html and BANNER not in html, path
    assert FLAG not in hear_page() and FLAG not in judge_landing()
    dev_on(setup)
    for path in TABS + ("/hear",):
        _, html = setup.get(path)
        assert html.count(FLAG) == 1, path
        assert BANNER in html, path
        # top middle, above the header: never over the top-right logo
        assert html.index('class="dev-strip"') < html.index('<header class="top') < html.index("bw-mark mk-")
    assert FLAG in hear_page(dev=True) and FLAG in judge_landing(dev=True)
    press(setup, "Turn off Dev mode")
    for path in TABS + ("/hear",):
        _, html = setup.get(path)
        assert "TEST MODE" not in html, path


def test_banner_is_csp_safe_and_accessible():
    html = page("x", "<p>b</p>", "home", {"state": "green", "text": "ok", "dev": True})
    strip = re.search(r'<div class="dev-strip".*?</div>', html, re.S).group(0)
    assert "style=" not in strip and 'role="region"' in strip and 'aria-label="Test mode"' in strip
    assert ".dev-flag{display:block;color:#B42318;font-weight:800" in STYLE and ".dev-strip{" in STYLE
    assert "text-align:center" in STYLE.split(".dev-strip{")[1].split("}")[0]
