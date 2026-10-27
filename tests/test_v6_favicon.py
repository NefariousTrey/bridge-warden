"""v6: the browser tab icon is Trey's existing BW mark (favicon.ico + 32px PNG), served with no login, exact names only."""
import http.client
import struct

from test_v4_ui import setup  # noqa: F401  (fixture)
from bridge_warden import web


def raw(s, path, cookie=True):
    port = next(c.cell_contents for c in s.req.__closure__ if isinstance(c.cell_contents, int))   # the test server's port
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(s.ck if cookie else {})})
    r = c.getresponse(); b = r.read(); c.close()
    return r, b


def test_every_page_links_the_favicon(setup):
    _, page = setup.get("/")
    assert '<link rel="icon" href="/favicon.ico"' in page and 'href="/favicon-32.png"' in page
    assert 'href="/assets/logo.svg" type="image/svg+xml"' not in page


def test_favicon_files_served_without_login(setup):
    r, b = raw(setup, "/favicon.ico", cookie=False)
    assert r.status == 200 and r.getheader("Content-Type").startswith("image/x-icon")
    zero, typ, n = struct.unpack("<HHH", b[:6])
    assert (zero, typ) == (0, 1) and n == 3                         # a real .ico with 16/32/48
    r, b = raw(setup, "/favicon-32.png", cookie=False)
    assert r.status == 200 and b[:8] == b"\x89PNG\r\n\x1a\n"
    assert "default-src 'none'" in r.getheader("Content-Security-Policy")


def test_only_exact_names(setup):
    for p in ("/favicon.png", "/favicon.ico/../web.py", "/favicon-32.png.bak", "/favicon"):
        r, _ = raw(setup, p, cookie=False)
        assert r.status in (401, 404), p
    assert set(web.FAVICONS) == {"/favicon.ico", "/favicon-32.png"}
