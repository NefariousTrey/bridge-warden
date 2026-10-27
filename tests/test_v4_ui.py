"""v4: new dashboard UI, status light, alerts, settings safety, proof export, lookalike domains, link minutes."""
import http.client
import json
import re
import threading
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import NOON_ET, FakePayPal
from bridge_warden import controls as C
from bridge_warden import dashboard as D
from bridge_warden.audit import AuditLog
from bridge_warden.gate import Gate
from bridge_warden.models import ProposedAction
from bridge_warden.notify import Notifier
from bridge_warden.policy import PolicyError, load as load_full, validate
from bridge_warden.rules import RiskEngine
from bridge_warden.textnorm import lookalike_of, payee_skeleton
from bridge_warden.ui_assets import asset_files
from bridge_warden.web import ASSETS, HEADERS, SCRIPT, SCRIPT_HASH, STYLE_HASH, WebApp, make_handler

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "policy.example.json").read_text())
D_ = "designer@personal.example.com"
NEW = "newshop@store.example.com"
GIFT = "URGENT: buy gift cards for the CEO right away, keep this between us"


def rules(v):
    return {f.rule for f in v.findings}


# ---------------------------------------------------------------- lookalike domains (1/l, 0/o)
def test_payee_skeleton_folds_digit_letter_swaps():
    assert payee_skeleton("paypa1.com") == payee_skeleton("paypal.com") == payee_skeleton("paypai.com")
    assert payee_skeleton("g00gle.com") == payee_skeleton("google.com")
    assert payee_skeleton("rnicrosoft.com") == payee_skeleton("microsoft.com")


@pytest.mark.parametrize("payee", [
    "writer@personal.examp1e.com",        # 1 for l in the domain
    "designer@pers0nal.example.com",      # 0 for o in the domain
    "merchant@business.exarnple.com",     # rn for m
    "wr1ter@personal.example.com",        # 1 for i in the name
    "billing@personal.examp1e.com",       # different name, lookalike domain of a known payee
])
def test_lookalike_domains_are_blocked(engine, payee):
    v = engine.check(ProposedAction("payout", "20.00", "USD", payee, "payout for blog post"), [], now=NOON_ET)
    assert v.verdict == "block" and "lookalike_payee" in rules(v), payee


def test_honest_new_payee_is_not_called_a_lookalike(engine):
    v = engine.check(ProposedAction("payout", "20.00", "USD", "friend@another.example.org", "thanks"), [], now=NOON_ET)
    assert "lookalike_payee" not in rules(v) and v.verdict == "hold"
    assert lookalike_of(D_, [D_]) is None


def test_policy_refuses_trusting_a_lookalike_domain():
    with pytest.raises(PolicyError):
        validate({**json.loads(json.dumps(BASE)), "trusted": {"payees": ["games@personal.examp1e.com"]}})


