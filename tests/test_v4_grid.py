"""v4 History grid: AG Grid Community, self-hosted, allowed only by exact hashes. No outside hosts."""
import base64
import hashlib
import json
import re
from pathlib import Path

from test_v4_ui import GIFT, NEW, setup  # noqa: F401  (fixture)
from bridge_warden import web
from bridge_warden.models import ProposedAction as P

GIFT_A = lambda: P("payout", "250.00", "USD", "desk@personal.example.com", GIFT)
NEW_A = lambda: P("payout", "40.00", "USD", NEW, "new seller listing")

STATIC = Path(web.__file__).resolve().parent / "static"


def h256(b):
    return "sha256-" + base64.b64encode(hashlib.sha256(b).digest()).decode()


def test_files_are_local_mit_and_make_no_network_calls():
    lic = (STATIC / "AG-GRID-LICENSE.txt").read_text(encoding="utf-8")
    assert lic.startswith("The MIT License")
    bundle = (STATIC / "ag-grid-community.min.js").read_text(encoding="utf-8")
    for bad in ("XMLHttpRequest", "sendBeacon", "fetch(", "new WebSocket", "importScripts"):
        assert bad not in bundle
    for name in ("bw-grid.js", "bw-grid-v2.js", "bw-grid-v3.js"):   # v1, v2 kept on disk; v3 is the one served
        ours = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://", ours) and "innerHTML" not in ours and "eval(" not in ours
        assert "fetch('/moves.json'" in ours


def test_history_csp_allows_exactly_the_two_files(setup):
    setup.gate.propose(GIFT_A()); setup.gate.propose(NEW_A())
    r, body = setup.get("/history")
    csp = r.getheader("Content-Security-Policy")
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "'self'" not in csp.split("script-src")[1].split(";")[0]
    assert "http" not in csp and "*" not in csp
    for n in web.GRID_FILES:
        want = h256((STATIC / n).read_bytes())
        assert f"'{want}'" in csp
        assert f'<script src="/static/{n}" integrity="{want}"></script>' in body
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'data-nonce="{nonce}"' in body
    assert '<div id="bw-plain"><table' in body          # plain table is always there (no-JS fallback)
    _, body2 = setup.get("/history")
    assert re.search(r'data-nonce="([^"]+)"', body2).group(1) != nonce   # new nonce every time


def test_other_pages_keep_the_strict_csp(setup):
    r, body = setup.get("/")
    assert r.getheader("Content-Security-Policy") == web.HEADERS["Content-Security-Policy"]
    assert "/static/" not in body


def test_static_route_is_allowlisted_and_needs_login(setup):
    r, _ = setup.req("GET", "/static/bw-grid-v3.js")
    assert r.status == 401
    r, _ = setup.get("/static/bw-grid-v3.js")
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/javascript")
    assert r.getheader("X-Content-Type-Options") == "nosniff"
    for bad in ("/static/../web.py", "/static/AG-GRID-LICENSE.txt", "/static/x.js", "/static/",
                "/static/bw-grid.js", "/static/bw-grid-v2.js"):
        assert setup.get(bad)[0].status == 404


def test_moves_json_is_redacted_rows_only(setup):
    setup.gate.propose(GIFT_A())
    r, _ = setup.req("GET", "/moves.json")
    assert r.status == 401
    r, body = setup.get("/moves.json")
    rows = json.loads(body)["rows"]
    assert rows and set(rows[0]) == {"id", "at", "when", "side", "item", "counterparty", "amount", "amount_text",
                                     "market", "market_text", "market_source", "diff_pct", "risk", "risk_label",
                                     "risk_why", "dot", "dot2x", "result", "kind", "why", "choice", "link"}
    assert rows[0]["kind"] == "blocked"
