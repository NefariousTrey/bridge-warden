import threading
import urllib.parse
import urllib.request

import pytest

from bridge_warden.models import ProposedAction
from bridge_warden.paypal_client import PayPalSandbox
from bridge_warden.web import make_handler, serve
from http.server import ThreadingHTTPServer


def test_client_refuses_live_url():
    with pytest.raises(ValueError):
        PayPalSandbox("id", "secret", base_url="https://api-m.paypal.com")


def test_client_repr_hides_secret():
    assert "topsecret" not in repr(PayPalSandbox("client123456", "topsecret"))


def test_web_only_binds_localhost(gate):
    with pytest.raises(ValueError):
        serve(gate, host="0.0.0.0", port=0)


def test_web_page_approve_flow(gate):
    import http.client, re
    from bridge_warden.web import WebApp
    out = gate.propose(ProposedAction("payout", "120.00", "USD", "designer@personal.example.com", "logo design invoice"))
    app = WebApp(gate, login_key="k" * 24)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gate, app=app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    host = f"127.0.0.1:{port}"
    def req(method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(method, path, body=body, headers={"Host": host, **(headers or {})})
        r = c.getresponse(); data = r.read().decode(); c.close()
        return r, data
    try:
        r, _ = req("GET", "/")
        assert r.status == 401                                   # no login cookie, no page
        r, _ = req("GET", "/login?k=" + "k" * 24)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        assert "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")
        r, page = req("GET", "/", headers={"Cookie": cookie})
        assert out["action_id"] in page and "Send $120.00" in page   # v4: one big green Send button
        nonce = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
        form = {"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{host}"}
        r, _ = req("POST", "/decide", urllib.parse.urlencode({"nonce": "wrong", "d": "yes", "sure": "yes"}), form)
        assert r.status == 403 and gate.paypal.calls == []
        r, _ = req("POST", "/decide", urllib.parse.urlencode({"nonce": nonce, "d": "yes", "sure": "yes"}), form)
        assert r.status == 303
        assert len(gate.paypal.calls) == 1 and gate.pending() == []
    finally:
        srv.shutdown()