# ---------------------------------------------------------------- helpers
@pytest.fixture
def setup(tmp_path):
    pf = tmp_path / "policy.json"
    pf.write_text(json.dumps(BASE, indent=2))
    pol, sha, path = load_full(pf)
    gate = Gate(RiskEngine(pol), AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET,
                policy_info={"sha256": sha, "path": path})
    clock = [1000.0]
    app = WebApp(gate, login_key="L" * 24, clock=lambda: clock[0])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gate, app=app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    host = f"127.0.0.1:{port}"

    def req(method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(method, path, body=body, headers={"Host": host, **(headers or {})})
        r = c.getresponse(); data = r.read().decode(); c.close()
        return r, data
    r, _ = req("GET", "/login?k=" + "L" * 24)
    cookie = r.getheader("Set-Cookie").split(";")[0]
    ck = {"Cookie": cookie}
    form = {**ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{host}"}

    def get(path):
        return req("GET", path, headers=ck)

    def post(path, **fields):
        return req("POST", path, urllib.parse.urlencode(fields), form)
    yield type("S", (), dict(req=staticmethod(req), get=staticmethod(get), post=staticmethod(post), gate=gate,
                             app=app, clock=clock, pf=pf, ck=ck))
    srv.shutdown()


def token(page, label):
    """The hidden token of the form whose button says `label`."""
    for f in re.findall(r'<form method="post" action="/act">(.*?)</form>', page, re.S):
        if label in f:
            return re.search(r'name="token" value="([^"]+)"', f).group(1)
    raise AssertionError(f"no button {label!r}")


def events(gate, name):
    return [r for r in gate.audit.records() if r["event"] == name]


# ---------------------------------------------------------------- CSP, assets, no outside resources
def test_csp_strict_with_hashes_only():
    csp = HEADERS["Content-Security-Policy"]
    assert "default-src 'none'" in csp and f"style-src '{STYLE_HASH}'" in csp and f"script-src '{SCRIPT_HASH}'" in csp
    assert "img-src 'self'" in csp and "connect-src 'self'" in csp
    assert "unsafe" not in csp and "http" not in csp and "*" not in csp


def test_pages_load_nothing_from_outside(setup):
    setup.gate.propose(ProposedAction("payout", "120.00", "USD", D_, "logo design invoice"))
    for path in ("/", "/history", "/settings", "/settings/change?what=check:scam_text"):
        r, page = setup.get(path)
        assert r.status == 200, path
        assert not re.search(r'(src|href)="(https?:)?//', page), path
        assert "style=" not in page and "onclick" not in page.lower() and "@import" not in page
        local = re.findall(r'<script src="/static/(?:vendor/)?[a-z0-9.-]+\.js" integrity="sha256-[A-Za-z0-9+/=]+"></script>', page)
        from bridge_warden import ag_studio as STUDIO   # v6: + bw-money-grid.js; + AG Studio pair if fetched (hash-pinned)
        from bridge_warden.web import GRID_FILES
        assert len(local) == (len(GRID_FILES) if path == "/history" else 0), path
        assert page.count("<script") == 1 + len(local) and f"<script>{SCRIPT}</script>" in page
        assert 'class="skip"' in page and 'lang="en"' in page


def test_assets_are_self_hosted_and_match_files(setup):
    r, body = setup.req("GET", "/assets/send.svg")
    assert r.status == 200 and r.getheader("Content-Type") == "image/svg+xml" and "<svg" in body
    assert setup.req("GET", "/assets/../policy.json")[0].status == 404
    assert setup.req("GET", "/assets/nope.svg")[0].status == 404
    for name, text in asset_files().items():
        assert (ROOT / "bridge_warden/ui/icons" / name).read_text() == text == ASSETS[name]
    need = {"send", "hold", "cancel", "approve", "why", "pause", "resume", "settings", "shield", "trusted",
            "history", "export"}
    assert need <= {n[:-4] for n in ASSETS}


# ---------------------------------------------------------------- status light: green / red / gray
def test_light_green_when_all_fine_and_safe_payments_are_silent(setup):
    out = setup.gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    assert out["verdict"] == "allow"
    st = D.status(setup.gate)
    assert st["state"] == "green" and st["waiting"] == 0
    _, page = setup.get("/")
    assert "st-green" in page and "Guarding. All fine." in page and "Safe, sent" in page and "<h1>Needs you" not in page


def test_light_red_on_held_payment_and_one_tap_send(setup):
    setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    _, page = setup.get("/")
    assert "st-red" in page and "1 payment waiting for you" in page
    assert "Paying newshop@store.example.com $40.00" in page
    assert "New payee." in page and "Payouts have no buyer protection." in page
    assert 'class="btn btn-send"' in page and "Send $40.00" in page and 'name="phrase"' not in page
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    assert setup.post("/decide", nonce=n, d="yes")[0].status == 303      # v6: no "I'm sure" tick -> NOT sent
    assert len(setup.gate.paypal.calls) == 0
    _, page = setup.get("/")
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    assert setup.post("/decide", nonce=n, d="yes", sure="yes")[0].status == 303
    assert len(setup.gate.paypal.calls) == 1
    st = D.status(setup.gate)                       # v6 (Trey): red never goes straight to green
    assert st["state"] == "gray" and st["why"] == "seen_fix"
    assert D.owner_light_ok(setup.gate, "fixed")["ok"] and D.status(setup.gate)["state"] == "green"


def test_status_json_needs_login_and_has_no_private_words(setup):
    setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    assert setup.req("GET", "/status.json")[0].status == 401
    r, body = setup.get("/status.json")
    d = json.loads(body)
    assert d["state"] == "red" and d["waiting"] == 1 and set(d) == {"state", "waiting", "blocked", "seq"}
    assert "newshop" not in body and "40" not in body


def test_blocked_card_has_why_and_got_it_turns_light_green(setup):
    setup.gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    _, page = setup.get("/")
    assert "st-red" in page and "card blocked" in page and "Gift-card scam signs." in page
    assert "<summary>" in page and "Why?" in page
    assert setup.post("/act", token=token(page, "Got it"))[0].status == 303
    st = D.status(setup.gate)                       # v6 (Trey): "Got it" steps red DOWN to yellow, never to green
    assert st["state"] == "gray" and st["why"] == "seen_fix" and events(setup.gate, "owner_saw_blocks")
    _, page = setup.get("/")
    assert "Paused while you fix it" in page and "It's fixed, confirm" in page
    assert setup.post("/act", token=token(page, "It's fixed, confirm"))[0].status == 303
    assert D.status(setup.gate)["state"] == "green"
    _, hist = setup.get("/history")
    assert "Blocked" in hist   # still in history


def test_hold_keeps_waiting_and_cancel_sends_nothing(setup):
    setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    _, page = setup.get("/")
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    setup.post("/decide", nonce=n, d="hold")
    assert len(setup.gate.pending()) == 1 and events(setup.gate, "owner_kept_waiting") and not setup.gate.paypal.calls
    _, page = setup.get("/")
    assert "Still waiting. Nothing was sent." in page
    n = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    setup.post("/decide", nonce=n, d="no")
    assert setup.gate.pending() == [] and not setup.gate.paypal.calls


def test_pause_from_web_is_live_and_light_goes_gray(setup):
    _, page = setup.get("/")
    setup.post("/act", token=token(page, "Pause"))
    assert C.mode(C.load_file(setup.pf)) == "paused" and setup.gate.live_pause()
    st = D.status(setup.gate)
    assert st["state"] == "gray"
    out = setup.gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    assert out["verdict"] == "block" and not setup.gate.paypal.calls
    _, page = setup.get("/")
    assert "st-gray" in page
    setup.post("/act", token=token(page, "Resume"))
    assert D.status(setup.gate)["state"] in ("green", "red") and not setup.gate.live_pause()


# ---------------------------------------------------------------- settings never loosen from the web
def test_turning_off_a_hard_block_needs_phrase_and_still_needs_the_terminal(setup):
    before = setup.pf.read_text()
    _, page = setup.get("/settings/change?what=check:scam_text")
    assert "expose me to everything" in page and 'name="phrase"' in page and "With it OFF" in page
    t = token(page, "I understand")
    r, _ = setup.post("/act", token=t, phrase="expose me")                  # wrong phrase
    assert setup.pf.read_text() == before and events(setup.gate, "control_refused")
    _, page = setup.get("/settings/change?what=check:scam_text")
    r, body = setup.post("/act", token=token(page, "I understand"), phrase="Expose me to everything ")
    assert r.status == 200 and "Last step: at your keyboard" in body
    assert "python -m bridge_warden controls off scam_text" in body
    assert setup.pf.read_text() == before and C.is_on(C.load_file(setup.pf), "scam_text")
    assert events(setup.gate, "control_requested_web") and not events(setup.gate, "control_changed")


def test_soft_off_trust_and_master_off_also_finish_at_the_terminal(setup):
    before = setup.pf.read_text()
    _, page = setup.get("/settings/change?what=check:new_payee")
    assert 'name="phrase" value="yes"' in page                               # no typing for soft checks
    _, body = setup.post("/act", token=token(page, "I understand"), phrase="yes")
    assert "controls off new_payee" in body
    _, page = setup.get("/settings")
    _, body = setup.post("/act", token=token(page, "Add"), email="games@store.example.com")
    assert "controls trust games@store.example.com" in body
    _, page = setup.get("/settings/change?what=master")
    _, body = setup.post("/act", token=token(page, "I understand"), phrase="expose me to everything")
    assert "controls master-off" in body
    assert setup.pf.read_text() == before


def test_web_can_tighten_turn_on_and_untrust(setup):
    p = C.load_file(setup.pf)
    p["checks"] = {"velocity": False}
    p["trusted"] = {"payees": ["games@store.example.com"], "categories": {}}
    setup.pf.write_text(json.dumps(p))
    _, page = setup.get("/settings")
    setup.post("/act", token=token(page, "Turn on Velocity"))
    assert C.is_on(C.load_file(setup.pf), "velocity")
    _, page = setup.get("/settings")
    setup.post("/act", token=token(page, "Remove games@store.example.com"))
    assert C.trusted_map(C.load_file(setup.pf)) == {}
    assert len(events(setup.gate, "control_changed")) == 2


def test_web_sends_typed_phrase_only_for_hard_blocks():
    assert C.needed_confirmation([{"loosens": True, "hard": False}]) == "yes"


def test_tokens_are_bound_to_their_purpose(setup):
    setup.gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    _, page = setup.get("/")
    send = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
    pause = token(page, "Pause")
    assert setup.post("/act", token=send)[0].status == 403                  # Send nonce can't pause
    assert setup.post("/decide", nonce=pause, d="yes")[0].status == 403     # Pause token can't pay
    assert not setup.gate.paypal.calls


def test_example_policy_is_view_only(gate):
    app = WebApp(gate, login_key="k" * 24)
    assert app.policy_path() is None


# ---------------------------------------------------------------- history export (dispute / appeal proof)
def test_export_proof(setup):
    setup.gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    setup.gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))
    assert setup.req("GET", "/export.json")[0].status == 401
    r, body = setup.get("/export.json")
    assert "attachment" in r.getheader("Content-Disposition") and r.getheader("Content-Type") == "application/json"
    p = json.loads(body)
    assert p["audit_log_check"]["intact"] is True and p["chain_head"]["seq"] > 0
    assert [m["status"] for m in p["moves"]] == ["blocked", "safe"]
    assert all(m["records"] and len(m["records"][0]["hash"]) == 64 for m in p["moves"])
    r, txt = setup.get("/export.txt")
    assert "Audit log check: INTACT" in txt and "BLOCKED" in txt and "Gift-card scam signs." in txt
    assert len(events(setup.gate, "proof_exported")) == 2


