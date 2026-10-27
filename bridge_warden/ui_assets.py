"""Bridge Warden's own icon set and logo (v4). Drawn for this project: simple 24x24 line icons,
2px round strokes, no fills, colour from the surrounding text (currentColor). No third-party art.

The same shapes are inlined in each page as an SVG sprite (<use href="#i-name">) and written to
bridge_warden/ui/icons/*.svg (served from /assets/ by the local page, never from a CDN)."""
from __future__ import annotations

ICONS = {
    "money": ('<rect x="3" y="6.5" width="18" height="12.5" rx="2.2"/><path d="M3 10h18"/>'
              '<path d="M15.5 14.8h2.5"/><path d="M6 6.5 15.8 3.6l1.2 2.9"/>'),
    "chat": ('<path d="M4 5.5h16v10.2H10.2L6 19.5v-3.8H4z"/><path d="M8 9.6h8M8 12.6h5"/>'),
    "ai": ('<rect x="6.5" y="6.5" width="11" height="11" rx="1.6"/><path d="M10 10h4v4h-4z"/>'
           '<path d="M9.5 3.2v3.3M14.5 3.2v3.3M9.5 17.5v3.3M14.5 17.5v3.3M3.2 9.5h3.3M3.2 14.5h3.3'
           'M17.5 9.5h3.3M17.5 14.5h3.3"/>'),
    "phone": ('<path d="M6.6 3.6h2.9l1.4 4.1-2 1.4a10.6 10.6 0 0 0 6 6l1.4-2 4.1 1.4v2.9a1.9 1.9 0 0 1-2.1 1.9'
              'A15.6 15.6 0 0 1 4.7 5.7a1.9 1.9 0 0 1 1.9-2.1z"/>'),
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.2 10.5V8a3.8 3.8 0 0 1 7.6 0v2.5"/>',
    "send": '<path d="M20.5 3.5 10.2 13.8"/><path d="M20.5 3.5 14.2 20.4l-4-6.6-6.6-4z"/>',
    "approve": '<circle cx="12" cy="12" r="9"/><path d="m7.6 12.4 3 3 5.9-6.4"/>',
    "hold": ('<path d="M7 3.5h10M7 20.5h10"/><path d="M8.2 3.5v2.2c0 2.1 1.5 3.5 3.8 6.3 2.3-2.8 3.8-4.2 3.8-6.3V3.5"/>'
             '<path d="M8.2 20.5v-2.2c0-2.1 1.5-3.5 3.8-6.3 2.3 2.8 3.8 4.2 3.8 6.3v2.2"/>'),
    "cancel": '<circle cx="12" cy="12" r="9"/><path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6"/>',
    "why": ('<circle cx="12" cy="12" r="9"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.5"/>'
            '<path d="M12 16.9v.2"/>'),
    "pause": '<rect x="6.5" y="5" width="3.6" height="14" rx="1.2"/><rect x="13.9" y="5" width="3.6" height="14" rx="1.2"/>',
    "resume": '<path d="M8.2 5.6v12.8a.8.8 0 0 0 1.2.7l9.9-6.4a.8.8 0 0 0 0-1.4L9.4 4.9a.8.8 0 0 0-1.2.7z"/>',
    "settings": ('<path d="M4 7h9.2M16.8 7H20M4 17h3.2M10.8 17H20"/><circle cx="15" cy="7" r="1.8"/>'
                 '<circle cx="9" cy="17" r="1.8"/>'),
    "shield": ('<path d="M12 3.2 4.8 6.1v5.4c0 4.5 3 8 7.2 9.3 4.2-1.3 7.2-4.8 7.2-9.3V6.1z"/>'
               '<path d="m8.9 12.1 2.2 2.2 4.1-4.4"/>'),
    "trusted": ('<circle cx="9.5" cy="8" r="3.4"/><path d="M3.6 19.6c.6-3.5 2.9-5.3 5.9-5.3 1.4 0 2.7.4 3.7 1.1"/>'
                '<path d="m14.9 17.9 2 2 4-4.4"/>'),
    "history": '<path d="M3.8 12a8.2 8.2 0 1 0 2.5-5.9"/><path d="M3.8 4.6v3.9h3.9"/><path d="M12 7.8V12l2.9 1.9"/>',
    "export": ('<path d="M12 3.6v10.6"/><path d="m7.8 10 4.2 4.2 4.2-4.2"/>'
               '<path d="M4.6 15.4v3a2 2 0 0 0 2 2h10.8a2 2 0 0 0 2-2v-3"/>'),
    "blocked": '<path d="M8.4 3.2h7.2l5.2 5.2v7.2l-5.2 5.2H8.4l-5.2-5.2V8.4z"/><path d="M7.8 12h8.4"/>',
    "bell": '<path d="M6.2 16.4V11a5.8 5.8 0 0 1 11.6 0v5.4l1.6 2H4.6z"/><path d="M10 20.4a2 2 0 0 0 4 0"/>',
    "home": '<path d="M4 11.2 12 4.4l8 6.8"/><path d="M6.2 9.6v10h11.6v-10"/><path d="M10 19.6v-5h4v5"/>',
    "keyboard": ('<rect x="2.8" y="6.2" width="18.4" height="11.6" rx="2"/>'
                 '<path d="M6.5 10h.1M9.5 10h.1M12.5 10h.1M15.5 10h.1M6.5 13.8h.1M17.5 13.8h.1M9.2 13.8h5.6"/>'),
}

