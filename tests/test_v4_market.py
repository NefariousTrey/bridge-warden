"""v4 Market price column (History grid). Made by @Nefarious_Trey, with Grok.
Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
Checks the difference % and ring-flag logic, the EXAMPLE price file, /moves.json and the click-through page."""
import json
import urllib.parse

import pytest

from test_v4_ui import GIFT, NEW, setup  # noqa: F401  (fixture)
from bridge_warden import market_price as MP, web
from bridge_warden.models import ProposedAction as P

ITEMS = MP.load_examples()


# ---------------------------------------------------------------- difference %
@pytest.mark.parametrize("amount,market,want", [
    ("100", 100, 0.0), ("150", 100, 50.0), ("40", 450, -91.1), ("19", 20, -5.0), ("0", 50, -100.0),
    ("249", 120, 107.5)])
def test_diff_pct(amount, market, want):
    assert MP.diff_pct(amount, market) == want


@pytest.mark.parametrize("amount,market", [("10", 0), ("10", -5), ("x", 10), (None, 10), ("10", None), ("-1", 10)])
def test_diff_pct_unknown_is_none(amount, market):
    assert MP.diff_pct(amount, market) is None


# ---------------------------------------------------------------- ring flags
@pytest.mark.parametrize("pct,ring", [
    (-91.1, "red"), (-60.1, "red"), (-60.0, "yellow"), (-31, "yellow"), (-30, "green"), (0, "green"),
    (25, "green"), (25.1, "yellow"), (99.9, "yellow"), (100, "red"), (300, "red")])
def test_buy_and_pay_flags(pct, ring):
    for act in ("create_order", "payout"):
        assert MP.price_flag(act, pct)[0] == ring


@pytest.mark.parametrize("pct,ring", [(-80, "green"), (10, "green"), (10.1, "yellow"), (50, "yellow"), (50.1, "red")])
def test_refund_flags(pct, ring):
    assert MP.price_flag("refund", pct)[0] == ring


def test_no_market_price_is_no_flag():
    ring, words = MP.price_flag("create_order", None)
    assert ring is None and "No market price" in words


def test_too_low_line_matches_the_live_price_check():
    from bridge_warden import price_check
    assert MP.TOO_LOW_RED == price_check.TOO_LOW


def test_worst_ring_wins():
    assert MP.worst("green", "red") == "red" and MP.worst("yellow", "green") == "yellow"
    assert MP.worst("green", None) == "green" and MP.worst(None) == "yellow"


# ---------------------------------------------------------------- EXAMPLE price file
def test_example_file_is_labelled_example_and_generic():
    data = json.loads(MP.EXAMPLE_FILE.read_text(encoding="utf-8"))
    assert data["source"] == "example" and "EXAMPLE" in data["_about"] and "NOT real" in data["_about"]
    assert len(ITEMS) >= 10 and all(i["price"] > 0 for i in ITEMS)
    for brand in ("apple", "sony", "samsung", "nintendo", "nike", "playstation", "xbox", "iphone"):
        assert brand not in json.dumps(data).lower()


def test_broken_or_missing_file_means_no_prices(tmp_path):
    assert MP.load_examples(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"; bad.write_text("{not json", encoding="utf-8")
    assert MP.load_examples(bad) == []
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"items": [{"name": "x"}, {"name": "y", "keywords": ["y"], "example_price": -1},
                                         {"name": "Ok", "keywords": ["ok thing"], "example_price": 5}]}), encoding="utf-8")
    assert [i["name"] for i in MP.load_examples(odd)] == ["Ok"]


def test_match_whole_words_longest_wins():
    assert MP.match("Brand-new GAME CONSOLE, sealed", ITEMS)["name"] == "Game console"
    assert MP.match("wireless earbuds", ITEMS)["name"] == "Wireless earbuds"
    assert MP.match("bikes and bicycle", ITEMS)["name"] == "Used bike"
    assert MP.match("logo design invoice", ITEMS) is None
    assert MP.match("consoled", ITEMS) is None and MP.match("", ITEMS) is None


# ---------------------------------------------------------------- source flag (off by default)
def test_source_flag_defaults_to_example():
    assert MP.source_from_env({}) == "example"
    assert MP.source_from_env({"BW_MARKET_PRICES": "channel3"}) == "channel3"
    assert MP.source_from_env({"BW_MARKET_PRICES": "anything-else"}) == "example"