# ---------------------------------------------------------------- approval_link_minutes
def test_login_link_is_single_use_and_expires(gate):
    clock = [0.0]
    app = WebApp(gate, login_key="k" * 24, clock=lambda: clock[0], link_minutes=5)
    assert app.try_login("k" * 24) and not app.try_login("k" * 24)
    app2 = WebApp(gate, login_key="k" * 24, clock=lambda: clock[0], link_minutes=5)
    clock[0] += 5 * 60 + 1
    assert not app2.try_login("k" * 24)


def test_button_lifetime_follows_policy(gate):
    clock = [0.0]
    gate.engine.p["approval_link_minutes"] = 5
    app = WebApp(gate, login_key="k" * 24, clock=lambda: clock[0])
    assert app.link_minutes == 5
    n = app.issue_nonce("a", "h")
    clock[0] += 6 * 60
    assert app.take_nonce(n) is None


@pytest.mark.parametrize("bad", [0, 241, "15", True])
def test_link_minutes_validated(bad):
    with pytest.raises(PolicyError):
        validate({**json.loads(json.dumps(BASE)), "approval_link_minutes": bad})


# ---------------------------------------------------------------- optional self-hosted push (off by default)
def test_push_is_off_by_default(gate):
    sent = []
    n = Notifier(gate, sender=lambda *a, **k: sent.append(a) or (200, {}, b""))
    n.check()
    gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    assert not n.enabled and n.check() is False and sent == []