ICON_LABELS = {"money": "Money", "chat": "Ask AI", "ai": "AI check", "phone": "Call alert", "lock": "Private", "send": "Send", "approve": "Approve", "hold": "Keep waiting", "cancel": "Cancel", "why": "Why",
               "pause": "Pause", "resume": "Resume", "settings": "Settings", "shield": "Status",
               "trusted": "Trusted list", "history": "History", "export": "Export", "blocked": "Blocked",
               "bell": "Alerts", "home": "Home", "keyboard": "Keyboard"}

# Logo mark: a shield with a bridge across it (the warden stands on the bridge, between you and the world).
# v4 brand: "BW" monogram. Corporate first (near-black navy, crisp white letters), one electric accent
# (cyan) as a thin circuit/shield line. Three variants; the UI uses "shield". Original artwork.
INK_DARK, ACCENT = "#0B1220", "#22D3EE"
_B = ('<path d="M13.5 14.5V31M13.5 14.5h5q3.5 0 3.5 4.05t-3.5 4.05h-5M18.5 22.6h.7q3.6 0 3.6 4.2T19.2 31h-5.7" '
      'fill="none" stroke="#F8FAFC" stroke-width="2.6" stroke-linejoin="round"/>')
_W = ('<path d="M25.4 14.5 28.2 31 31 20.6 33.8 31 36.6 14.5" fill="none" stroke="#F8FAFC" stroke-width="2.6" '
      'stroke-linejoin="round" stroke-linecap="round"/>')
BRAND = {
    "shield": ('<path d="M24 2.5 42 8.5V22c0 11.5-7.5 19.8-18 23.5C13.5 41.8 6 33.5 6 22V8.5z" fill="#0B1220"/>'
               '<path d="M24 5.6 39 10.6V22c0 9.8-6.2 16.9-15 20.2C15.2 38.9 9 31.8 9 22V10.6z" fill="none" '
               'stroke="#22D3EE" stroke-width=".8" stroke-opacity=".75"/>'
               + _B + _W +
               '<path d="M14 35.5h7l3 3 3-3h7" fill="none" stroke="#22D3EE" stroke-width="1"/>'
               '<circle cx="14" cy="35.5" r="1.3" fill="#22D3EE"/><circle cx="34" cy="35.5" r="1.3" fill="#22D3EE"/>'),
    "tile": ('<rect x="3" y="3" width="42" height="42" rx="10" fill="#0B1220"/>'
             '<rect x="5.5" y="5.5" width="37" height="37" rx="8" fill="none" stroke="#22D3EE" stroke-width=".7" '
             'stroke-opacity=".55"/><g transform="translate(-0.5 -1.5)">' + _B + _W + '</g>'
             '<path d="M12 36.5h24" stroke="#22D3EE" stroke-width="1"/><rect x="22.6" y="35.1" width="2.8" '
             'height="2.8" fill="#22D3EE"/><circle cx="12" cy="36.5" r="1.3" fill="#22D3EE"/>'
             '<circle cx="36" cy="36.5" r="1.3" fill="#22D3EE"/>'),
    "hex": ('<path d="M24 2.5 42.5 13.2v21.6L24 45.5 5.5 34.8V13.2z" fill="#0B1220"/>'
            '<path d="M24 5.8 39.6 14.8v18.4L24 42.2 8.4 33.2V14.8z" fill="none" stroke="#22D3EE" '
            'stroke-width=".7" stroke-opacity=".6"/><g transform="translate(-0.5 0.5)">' + _B + _W + '</g>'
            '<path d="M5.5 24h4M38.5 24h4M24 36v6.2" stroke="#22D3EE" stroke-width="1"/>'
            '<circle cx="9.5" cy="24" r="1.2" fill="#22D3EE"/><circle cx="38.5" cy="24" r="1.2" fill="#22D3EE"/>'
            '<circle cx="24" cy="36" r="1.2" fill="#22D3EE"/>'),
}
BRAND_NAMES = {"shield": "A. Shield monogram (used in the app)", "tile": "B. Tile monogram",
               "hex": "C. Hex circuit monogram"}
