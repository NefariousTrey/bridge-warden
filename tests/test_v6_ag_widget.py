"""v6: the "BW Light" AG Studio custom widget (bridge_warden/ag_light.py + static/bw-light-widget.js).
Its two owner buttons run only Bridge Warden's existing rules: red never goes straight to green, agents can only
raise the light, and nothing here can approve, ignore, send, release a hold or move money.
Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache 2.0.
Fakes only: fake PayPal, fake alerts. Nothing real is called."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_v4_ui import GIFT, NEW, events, setup  # noqa: F401  (setup is a fixture)
from test_v6_ag_agent import FakeAlerts, red_finding
from test_v6_web_ag import _ORIGIN, needs_studio, st  # noqa: F401  (st is a fixture)
from bridge_warden import ag_agent as AG
from bridge_warden import ag_light as L
from bridge_warden import ag_studio as STUDIO
from bridge_warden import dashboard as D
from bridge_warden import web as W
from bridge_warden.models import ProposedAction

JS = Path(STUDIO.STATIC_DIR) / STUDIO.WIDGET


def block(gate):
    return gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com", GIFT))


def hold(gate):
    return gate.propose(ProposedAction("payout", "40.00", "USD", NEW, "new seller listing 1"))


def press(app, what):
    """What the web route does after it takes the one-time token: run the step for the light it was shown for."""
    s = L.state(app)
    assert s["can"][what] and s["tokens"][what], s
    purpose = app.nonces[s["tokens"][what]][0]
    assert app.take_nonce(s["tokens"][what], purpose) is not None
    return L.step(app, purpose)


def never_red_to_green(gate):
    bad = [r for r in events(gate, D.LIGHT_EVENT) if r.get("from") == "red" and r.get("to") == "green"]
    assert bad == [], bad


# ---- the rules (module level) ------------------------------------------------------------------------------
def test_green_shows_trey_dot_and_no_buttons(setup):
    s = L.state(setup.app)
    assert s["light"] == "green" and s["can"] == {"seen": False, "fixed": False} and s["tokens"] == {}
    assert s["last_alert"] is None and "never goes straight to green" in s["rules"]
    for u in (s["dot"]["src"], s["dot"]["src2x"]):
        assert W.dot_file(u.rsplit("/", 1)[1]) is not None, u      # a real, allowlisted BW dot


def test_colorblind_dots_exist():
    for c in ("red", "gray", "green"):
        for u in L.dot(c, cvd=True).values():
            assert W.dot_file(u.rsplit("/", 1)[1]) is not None, u
        for u in L.dot(c).values():
            assert W.dot_file(u.rsplit("/", 1)[1]) is not None, u


def test_blocked_red_seen_yellow_then_fixed_green(setup):
    g = setup.gate
    block(g)
    s = L.state(setup.app)
    assert s["light"] == "red" and s["can"] == {"seen": True, "fixed": False}
    assert s["last_alert"] and s["last_alert"]["text"]
    assert press(setup.app, "seen")["light"] == "yellow"
    assert events(g, "owner_saw_blocks")[-1]["by"] == L.BY
    s = L.state(setup.app)
    assert s["light"] == "yellow" and s["can"] == {"seen": False, "fixed": True}
    assert press(setup.app, "fixed")["light"] == "green"
    assert events(g, D.OWNER_OK)[-1]["by"] == L.BY and events(g, D.OWNER_OK)[-1]["mode"] == "fixed"
    never_red_to_green(g)
    assert g.paypal.calls == []


def test_red_never_straight_to_green(setup):
    g = setup.gate
    block(g)
    seq = D.status(g)["seq"]
    r = L.step(setup.app, f"{L.PURPOSE}fixed:{seq}")       # even a forged "fixed" token for a red light
    assert r["ok"] is False and "red" in r["why"] and D.status(g)["state"] == "red"
    assert events(g, "owner_light_ok_refused")
    never_red_to_green(g)


def test_ag_agent_red_seen_then_fixed(setup):
    g = setup.gate
    iid = AG.raise_light(g, red_finding(), alerts=FakeAlerts(g))["issue_id"]
    assert L.state(setup.app)["light"] == "red"
    assert press(setup.app, "seen")["ok"]
    assert [i["status"] for i in AG.issues(g.audit.records()) if i["id"] == iid] == ["yellow"]
    assert press(setup.app, "fixed")["light"] == "green"
    assert [i["status"] for i in AG.issues(g.audit.records()) if i["id"] == iid] == ["fixed"]
    never_red_to_green(g)


def test_agent_can_only_raise_never_lower(setup):
    """The agent's own name can't run the owner rules, even with a valid step."""
    g = setup.gate
    iid = AG.raise_light(g, red_finding(), alerts=FakeAlerts(g))["issue_id"]
    assert AG.mark_seen(g, iid, by="BW AG Grid agent (AI)")["ok"] is False
    assert D.owner_light_ok(g, "fixed", by="BW AG Grid agent (AI)")["ok"] is False
    assert D.status(g)["state"] == "red"
    assert L.BY.startswith("owner")          # the widget's steps are logged as the owner's own clicks


def test_held_payment_is_never_decided_by_the_widget(setup):
    g = setup.gate
    r = hold(g)
    assert L.state(setup.app)["light"] == "red"
    assert press(setup.app, "seen")["light"] == "yellow"
    s = L.state(setup.app)
    assert s["can"]["fixed"] is False and "Home" in s["hint"]            # the yes / no stays on Home
    assert r["action_id"] in str(g.pending())                             # still held, still waiting for you
    assert g.paypal.calls == [] and not events(g, "owner_decision")


def test_off_is_red_and_points_to_settings(setup):
    setup.gate.engine.p["mode"] = "off"
    s = L.state(setup.app)
    assert s["light"] == "red" and s["can"] == {"seen": False, "fixed": False} and "Settings" in s["hint"]


def test_stale_or_unknown_steps_change_nothing(setup):
    g = setup.gate
    n = len(g.audit.records())
    for p in ("studio:light:approve:1", "studio:light:fixed:x", "nope", f"{L.PURPOSE}seen:1"):
        assert L.step(setup.app, p)["ok"] is False
    assert not [r for r in g.audit.records()[n:] if r["event"] in ("owner_saw_blocks", D.OWNER_OK)]


# ---- the web routes -----------------------------------------------------------------------------------------
def _light_post(s, body, origin="same", ctype="application/json"):
    h = {**s.ck, "Content-Type": ctype}
    if origin == "same":
        h["Origin"] = _ORIGIN[0]
    elif origin:
        h["Origin"] = origin
    return s.req("POST", "/ag-studio/light", body if isinstance(body, str) else json.dumps(body), h)


@needs_studio
def test_light_json_needs_login_and_is_no_store(st):
    assert st.req("GET", "/ag-studio/light.json")[0].status == 401
    r, body = st.get("/ag-studio/light.json")
    assert r.status == 200 and r.getheader("Cache-Control") == "no-store"
    assert json.loads(body)["light"] == "green"


@needs_studio
def test_buttons_over_http_seen_then_fixed_single_use(st):
    block(st.gate)
    s = json.loads(st.get("/ag-studio/light.json")[1])
    t = s["tokens"]["seen"]
    assert _light_post(st, {"step": "seen", "token": t}, origin="http://evil.example")[0].status == 403
    assert _light_post(st, {"step": "seen", "token": t}, origin=None)[0].status == 403
    assert _light_post(st, f"step=seen&token={t}", ctype="application/x-www-form-urlencoded")[0].status == 415
    assert _light_post(st, {"step": "fixed", "token": t})[0].status == 403        # a seen token is not a fixed token
    r, body = _light_post(st, {"step": "seen", "token": t})
    assert r.status == 200 and json.loads(body)["light"] == "yellow" and "yellow" in json.loads(body)["say"]
    assert _light_post(st, {"step": "seen", "token": t})[0].status == 403          # replay
    s = json.loads(st.get("/ag-studio/light.json")[1])
    r, body = _light_post(st, {"step": "fixed", "token": s["tokens"]["fixed"]})
    assert r.status == 200 and json.loads(body)["light"] == "green"
    never_red_to_green(st.gate)
    assert st.gate.paypal.calls == []


@needs_studio
def test_post_needs_login_and_size_cap(st):
    r, _ = st.req("POST", "/ag-studio/light", "{}", {"Content-Type": "application/json", "Origin": _ORIGIN[0]})
    assert r.status == 401
    assert _light_post(st, {"step": "seen", "token": "x" * 3000})[0].status == 413
    assert _light_post(st, "not json")[0].status == 400


@needs_studio
def test_panel_serves_hashed_widget_with_bw_header(st):
    r, p = st.get("/ag-studio/panel")
    pc = r.getheader("Content-Security-Policy")
    assert STUDIO.static(STUDIO.WIDGET)[1] in pc and STUDIO.static(STUDIO.GLUE)[1] in pc
    assert p.index(STUDIO.WIDGET) < p.index(STUDIO.GLUE)                        # widget is defined before use
    assert 'class="bw-head"' in p and "/assets/brand/bw-mark-navy-v7b.png" in p
    assert W.mark_file("bw-mark-navy-v7b.png") is not None
    assert STUDIO.static(STUDIO.WIDGET)[0] == JS.read_bytes() and b"isTrusted" in JS.read_bytes()


def test_widget_js_has_no_money_or_approve_path():
    s = JS.read_text()
    for bad in ("/act", "/decide", ".click(", "submit(", "nonce", "approve", "release", "api.x.ai", "Authorization",
                "defineAiTool", "innerHTML"):
        assert bad not in s, bad
    for bad in ("cross" + "roads",):
        assert bad not in s.lower()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_bw_light_widget_node_tests():
    p = Path(__file__).parent / "node" / "test_bw_light_widget.mjs"
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "passed" in r.stdout and " 0 passed" not in r.stdout


# ---- the compact BW Light card on every BW page (server-rendered, same owner rules) ------------------------------
import re  # noqa: E402

PAGES = ("/", "/money", "/history", "/settings")


def card(page):
    m = re.search(r'<aside class="bwl bwl-(\w+)".*?</aside>', page, re.S)
    assert m, "no BW Light card"
    return m.group(1), m.group(0)


def card_token(html_card, step):
    m = re.search(r'name="token" value="([^"]+)"><input type="hidden" name="back" value="([^"]*)">'
                  rf'<button class="btn bwl-{step}" type="submit">', html_card)
    return m and m.group(1)


def test_compact_card_on_every_page_under_the_status_bar(setup):
    for p in PAGES:
        r, page = setup.get(p)
        assert r.status == 200, p
        light, c = card(page)
        assert light == "green" and page.count('class="bwl ') == 1, p
        assert page.index('id="status"') < page.index('class="bwl ') < page.index('role="status"'), p
        assert "style=" not in c and "<script" not in c and "BW Light" in c and "#logo" in c, p
        assert 'disabled>I&#x27;ve seen this' in c and 'disabled>It&#x27;s fixed' in c, p       # nothing to do on green
    assert L.CSS in W.STYLE and ".bwl-h{" in L.CSS and "#FFFFFF" in L.CSS                          # white header, hashed CSS
    assert "position:fixed" not in L.CSS and "position:absolute" not in L.CSS                      # never covers content


def test_compact_card_red_seen_yellow_fixed_green_single_use(setup):
    g = setup.gate
    block(g)
    _, c = card(setup.get("/money")[1])
    assert "bwl-red" in c and card_token(c, "fixed") is None and 'disabled>It&#x27;s fixed' in c    # red: no green step
    t = card_token(c, "seen")
    assert t and 'name="back" value="/money"' in c
    r, _ = setup.post("/act", token=t, back="/money")
    assert r.status == 303 and r.getheader("Location") == "/money"
    assert L.state(setup.app)["light"] == "yellow" and events(g, "owner_saw_blocks")[-1]["by"] == L.BY
    assert setup.post("/act", token=t, back="/money")[0].status != 303                              # replay refused
    light, c = card(setup.get("/settings")[1])
    assert light == "yellow"
    r, _ = setup.post("/act", token=card_token(c, "fixed"), back="https://evil.example/")
    assert r.status == 303 and r.getheader("Location") == "/"                                       # back is allowlisted
    assert card(setup.get("/")[1])[0] == "green"
    never_red_to_green(g)
    assert g.paypal.calls == []


def test_compact_card_cannot_decide_a_held_payment(setup):
    g = setup.gate
    hold(g)
    _, c = card(setup.get("/")[1])
    assert "/decide" not in c and "Send" not in c and "approve" not in c.lower()
    assert g.paypal.calls == [] and len(g.pending()) == 1