def test_channel3_uses_recorded_typical_only():
    recs = [{"event": "price_check", "action_id": "a1", "result": {"called": True, "offers": 5, "typical": 400.0}},
            {"event": "price_check", "action_id": "a2", "result": {"called": False}}]
    rec = MP.recorded_typicals(recs)
    assert rec == {"a1": 400.0}
    m = {"action_id": "a1", "action": "create_order", "amount": "100.00", "currency": "USD", "description": "laptop"}
    got = MP.for_move(m, ITEMS, rec, "channel3")
    assert got["market"] == 400.0 and got["market_source"] == "channel3" and got["diff_pct"] == -75.0
    got = MP.for_move({**m, "action_id": "a2"}, ITEMS, rec, "channel3")      # falls back to EXAMPLE
    assert got["market_source"] == "example" and got["market"] == 900.0
    assert MP.for_move({**m, "currency": "EUR"}, ITEMS, {}, "example")["market"] is None


# ---------------------------------------------------------------- the web side
CONSOLE = lambda: P("create_order", "40.00", "USD", NEW, "brand-new game console, ships today")
CHARGER = lambda: P("create_order", "19.00", "USD", "shop@store.example.com", "phone charger")


def rows_by_item(setup):
    return {r["item"]: r for r in json.loads(setup.get("/moves.json")[1])["rows"]}


def test_moves_json_has_market_fields(setup):
    setup.gate.propose(CONSOLE()); setup.gate.propose(CHARGER())
    d = json.loads(setup.get("/moves.json")[1])
    assert d["cvd"] is False and d["source"] == "example"
    rows = rows_by_item(setup)
    c = rows["Game console"]
    assert c["side"] == "Buy" and c["market"] == 450.0 and c["market_source"] == "example"
    assert c["diff_pct"] == -91.1 and c["risk"] == "red" and "Too good to be true" in c["risk_why"]
    assert c["dot"] == "/assets/dots/bw-dot-trey-red-full-glyph-24.png"
    assert c["link"].startswith("/history/move?id=")
    ch = rows["Phone charger"]
    assert ch["diff_pct"] == -5.0 and ch["market_text"] == "$20.00"


def test_unknown_item_text_is_redacted_and_has_no_price(setup):
    setup.gate.propose(P("payout", "250.00", "USD", "desk@personal.example.com", GIFT))
    r = json.loads(setup.get("/moves.json")[1])["rows"][0]
    assert r["market"] is None and r["diff_pct"] is None and r["market_text"] == "-"
    assert r["risk"] == "red" and "@" not in r["item"]


def test_colorblind_mode_uses_the_orbs(setup, monkeypatch):
    setup.gate.propose(CONSOLE()); setup.gate.propose(CHARGER())
    monkeypatch.setattr(type(setup.app), "colorblind", lambda self: True)
    d = json.loads(setup.get("/moves.json")[1])
    assert d["cvd"] is True
    dots = {r["risk"]: r["dot"] for r in d["rows"]}
    assert dots["red"] == "/assets/dots/bw-dot-trey-cvd-red-x-96.png"
    assert dots["red"].rsplit("/", 1)[1] in web.DOT_FILES


def test_every_dot_url_is_a_served_file():
    for cvd in (False, True):
        for ring in ("red", "yellow", "green"):
            for u in web.ring_dot(ring, cvd):
                assert u.startswith("/assets/dots/") and u.rsplit("/", 1)[1] in web.DOT_FILES, u


def test_click_through_page(setup):
    setup.gate.propose(CONSOLE())
    link = json.loads(setup.get("/moves.json")[1])["rows"][0]["link"]
    assert setup.req("GET", link)[0].status == 401                       # login needed
    r, body = setup.get(link)
    assert r.status == 200 and "Red: risky" in body
    assert "Safety check" in body and "Market price" in body and "EXAMPLE price" in body
    assert "-91.1%" in body and "Too good to be true" in body and "Back to Guard History" in body
    assert "never blocks" in body and "Signed records" in body


def test_click_through_unknown_or_odd_id_is_404(setup):
    for q in ("nope", "", "<script>", "../../etc"):
        assert setup.get("/history/move?id=" + urllib.parse.quote(q))[0].status == 404


