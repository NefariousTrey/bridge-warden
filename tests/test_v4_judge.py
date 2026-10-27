"""v4 judge / demo mode: practice data only, no owner secrets, same protections."""
import http.client
import re
import threading
from pathlib import Path

import pytest

from bridge_warden import judge, web

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def clean_env(monkeypatch):
    for k in judge.OWNER_SECRET_ENV:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def jsrv(clean_env):
    srv, j = judge.serve_judge(0, public_host="bw-demo.onrender.com", bind="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, j
    srv.shutdown()
    judge.cleanup(j)


def req(srv, method, path, host=None, headers=None, body=None):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode()


def login(srv, host=None):
    _, h, _ = req(srv, "GET", "/judge/start", host=host)
    return h["Set-Cookie"].split(";")[0]


def test_refuses_when_any_owner_secret_is_set(clean_env, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-SECRET-value-123456")
    with pytest.raises(SystemExit) as ex:
        judge.Judge()
    assert "XAI_API_KEY" in str(ex.value) and "SECRET-value" not in str(ex.value)


def test_practice_only_nothing_real(jsrv):
    srv, _ = jsrv
    g = srv.bw_app.gate
    assert g.paypal is None and g.ai is None
    assert isinstance(g.prices, judge.PracticePrices)
    assert srv.bw_app.money_reader.practice


def test_landing_health_and_cookie(jsrv):
    srv, _ = jsrv
    assert req(srv, "GET", "/healthz")[2] == "ok"
    code, h, body = req(srv, "GET", "/")
    assert code == 200 and "practice copy" in body and "<script" not in body
    assert "Content-Security-Policy" in h and "unsafe-inline" not in h["Content-Security-Policy"]
    assert not re.search(r'(src|href)="https?://', body)
    _, h, _ = req(srv, "GET", "/judge/start")
    assert "HttpOnly" in h["Set-Cookie"] and "SameSite=Strict" in h["Set-Cookie"]
    _, h, _ = req(srv, "GET", "/judge/start", host="bw-demo.onrender.com")
    assert "Secure" in h["Set-Cookie"]


def test_wrong_host_refused(jsrv):
    srv, _ = jsrv
    assert req(srv, "GET", "/healthz", host="evil.example.com")[0] == 421


def test_scenario_button_holds_too_cheap_seller(jsrv):
    srv, _ = jsrv
    ck = login(srv)
    _, _, body = req(srv, "GET", "/", headers={"Cookie": ck})
    assert "Judge demo: play the AI agent" in body
    app = srv.bw_app
    tok = next(k for k, v in app.nonces.items() if v[0] == "judge:cheap")
    code, _, _ = req(srv, "POST", "/act", headers={"Cookie": ck, "Origin": f"http://127.0.0.1:{srv.server_address[1]}",
                                                    "Content-Type": "application/x-www-form-urlencoded"},
                     body=f"token={tok}")
    assert code == 303
    p = app.gate.pending()[-1]
    assert any("far below what stores ask" in r for r in p["verdict"]["reasons"])
    _, _, body = req(srv, "GET", "/", headers={"Cookie": ck})
    assert "Price is far below what stores ask." in body


def test_public_host_needs_https_origin(jsrv):
    srv, _ = jsrv
    ck = login(srv, host="bw-demo.onrender.com")
    req(srv, "GET", "/", host="bw-demo.onrender.com", headers={"Cookie": ck})
    tok = next(k for k, v in srv.bw_app.nonces.items() if v[0] == "judge:safe")
    hdr = {"Cookie": ck, "Content-Type": "application/x-www-form-urlencoded"}
    code, _, _ = req(srv, "POST", "/act", host="bw-demo.onrender.com",
                     headers={**hdr, "Origin": "http://bw-demo.onrender.com"}, body=f"token={tok}")
    assert code == 403
    tok = next(k for k, v in srv.bw_app.nonces.items() if v[0] == "judge:safe")
    code, _, _ = req(srv, "POST", "/act", host="bw-demo.onrender.com",
                     headers={**hdr, "Origin": "https://bw-demo.onrender.com"}, body=f"token={tok}")
    assert code == 303


def test_busy_limit(jsrv):
    srv, j = jsrv
    j.taps = [__import__("time").monotonic()] * judge.MAX_TAPS_PER_HOUR
    assert "busy" in judge.run_scenario(srv.bw_app, "safe")


def test_owner_serve_still_localhost_only():
    with pytest.raises(ValueError):
        web.serve(None, host="0.0.0.0")


def test_render_yaml_is_judge_only_and_manual():
    y = (ROOT / "render-judge.yaml").read_text(encoding="utf-8")   # moved 2026-10-26: root render.yaml is now the self-host button
    assert "judge --public" in y and "autoDeploy: false" in y and "healthCheckPath: /healthz" in y
    keys = re.findall(r"- key: (\S+)", y)
    assert keys == ["PYTHON_VERSION"]


def test_judge_history_and_why_pages_load_with_white_logo(jsrv):
    """Oct 26 fix: judge mode's _page had no mark_back, so /history and its 'Why?' page crashed (TypeError).
    Now: History + Why use the white-fill logo, the other pages the navy-fill one."""
    import json as _j
    srv, _ = jsrv
    ck = {"Cookie": login(srv)}
    st, _, body = req(srv, "GET", "/history", headers=ck)
    assert st == 200 and "bw-mark-white-v7b" in body and 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body
    assert '<header class="top top-light">' in body                     # white header on Guard History
    rows = _j.loads(req(srv, "GET", "/moves.json", headers=ck)[2])["rows"]
    if rows:
        st, _, body = req(srv, "GET", rows[0]["link"], headers=ck)
        assert st == 200 and "bw-mark-white-v7b" in body
        assert '<header class="top top-light">' in body
    st, _, body = req(srv, "GET", "/", headers=ck)
    assert st == 200 and "bw-mark-white-v7b" in body and 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body   # Oct 26 10:11 PM ET: all white
    assert '<header class="top top-light">' in body
    st, _, body = req(srv, "GET", "/", headers={})                                  # public judge landing page too
    assert st == 200 and "bw-mark-white-v7b" in body and '<header class="top top-light">' in body
