"""v4 (2026-10-26): Trey's status dots in the UI, the color-blind mode switch, and the dot image route."""
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
from bridge_warden.policy import PolicyError, load as load_full, validate
from bridge_warden.rules import RiskEngine
from bridge_warden.web import (DOT_FILES, HEADERS, SCRIPT, STYLE_HASH, SCRIPT_HASH, WebApp, dot_file,
                                    light_files, make_handler)

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "policy.example.json").read_text(encoding="utf-8"))
ENERGY = ROOT / "assets" / "dots-trey-energy-20261026"
CVD = ROOT / "assets" / "dots-trey-cvd-20261026"
FULL = ROOT / "assets" / "dots-trey-energy-full-20261026"
D_ = "designer@personal.example.com"


def _server(tmp_path, writable=True):
    pf = tmp_path / ("policy.json" if writable else "policy.example.json")
    pf.write_text(json.dumps(BASE, indent=2), encoding="utf-8")
    pol, sha, path = load_full(pf)
    gate = Gate(RiskEngine(pol), AuditLog(tmp_path / "audit.jsonl"), FakePayPal(), clock=lambda: NOON_ET,
                policy_info={"sha256": sha, "path": path})
    app = WebApp(gate, login_key="L" * 24, clock=lambda: 1000.0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gate, app=app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    host = f"127.0.0.1:{port}"

    def req(method, p, body=None, headers=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(method, p, body=body, headers={"Host": host, **(headers or {})})
        r = c.getresponse(); data = r.read(); c.close()
        return r, (data if raw else data.decode())
    r, _ = req("GET", "/login?k=" + "L" * 24)
    ck = {"Cookie": r.getheader("Set-Cookie").split(";")[0]}
    form = {**ck, "Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{host}"}
    S = type("S", (), dict(req=staticmethod(req), gate=gate, app=app, pf=pf,
                           get=staticmethod(lambda p: req("GET", p, headers=ck)),
                           post=staticmethod(lambda p, **f: req("POST", p, urllib.parse.urlencode(f), form))))
    return S, srv


@pytest.fixture
def s(tmp_path):
    S, srv = _server(tmp_path)
    yield S
    srv.shutdown()


@pytest.fixture
def ro(tmp_path):
    S, srv = _server(tmp_path, writable=False)
    yield S
    srv.shutdown()


def token(page, label):
    for f in re.findall(r'<form method="post" action="/act">(.*?)</form>', page, re.S):
        if label in f:
            return re.search(r'name="token" value="([^"]+)"', f).group(1)
    raise AssertionError(f"no button {label!r}")


def light(page):
    sec = re.search(r'<section id="status"[^>]*>.*?</section>', page, re.S).group(0)
    img = re.search(r'<img class="light" src="([^"]+)" srcset="([^"]+)" width="(\d+)" height="\d+" alt="([^"]+)">',
                    sec)
    src = re.search(r'<source type="image/webp" srcset="([^"]+)">', sec).group(1)
    cvd = re.search(r'data-cvd="(\d)"', sec).group(1)
    return img.group(1), img.group(4), src, cvd, sec


# ---------------------------------------------------------------- the asset files
@pytest.mark.parametrize("c", ["green", "red", "yellow"])
def test_energy_ring_and_glyph_files_exist(c):
    for px in (48, 96, 128, 256):
        for ext in ("png", "webp"):
            assert (ENERGY / f"bw-dot-trey-{c}-ring-{px}.{ext}").is_file()
    assert (ENERGY / f"bw-dot-trey-{c}-glyph-24.png").is_file()


def _png_info(b):
    """(width, height, colour type, first pixel alpha) with the stdlib only (no Pillow in the app's venv)."""
    import struct, zlib
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, ctype = struct.unpack(">IIBB", b[16:26])
    i, idat = 8, b""
    while i < len(b):
        n, t = struct.unpack(">I4s", b[i:i + 8])
        if t == b"IDAT":
            idat += b[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    return w, h, ctype, raw[4]   # row 0, pixel 0: every PNG filter leaves it as stored


@pytest.mark.parametrize("n", ["red-x", "yellow-bang", "green-check"])
def test_cvd_orb_files_exist_square_and_transparent(n):
    for px in (48, 96, 128, 256):
        w, h, ctype, a0 = _png_info((CVD / f"bw-dot-trey-cvd-{n}-{px}.png").read_bytes())
        assert (w, h) == (px, px) and ctype == 6 and a0 == 0, (n, px)     # square, RGBA, clear corner
        wb = (CVD / f"bw-dot-trey-cvd-{n}-{px}.webp").read_bytes()
        assert wb[:4] == b"RIFF" and wb[8:12] == b"WEBP" and wb[12:16] in (b"VP8X", b"VP8L")   # has alpha
    for src in ("hidden-x.jpg", "hidden-bang.jpg", "hidden-check.jpg"):
        assert (CVD / "source" / src).is_file()


def test_notices_say_apache_and_logo_music_reserved():
    # 2026-10-26 (night): code stays Apache 2.0; the dot art is MIT on its own (old test in .bak-20261026-dotsmit)
    for d in (ENERGY, CVD, FULL):
        t = (d / "NOTICE.md").read_text(encoding="utf-8")
        assert "Art by @Nefarious_Trey." in t and "MIT License" in t and "all rights reserved" in t.lower()
        assert "Copyright 2026 Douglas Gibbons III\nMade by @Nefarious_Trey,\nwith Grok.\n" in t
        lic = (d / "LICENSE").read_text(encoding="utf-8")
        assert lic.startswith("MIT License\n\nCopyright 2026 Douglas Gibbons III\nMade by @Nefarious_Trey,\nwith Grok.\n")
        assert "Permission is hereby granted, free of charge" in lic and "WITHOUT WARRANTY OF ANY KIND" in lic
        if (d / "NOTICE.md.bak-20261026-dotsmit").exists():   # backups stay on the build box only (not shipped)
            assert "Apache License, Version 2.0" in (d / "NOTICE.md.bak-20261026-dotsmit").read_text(encoding="utf-8")   # old text kept
        if (d / "NOTICE.md.bak-20261026-apache").exists():
            assert "MIT" in (d / "NOTICE.md.bak-20261026-apache").read_text(encoding="utf-8")      # the oldest MIT text is kept too
    if (ENERGY / "NOTICE.md.bak").exists():
        assert "All rights reserved" in (ENERGY / "NOTICE.md.bak").read_text(encoding="utf-8")   # the oldest text is kept
    a = (ROOT / "ASSETS_NOTICE.md").read_text(encoding="utf-8")
    assert "Apache" in a and "logo" in a.lower() and "music" in a.lower() and "all rights reserved" in a.lower()
    assert "status dots are MIT licensed" in a
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in lic and "Version 2.0, January 2004" in lic and "END OF TERMS AND CONDITIONS" in lic
    n = (ROOT / "NOTICE").read_text(encoding="utf-8")
    # 2026-10-26: legal name only on copyright lines (Trey), then the two-line credit (old check in .bak-20261026-judge)
    assert n.startswith("Bridge Warden\nCopyright 2026 Douglas Gibbons III\nMade by @Nefarious_Trey,\nwith Grok.\n")
    assert "logo" in n.lower() and "music" in n.lower() and "all rights reserved" in n.lower()


# ---------------------------------------------------------------- the /assets/dots/ route
def test_dot_route_serves_png_and_webp_with_right_type(s):
    for name, ctype, magic in (("bw-dot-trey-green-ring-96.png", "image/png", b"\x89PNG"),
                               ("bw-dot-trey-red-ring-128.webp", "image/webp", b"RIFF"),
                               ("bw-dot-trey-cvd-yellow-bang-128.png", "image/png", b"\x89PNG"),
                               ("bw-dot-trey-cvd-green-check-256.webp", "image/webp", b"RIFF"),
                               ("bw-dot-trey-red-glyph-24.png", "image/png", b"\x89PNG")):
        r, body = s.req("GET", "/assets/dots/" + name, raw=True)
        assert r.status == 200 and r.getheader("Content-Type") == ctype, name
        assert body[:4] == magic and body == DOT_FILES[name].read_bytes()
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        assert r.getheader("Content-Security-Policy") == "default-src 'none'; style-src 'none'"


@pytest.mark.parametrize("bad", ["../policy.json", "..%2f..%2fpolicy.json", "nope.png", "NOTICE.md",
                                 "source/trey-ring-red.jpg", "bw-dot-trey-red-ring-96.jpg", "",
                                 "%2e%2e/web.py", "bw-dot-trey-red-ring-96.png/../../x"])
def test_dot_route_refuses_anything_not_on_the_list(s, bad):
    assert s.req("GET", "/assets/dots/" + bad, raw=True)[0].status == 404
    assert dot_file(bad) is None


def test_dot_allowlist_is_only_images_in_the_three_folders():
    assert DOT_FILES and all(n.endswith((".png", ".webp")) for n in DOT_FILES)
    assert all(f.parent in (ENERGY, CVD, FULL) for f in DOT_FILES.values())


def test_every_light_and_dot_the_page_can_ask_for_exists():
    for state in ("green", "red", "gray"):
        for cvd in (False, True):
            base, sizes = light_files(state, cvd)
            for px in sizes:
                for ext in ("png", "webp"):
                    assert base.rsplit("/", 1)[1] + f"{px}.{ext}" in DOT_FILES
    for nm in ("red-x", "yellow-bang", "green-check"):          # the JS builds these names too
        assert f"'cvd-{nm}'" in SCRIPT and f"bw-dot-trey-cvd-{nm}-256.png" in DOT_FILES


def test_csp_still_strict():
    csp = HEADERS["Content-Security-Policy"]
    assert f"style-src '{STYLE_HASH}'" in csp and f"script-src '{SCRIPT_HASH}'" in csp and "img-src 'self'" in csp
    assert "unsafe" not in csp and "http" not in csp and "data:" not in csp and "*" not in csp


# ---------------------------------------------------------------- policy: ui.colorblind_mode
def test_policy_ui_block_is_checked():
    assert validate({**BASE, "ui": {"colorblind_mode": True}})
    for bad in ({"colorblind_mode": "yes"}, {"colorblind_mode": 1}, {"theme": "purple"}, {"theme": True}, {"font": "big"}, ["colorblind_mode"]):
        with pytest.raises(PolicyError):
            validate({**BASE, "ui": bad})
    assert validate({**BASE, "ui": {"theme": "dark"}}) and validate({**BASE, "ui": {"theme": "light"}})
    assert C.ui_prefs(BASE) == {"colorblind_mode": False, "theme": "light"}   # default off, Light


# ---------------------------------------------------------------- the big light, normal mode
def test_normal_mode_green_light_is_the_green_full_dot(s):
    src, alt, webp, cvd, _ = light(s.get("/")[1])
    assert src == "/assets/dots/bw-dot-trey-green-full-96.png" and alt == "All clear" and cvd == "0"
    assert "bw-dot-trey-green-full-96.webp 1x" in webp and "bw-dot-trey-green-full-128.webp 2x" in webp


def test_normal_mode_red_light_when_a_payment_is_held(s):
    s.gate.propose(ProposedAction("payout", "120.00", "USD", D_, "logo design invoice"))
    src, alt, _, _, sec = light(s.get("/")[1])
    assert src.endswith("bw-dot-trey-red-full-96.png") and alt == "Issue \u2014 payment held"
    assert "Status light Red" in sec


def test_paused_light_is_yellow_not_gray(s):
    page = s.get("/")[1]
    s.post("/act", token=token(page, "Pause"))
    src, alt, _, _, sec = light(s.get("/")[1])
    assert src.endswith("bw-dot-trey-yellow-full-96.png") and alt == "Paused / attention"
    assert "Status light Yellow" in sec and "Gray" not in sec


def test_list_rows_get_24px_glyph_dots_in_both_modes(s):
    s.gate.propose(ProposedAction("payout", "20.00", "USD", "writer@personal.example.com", "blog post"))
    s.gate.propose(ProposedAction("payout", "120.00", "USD", D_, "logo design invoice"))
    for mode in ("normal", "cvd"):
        page = s.get("/")[1]
        assert 'class="dot" src="/assets/dots/bw-dot-trey-green-full-glyph-24.png"' in page, mode
        assert 'class="dot" src="/assets/dots/bw-dot-trey-yellow-full-glyph-24.png"' in page, mode
        assert 'width="24" height="24" alt=""' in page   # the label text next to it carries the meaning
        if mode == "normal":
            s.post("/act", token=token(s.get("/settings")[1], "Turn on color-blind mode"))


# ---------------------------------------------------------------- the switch
def test_switch_is_off_by_default_and_shown_in_settings(s):
    page = s.get("/settings")[1]
    assert "Color-blind mode" in page and "Turn on color-blind mode" in page
    assert "bw-dot-trey-cvd-red-x-96.png" in page and 'alt="Issue \u2014 payment held"' in page
    assert "ui" not in C.load_file(s.pf) and s.app.colorblind() is False


def test_switch_on_saves_policy_history_and_log_then_off_reverses(s):
    s.post("/act", token=token(s.get("/settings")[1], "Turn on color-blind mode"))
    pol = C.load_file(s.pf)
    assert pol["ui"] == {"colorblind_mode": True} and validate(pol)
    assert C.snapshot(pol) == C.snapshot(BASE)            # display only: no check, mode or trust changed
    ev = [r for r in s.gate.audit.records() if r["event"] == "ui_pref_changed"]
    assert len(ev) == 1 and ev[0]["value"] is True and ev[0]["key"] == "colorblind_mode"
    assert len(C.versions(s.pf)) == 1
    src, alt, webp, cvd, _ = light(s.get("/")[1])
    assert cvd == "1" and src == "/assets/dots/bw-dot-trey-cvd-green-check-128.png" and alt == "All clear"
    assert "bw-dot-trey-cvd-green-check-256.webp 2x" in webp and 'width="96"' in light(s.get("/")[1])[4]
    s.gate.propose(ProposedAction("payout", "120.00", "USD", D_, "logo design invoice"))
    src, alt, *_ = light(s.get("/")[1])
    assert src.endswith("bw-dot-trey-cvd-red-x-128.png") and alt == "Issue \u2014 payment held"
    s.post("/act", token=token(s.get("/settings")[1], "Turn off color-blind mode"))
    assert C.load_file(s.pf)["ui"] == {"colorblind_mode": False}
    assert len([r for r in s.gate.audit.records() if r["event"] == "ui_pref_changed"]) == 2
    src, *_ = light(s.get("/")[1])
    assert src.endswith("bw-dot-trey-red-full-96.png")


def test_cvd_paused_is_the_bang_orb(s):
    s.post("/act", token=token(s.get("/settings")[1], "Turn on color-blind mode"))
    s.post("/act", token=token(s.get("/")[1], "Pause"))
    src, alt, *_ = light(s.get("/")[1])
    assert src.endswith("bw-dot-trey-cvd-yellow-bang-128.png") and alt == "Paused / attention"


def test_switch_does_not_touch_money_or_need_restart(s):
    s.post("/act", token=token(s.get("/settings")[1], "Turn on color-blind mode"))
    assert "Restart Bridge Warden to use them" not in s.get("/settings")[1]
    out = s.gate.propose(ProposedAction("payout", "120.00", "USD", D_, "logo design invoice"))
    assert out["verdict"] == "hold" and not s.gate.paypal.calls


def test_set_ui_pref_same_value_is_no_change_and_bad_key_never_written(s):
    assert C.set_ui_pref(s.pf, "colorblind_mode", False, s.gate.audit)["status"] == "no_change"
    before = s.pf.read_bytes()
    with pytest.raises(PolicyError):
        C.set_ui_pref(s.pf, "font", "big", s.gate.audit)
    assert s.pf.read_bytes() == before and C.versions(s.pf) == []


def test_old_switch_button_cannot_be_replayed(s):
    t = token(s.get("/settings")[1], "Turn on color-blind mode")
    s.post("/act", token=t)
    r, _ = s.post("/act", token=t)
    assert r.status == 403


def test_view_only_run_keeps_the_switch_for_the_session_only(ro):
    before = ro.pf.read_bytes()
    page = ro.get("/settings")[1]
    assert "this session only" in page
    ro.post("/act", token=token(page, "Turn on color-blind mode"))
    assert ro.pf.read_bytes() == before and ro.app.colorblind() is True
    assert light(ro.get("/")[1])[3] == "1"
    ro.post("/act", token=token(ro.get("/settings")[1], "Turn off color-blind mode"))
    assert ro.app.colorblind() is False


def test_js_poll_swaps_light_and_uses_yellow_word():
    assert "'Yellow'" in SCRIPT and "'Gray'" not in SCRIPT
    assert "img.light" in SCRIPT and "data-cvd" in SCRIPT and "im.alt=" in SCRIPT
    assert "Paused / attention" in SCRIPT and "All clear" in SCRIPT and "payment held" in SCRIPT


# ---------------------------------------------------------------- 2026-10-26: full dots ("you made my dot a ring")
@pytest.mark.parametrize("c", ["green", "red", "yellow"])
def test_full_dot_files_exist_square_clear_corner_solid_middle(c):
    import struct, zlib
    for var in ("full", "full-glyph"):
        for px in (24, 48, 96, 128, 256):
            b = (FULL / f"bw-dot-trey-{c}-{var}-{px}.png").read_bytes()
            w, h, ctype, a0 = _png_info(b)
            assert (w, h) == (px, px) and ctype == 6 and a0 == 0, (c, var, px)   # clear outside the halo
            wb = (FULL / f"bw-dot-trey-{c}-{var}-{px}.webp").read_bytes()
            assert wb[:4] == b"RIFF" and wb[8:12] == b"WEBP" and wb[12:16] in (b"VP8X", b"VP8L")
    # the middle of the dot is solid now (the ring set had a see-through middle): check the 256 png centre
    b = (FULL / f"bw-dot-trey-{c}-full-256.png").read_bytes()
    i, idat = 8, b""
    while i < len(b):
        n, t = struct.unpack(">I4s", b[i:i + 8])
        if t == b"IDAT":
            idat += b[i + 8:i + 8 + n]
        i += 12 + n
    raw, stride = zlib.decompress(idat), 1 + 256 * 4
    rows, prev = [], bytearray(256 * 4)
    for y in range(256):                                  # un-filter (PNG filters 0-4)
        f, line = raw[y * stride], bytearray(raw[y * stride + 1:(y + 1) * stride])
        for x in range(len(line)):
            a = line[x - 4] if x >= 4 else 0
            up = prev[x]
            ul = prev[x - 4] if x >= 4 else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + up) & 255
            elif f == 3: line[x] = (line[x] + (a + up) // 2) & 255
            elif f == 4:
                pp = a + up - ul; pa, pb, pc = abs(pp - a), abs(pp - up), abs(pp - ul)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else ul)) & 255
        rows.append(line); prev = line
    for (x, y) in ((128, 128), (100, 128), (128, 90), (160, 160)):
        assert rows[y][x * 4 + 3] == 255, (c, x, y)
    assert (FULL / "source" / f"trey-ring-{c}.jpg").read_bytes() == (ENERGY / "source" / f"trey-ring-{c}.jpg").read_bytes()


def test_old_ring_set_is_still_on_disk_but_the_page_uses_the_full_set(s):
    for c in ("green", "red", "yellow"):
        assert (ENERGY / f"bw-dot-trey-{c}-ring-96.png").is_file() and (ENERGY / f"bw-dot-trey-{c}-glyph-24.png").is_file()
    assert "k+'-full'" in SCRIPT and "-ring'" not in SCRIPT
    for state in ("green", "red", "gray"):
        base, _ = light_files(state, False)
        assert base.endswith("-full-") and DOT_FILES[base.rsplit("/", 1)[1] + "96.png"].parent == FULL
    assert "NOTICE.md.bak" not in [p.name for p in FULL.iterdir()]