def test_history_page_says_prices_are_examples(setup):
    setup.gate.propose(CONSOLE())
    body = setup.get("/history")[1]
    assert "EXAMPLE prices" in body and "bw-grid-v3.js" in body
    assert "<h2>Guard History</h2>" in body and 'aria-label="Guard History, sortable grid"' in body


def test_your_choice_column(setup):
    setup.gate.propose(CHARGER()); setup.gate.propose(P("payout", "250.00", "USD", "desk@personal.example.com", GIFT))
    rows = rows_by_item(setup)
    ch = rows["Phone charger"]                                   # new payee: held for the owner, not answered yet
    assert ch["kind"] == "held" and ch["choice"] == "Not yet" and ch["why"]
    blocked = [r for r in rows.values() if r["kind"] == "blocked"][0]
    assert blocked["choice"] == "Warden stopped it" and blocked["why"]


@pytest.mark.parametrize("status,by,want", [
    ("approved", "owner", "You sent it"), ("cancelled", "owner", "You cancelled it"), ("waiting", None, "Not yet"),
    ("expired", None, "No answer (timed out)"), ("failed", None, "Nothing needed"), ("failed", "owner", "You sent it"),
    ("blocked", "owner", "You sent it; recheck stopped it"), ("unknown", None, "-")])
def test_choice_text(status, by, want):
    assert web.choice_text({"status": status, "decided_by": by}) == want


def test_robots_still_hides_the_new_page():
    assert any("/history/move".startswith(p) for p in web.PRIVATE_PATHS)


# ---- Trey's logo watermark (his art, all rights reserved; see ASSETS_NOTICE.md) ----------------------------------

def test_watermark_files_and_route():
    from bridge_warden import web
    for n in web.MARK_FILES:
        b = web.mark_file(n)
        assert b and b[:8] == b"\x89PNG\r\n\x1a\n"
    assert web.mark_file("../web.py") is None and web.mark_file("bw-grid-v2.js") is None


def test_watermark_markup_is_decorative():
    from bridge_warden import web
    m = web.mark_img()
    assert 'aria-hidden="true"' in m and 'alt=""' in m and "style=" not in m
    assert "/assets/brand/bw-mark-navy-v7b@2x.png 2x" in m
    assert ".bw-mark{" in web.STYLE and "pointer-events:none" in web.STYLE
    assert "opacity" not in web.STYLE[web.STYLE.index(".bw-mark{"):].split("}")[0]   # solid, full colour


def test_logo_top_right_of_every_page():
    from bridge_warden import web
    p = web.page("T", "<h1>Hi</h1>", "", None)
    assert p.count('class="bw-mark') == 1
    head = p[p.index('<header class="top'):p.index("</header>")]
    assert 'class="bw-mark' in head                       # in the header, not over page content
    assert 'class="bw-mark' not in web.page("T", "<h1>Hi</h1>", "", None, mark=False)
    assert web.hear_page().count('class="bw-mark') == 1


def test_logo_orb_colour_follows_status():
    """The orb in the top-right logo matches the main status light: green / yellow (state gray) / red."""
    from bridge_warden import web
    assert web.MARK_STATES == {"green": ("mk-g", ""), "gray": ("mk-y", "-yellow"), "red": ("mk-r", "-red")}
    for state, (cls, suf) in web.MARK_STATES.items():
        p = web.page("T", "<h1>Hi</h1>", "", {"state": state, "text": "x"})
        assert f'class="status st-{state}"' in p                 # main status light
        assert f'<span class="bw-mark mk-{state}" aria-hidden="true">' in p   # logo follows it
        assert f".bw-mark.mk-{state} .{cls}" in web.STYLE          # CSS shows the matching image
        assert f"/assets/brand/bw-mark-white-v7b{suf}.png" in p and f"bw-mark-navy-v7b{suf}.png" in web.MARK_FILES
        assert f"bw-mark-white-v7b{suf}.png" in web.MARK_FILES and f"bw-mark-blue{suf}.png" in web.MARK_FILES
        assert f"bw-mark{suf}.png" in web.MARK_FILES                    # originals still served, untouched
    assert web.mark_state(None) == "green" and web.mark_state({"state": "weird"}) == "green"
    assert 'class="bw-mark mk-green"' in web.mark_img("<script>")   # unknown state never reaches the markup
    assert 'class="bw-mark mk-green"' in web.hear_page()           # no status on this page = normal green
    assert "style=" not in web.mark_img("red")                       # strict CSP: no inline styles
    assert "mk.className='bw-mark mk-'+d.state" in web.SCRIPT       # live poll keeps it in step