LOGO_INNER = BRAND["shield"]
TAGLINE = "stands between everyone else and your money"


def icon_file(name: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="#14213D" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" role="img" '
            f'aria-label="{ICON_LABELS[name]}"><title>{ICON_LABELS[name]}</title>{ICONS[name]}</svg>\n')


def logo_file() -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48" role="img" '
            f'aria-label="Bridge Warden logo"><title>Bridge Warden</title>{LOGO_INNER}</svg>\n')


def lockup_file() -> str:
    """Logo with name and tagline, for docs and slides (system fonts only)."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 72" width="520" height="72" role="img" '
            f'aria-label="Bridge Warden: {TAGLINE}"><title>Bridge Warden</title>'
            f'<g transform="translate(4 12)">{LOGO_INNER}</g>'
            '<text x="64" y="38" font-family="system-ui, Segoe UI, Arial, sans-serif" font-size="28" '
            'font-weight="700" fill="#14213D">Bridge Warden</text>'
            '<text x="64" y="60" font-family="system-ui, Segoe UI, Arial, sans-serif" font-size="15" '
            f'fill="#4A5363">{TAGLINE}</text></svg>\n')


def sprite() -> str:
    syms = "".join(f'<symbol id="i-{n}" viewBox="0 0 24 24">{body}</symbol>' for n, body in ICONS.items())
    return ('<svg class="sprite" aria-hidden="true" focusable="false" width="0" height="0" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f'{syms}<symbol id="logo" viewBox="0 0 48 48">{LOGO_INNER}</symbol></svg>')


def brand_mark(name: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="96" height="96" role="img" '
            f'aria-label="Bridge Warden BW logo, {name}"><title>Bridge Warden</title>{BRAND[name]}</svg>\n')


def brand_lockup(name: str, dark: bool = False) -> str:
    bg = '<rect width="560" height="96" rx="14" fill="#0B1220"/>' if dark else ""
    ink, sub = ("#F8FAFC", "#A5F3FC") if dark else ("#0B1220", "#0E7490")
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 96" width="560" height="96" role="img" '
            f'aria-label="Bridge Warden: {TAGLINE}"><title>Bridge Warden</title>{bg}'
            f'<g transform="translate(16 16) scale(1.33)">{BRAND[name]}</g>'
            '<text x="96" y="50" font-family="Inter, system-ui, Segoe UI, Arial, sans-serif" font-size="32" '
            f'font-weight="700" letter-spacing=".3" fill="{ink}">Bridge Warden</text>'
            '<text x="97" y="76" font-family="Inter, system-ui, Segoe UI, Arial, sans-serif" font-size="16" '
            f'fill="{sub}">{TAGLINE}</text></svg>\n')


def brand_files() -> dict:
    out = {}
    for n in BRAND:
        out[f"bw-{n}.svg"] = brand_mark(n)
        out[f"bw-{n}-lockup-light.svg"] = brand_lockup(n)
        out[f"bw-{n}-lockup-dark.svg"] = brand_lockup(n, dark=True)
    return out


def asset_files() -> dict:
    out = {f"{n}.svg": icon_file(n) for n in ICONS}
    out["logo.svg"] = logo_file()
    out["lockup.svg"] = lockup_file()
    return out