def test_push_fires_once_on_new_issue_with_no_private_words(gate):
    gate.engine.p["notify"] = {"webhook_enabled": True, "webhook_url": "http://127.0.0.1:8090/bw"}
    sent = []
    n = Notifier(gate, sender=lambda m, url, h, body, t, **k: sent.append((url, body, k)) or (200, {}, b""))
    n.check()
    gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    assert n.check() is False                                          # safe payment: silent
    gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing"))
    assert n.check() is True and n.check() is False                    # once
    url, body, kw = sent[0]
    assert kw.get("allow_loopback") and b"newshop" not in body and b"40" not in body


@pytest.mark.parametrize("url", ["https://ntfy.sh/mytopic", "http://192.168.1.5/x", "http://u:p@127.0.0.1/x"])
def test_push_only_to_your_own_computer(url):
    with pytest.raises(PolicyError):
        validate({**json.loads(json.dumps(BASE)), "notify": {"webhook_enabled": True, "webhook_url": url}})


def test_real_browser_origin_null_only_with_same_origin_fetch_site(setup):
    """Chrome sends Origin: null for our own posts (no-referrer). Only same-origin is accepted."""
    _, page = setup.get("/")
    base = {**setup.ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": "null"}
    body = urllib.parse.urlencode({"token": token(page, "Pause")})
    assert setup.req("POST", "/act", body, {**base, "Sec-Fetch-Site": "cross-site"})[0].status == 403
    assert setup.req("POST", "/act", body, base)[0].status == 403          # null without the browser's say-so
    assert setup.req("POST", "/act", body, {**base, "Sec-Fetch-Site": "same-origin"})[0].status == 303