def test_logo_orb_variants_exist():
    """Yellow and red files: real PNGs, same size as the green art, and not just copies of it (stdlib only)."""
    import struct
    from bridge_warden import web
    size = lambda b: struct.unpack(">II", b[16:24])          # PNG IHDR width, height
    for x in ("", "@2x"):
        g, y, r = (web.mark_file(f"bw-mark{c}{x}.png") for c in ("", "-yellow", "-red"))
        assert size(g) == size(y) == size(r) == ((256, 256) if x else (128, 128))
        assert len({g, y, r}) == 3


def test_watermark_notice():
    from pathlib import Path
    t = (Path(__file__).resolve().parents[1] / "ASSETS_NOTICE.md").read_text(encoding="utf-8")
    assert "bw-mark.png" in t and "All rights reserved. NOT covered by the Apache license." in t


def test_logo_blue_back_variant_blends_with_header():
    """Trey (Oct 26): the white field inside the shield is header navy in the '-blue' copies; orb colours kept."""
    import struct, zlib
    assert "--navy:#0B1220" in web.STYLE and "header.top{background:var(--navy)" in web.STYLE
    assert web.MARK_BACKS == {"navy": "-navy-v7b", "white": "-white-v7b"}     # Trey's exact art (Oct 26, 10 PM ET)
    assert "bw-mark-navy-v7b-red.png" in web.mark_img("red") and "white-v7b" not in web.mark_img("green")
    assert '/assets/brand/bw-mark-white-v7b.png"' in web.mark_img("green", back="white")
    assert "bw-mark-navy-v7b" in web.mark_img("green", back="??")                 # unknown back = navy (default)
    for st in ("", "-yellow", "-red"):
        for x in ("", "@2x"):
            orig, blue = web.mark_file(f"bw-mark{st}{x}.png"), web.mark_file(f"bw-mark-blue{st}{x}.png")
            assert orig and blue and orig != blue and blue[:8] == b"\x89PNG\r\n\x1a\n"
    # middle of the white field (2x art: x=60,y=150) is navy in the blue copy, white in the original
    def px(data, x, y):
        w, h = struct.unpack(">II", data[16:24]); i, idat = 8, b""
        bd, ct = data[24], data[25]
        while i < len(data):
            n = struct.unpack(">I", data[i:i + 4])[0]; t = data[i + 4:i + 8]
            if t == b"IDAT": idat += data[i + 8:i + 8 + n]
            i += 12 + n
        assert bd == 8 and ct == 6
        raw, bpp, stride, prev, rows = zlib.decompress(idat), 4, w * 4, bytearray(w * 4), []
        p = 0
        for _ in range(h):
            f = raw[p]; line = bytearray(raw[p + 1:p + 1 + stride]); p += 1 + stride
            for k in range(stride):
                a = line[k - bpp] if k >= bpp else 0; b = prev[k]; c = prev[k - bpp] if k >= bpp else 0
                if f == 1: line[k] = (line[k] + a) & 255
                elif f == 2: line[k] = (line[k] + b) & 255
                elif f == 3: line[k] = (line[k] + (a + b) // 2) & 255
                elif f == 4:
                    pp = a + b - c; pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                    line[k] = (line[k] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            rows.append(line); prev = line
        return tuple(rows[y][x * 4:x * 4 + 4])
    assert min(px(web.mark_file("bw-mark@2x.png"), 60, 150)[:3]) > 200
    assert px(web.mark_file("bw-mark-blue@2x.png"), 60, 150)[:3] == (0x0B, 0x12, 0x20)


def test_history_pages_keep_white_logo_others_blue(setup):
    """Trey (Oct 26, 9:53 PM ET): AG Grid Guard History + its 'Why?' page use the WHITE-fill logo (bw-mark.png);
    every other page keeps the blue-fill copy. The orb still follows the status colour on both."""
    import re
    assert web.HISTORY_MARK_BACK == "white"
    setup.gate.propose(CONSOLE())                                       # a red move -> status not green
    link = json.loads(setup.get("/moves.json")[1])["rows"][0]["link"]
    for path in ("/history", link):
        body = setup.get(path)[1]
        assert '/assets/brand/bw-mark-white-v7b.png"' in body and 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body and "bw-mark-blue" not in body
        assert '<header class="top top-light">' in body                 # Oct 26 10:09 PM ET: white header here
        for suf in ("", "-yellow", "-red"):
            assert f'/assets/brand/bw-mark-white-v7b{suf}.png"' in body   # all three orb colours ready
        state = re.search(r'class="status st-(\w+)"', body).group(1)
        assert f'<span class="bw-mark mk-{state}" aria-hidden="true">' in body   # orb follows the light
    for path in ("/", "/money", "/settings"):
        body = setup.get(path)[1]
        # Oct 26 10:11 PM ET: ALL pages now white header + white logo
        assert "/assets/brand/bw-mark-white-v7b.png" in body and 'th-light" src="/assets/brand/bw-mark-navy' not in body and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in body
        assert '<header class="top top-light">' in body
    assert "mk.className='bw-mark mk-'+d.state" in web.SCRIPT          # live poll swaps the class on any page


def test_v7b_logo_files_are_trey_art_cropped_with_clear_outside():
    """v7b logo files: square, outside corners see-through, shield fill kept (navy / white), orb recoloured only."""
    from bridge_warden import web
    import struct, zlib
    def top_row(data):                       # decode only the first pixel row of an 8-bit RGBA PNG
        w, h = struct.unpack(">II", data[16:24]); assert data[24] == 8 and data[25] == 6
        i, idat = 8, b""
        while i < len(data):
            n = struct.unpack(">I", data[i:i + 4])[0]
            if data[i + 4:i + 8] == b"IDAT": idat += data[i + 8:i + 8 + n]
            i += 12 + n
        raw = zlib.decompressobj().decompress(idat, 1 + w * 4 + 64)
        f, line = raw[0], bytearray(raw[1:1 + w * 4])
        for k in range(len(line)):           # first row: the row above is all zeros
            a = line[k - 4] if k >= 4 else 0
            if f in (1, 4): line[k] = (line[k] + a) & 255
            elif f == 3: line[k] = (line[k] + a // 2) & 255
        return w, h, line
    for k in ("navy", "white"):
        files = []
        for c in ("", "-yellow", "-red"):
            for x, size in (("", 128), ("@2x", 256)):
                data = web.mark_file(f"bw-mark-{k}-v7b{c}{x}.png"); files.append(data)
                w, h, row = top_row(data)
                assert (w, h) == (size, size) and row[3] == 0 and row[-1] == 0   # outside corners see-through
        assert len(set(files)) == 6                                              # green / yellow / red really differ


def test_light_header_css_is_readable():
    """White header on Guard History: dark text on white, logo spot unchanged, mobile nav bar white too."""
    from bridge_warden import web
    assert web.HEADER_LIGHT == " top-light"
    assert "header.top.top-light{background:#fff;color:var(--ink)" in web.STYLE
    assert ".top-light .brand{color:var(--ink)}" in web.STYLE and ".top-light nav a{color:#1F2937}" in web.STYLE
    assert "@media (max-width:700px){.top-light nav{background:#fff}}" in web.STYLE
    assert "top-light .bw-mark" not in web.STYLE                       # same top-right logo spot as other pages
    assert '<header class="top top-light">' in web.page("T", "x", "", None, mark_back="white")
    assert web.ALL_WHITE_HEADERS is True                                  # Trey, Oct 26 10:11 PM ET: every page white
    for back in ("navy", "white"):
        p = web.page("T", "x", "", None, mark_back=back)
        assert '<header class="top top-light">' in p and "bw-mark-white-v7b" in p and 'th-light" src="/assets/brand/bw-mark-navy' not in p and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in p
    h = web.hear_page()
    assert '<header class="top top-light">' in h and "bw-mark-white-v7b" in h and 'th-light" src="/assets/brand/bw-mark-navy' not in h and 'th-dark" src="/assets/brand/bw-mark-navy-v7b' in h
    for n in web.MARK_FILES:                                               # navy files kept on disk, still served
        assert web.mark_file(n)
