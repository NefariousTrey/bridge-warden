"""v6: the "BW Light" AG Studio custom widget, server side.

The widget (static/bw-light-widget.js) shows the account's light (red / yellow / green) with Trey's BW dots, the last
alert reason, and two owner buttons: "I've seen this" and "It's fixed". The buttons call Bridge Warden's EXISTING rules
only; nothing new can turn the light green:
  - "I've seen this" = the same step as Home's "Got it, I've seen the blocked ones" (red -> yellow), or the BW AG
    Grid agent's own "I've seen this" for every open red issue it raised.
  - "It's fixed"     = the same step as Home's "It's fixed, confirm" (D.owner_light_ok), or the agent issue's own
    "It's fixed" (AG.mark_fixed). Red never goes straight to green: those rules refuse it, and so does this file.
No approve, no send, no release of a hold, no money path. Ignore stays on Home / History (it needs "I'm sure").
Every click needs the owner's login, the same origin, and a one-time token bound to the light it was shown for.
The AI chat panel has no tool for this; the browser side also drops clicks that are not a real person's click.
Made by @Nefarious_Trey,
with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
"""
from __future__ import annotations

import html

from . import ag_agent as AG
from . import dashboard as D

BY = "owner (AG Studio widget)"          # starts with "owner": the existing owner-only checks still apply
STEPS = ("seen", "fixed")
COLOR = {"green": "green", "red": "red", "gray": "yellow"}
WORD = {"green": "Green", "red": "Red", "gray": "Yellow"}
CVD = {"green": "cvd-green-check", "red": "cvd-red-x", "gray": "cvd-yellow-bang"}
PURPOSE = "studio:light:"                # purpose = studio:light:<step>:<seq the light was read at>


def dot(state: str, cvd: bool = False) -> dict:
    """The BW dot image for this light (served from the existing /assets/dots/ allowlist)."""
    if cvd:
        b = f"/assets/dots/bw-dot-trey-{CVD[state]}-"
        return {"src": b + "128.png", "src2x": b + "256.png"}
    b = f"/assets/dots/bw-dot-trey-{COLOR[state]}-full-"
    return {"src": b + "96.png", "src2x": b + "128.png"}


_RED_LEAD = "Light set to red: something bad happened. It stays red until you respond. "


def _plain(text: str) -> str:
    """The History line without its fixed red lead-in (the widget already says red)."""
    return text[len(_RED_LEAD):] if text.startswith(_RED_LEAD) and len(text) > len(_RED_LEAD) else text


def last_alert(records: list, tz: str) -> dict | None:
    """The last time the light went red: when and why (Bridge Warden's own words, never agent text)."""
    for r in reversed(records):
        if r.get("event") == D.LIGHT_EVENT and r.get("to") == "red":
            return {"at": D.local_time(r.get("at", ""), tz) if r.get("at") else "", "why": r.get("why", ""),
                    "text": _plain(str(r.get("text", "")))[:300]}
    return None


def _open_ag(records: list, status: str) -> list:
    return [i["id"] for i in AG.issues(records) if i["status"] == status]


def plan(gate) -> dict:
    """Which owner step fits the light right now (if any), and where to go otherwise. Read-only."""
    st = D.status(gate, log=False)
    recs = gate.audit.records()
    why, state = st.get("why"), st["state"]
    seen = fixed = None
    hint = ""
    if state == "red":
        if why == "needs_you":
            seen = "blocks"
            if st.get("waiting"):
                hint = "Held payments still need your yes or no on Home. This button never sends them."
        elif why == "ag_agent":
            seen = "ag"
        elif why == "off":
            hint = "Bridge Warden is off. Turn it back on in Settings (it steps to yellow first)."
        else:
            hint = "Open Home and clear it there."
        hint = hint or "Red never goes straight to green. Tap I've seen this first."
    elif state == "gray":
        if why == "seen_fix":
            fixed = "light"
        elif why == "ag_agent" and _open_ag(recs, "yellow"):
            fixed = "ag"
        elif why == "fix":
            hint = "A held payment still needs your yes or no on Home."
        elif why == "check":
            hint = "Clear the check in Settings."
        elif why in ("paused", "paused_safety"):
            hint = "Bridge Warden is paused. Resume it on Home."
    return {"status": st, "seen": seen, "fixed": fixed, "hint": hint}


def state(app) -> dict:
    """GET /ag-studio/light.json: what the widget shows, plus one-time tokens for the steps that fit right now."""
    gate = app.gate
    p = plan(gate)
    st = p["status"]
    tz = gate.engine.p.get("owner_timezone", "UTC")
    cvd = bool(app.colorblind()) if callable(getattr(app, "colorblind", None)) else False
    seq = st.get("seq", 0)
    tokens = {s: app.issue_nonce("-", "-", f"{PURPOSE}{s}:{seq}") for s in STEPS if p[s]}
    return {"light": COLOR[st["state"]], "word": WORD[st["state"]], "text": st.get("text", ""),
            "dot": dot(st["state"], cvd), "alt": f"{WORD[st['state']]} light",
            "last_alert": last_alert(gate.audit.records(), tz), "hint": p["hint"],
            "can": {s: bool(p[s]) for s in STEPS}, "tokens": tokens,
            "rules": "Red never goes straight to green. Only you can turn it green. Agents can only raise it."}


def step(app, purpose: str) -> dict:
    """Run one owner step. `purpose` came from a one-time token already taken by the caller. Never moves money."""
    gate = app.gate
    try:
        _, _, what, seq = purpose.split(":", 3)
        seq = int(seq)
    except ValueError:
        return {"ok": False, "why": "unknown step"}
    if what not in STEPS:
        return {"ok": False, "why": "unknown step"}
    p = plan(gate)
    kind = p[what]
    if kind is None:
        if what == "fixed" and p["status"]["state"] == "red":
            gate.audit.write("owner_light_ok_refused", action_id="-", mode="fixed", by=BY,
                             why="red never goes straight to green: respond to the red first")
            return {"ok": False, "why": "the light is still red. Tap I've seen this first (it steps down to yellow)"}
        return {"ok": False, "why": p["hint"] or "nothing is waiting for that step"}
    recs = gate.audit.records()
    if what == "seen" and kind == "blocks":
        gate.audit.write("owner_saw_blocks", action_id="-", upto_seq=seq, by=BY)
        r = {"ok": True}
    elif what == "seen":
        rs = [AG.mark_seen(gate, iid, by=BY) for iid in _open_ag(recs, "red")]
        r = {"ok": bool(rs) and all(x["ok"] for x in rs)}
    elif kind == "light":
        r = D.owner_light_ok(gate, "fixed", by=BY)
    else:
        rs = [AG.mark_fixed(gate, iid, by=BY) for iid in _open_ag(recs, "yellow")]
        r = {"ok": bool(rs) and all(x["ok"] for x in rs)}
    st = D.status(gate)                   # logs the new color, like every other owner step
    if not r.get("ok"):
        return {"ok": False, "why": r.get("why") or "nothing changed", "light": COLOR[st["state"]]}
    return {"ok": True, "light": COLOR[st["state"]], "text": st.get("text", "")}


# ---- the compact BW Light on every BW page (server-rendered; no script, so it works without AG Studio) -------------
# Same owner rules: its two buttons are plain owner forms to /act with the same one-time tokens (studio:light:...)
# and run step() above. It sits in the page flow under the status bar (never floats over content).
BACKS = {"home": "/", "money": "/money", "history": "/history", "settings": "/settings", "judges": "/judges"}
LABEL = {"seen": "I've seen this", "fixed": "It's fixed"}
CSS = (".bwl{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:10px 0 14px;overflow:hidden}"
       ".bwl-h{display:flex;align-items:center;gap:8px;padding:6px 12px;background:#FFFFFF;color:#0B1220;"
       "border-bottom:1px solid #E5E7EB;font-size:14px}.bwl-h svg{width:22px;height:22px}"
       ".bwl-h small{margin-left:auto;color:#4B5563;font-size:12px}"
       ".bwl-b{display:flex;align-items:center;gap:12px;padding:8px 12px;flex-wrap:wrap}"
       ".bwl-dot{width:36px;height:36px;flex:0 0 36px}.bwl-t{flex:1 1 280px;min-width:0;font-size:14px}"
       ".bwl-a{color:var(--soft)}.bwl-acts{display:flex;gap:8px;flex-wrap:wrap}.bwl-acts form{margin:0}"
       ".bwl-acts .btn{min-height:36px;padding:6px 12px;font-size:14px}")


def compact_html(d: dict | None, active: str = "") -> str:
    """The compact BW Light card. `d` is state(app). Plain HTML: dot, word, last alert, the two owner buttons."""
    if not d:
        return ""
    e = html.escape
    back = BACKS.get(active, "/")
    la = d.get("last_alert")
    if la:
        t = la.get("text") or ""
        t = t if len(t) <= 140 else t[:139].rstrip() + "\u2026"
        alert = f'Last alert{" (" + e(la["at"]) + ")" if la.get("at") else ""}: {e(t)}'
    else:
        alert = "No alerts yet."
    note = d.get("hint") or ""
    note_html = f'<br><span class="bwl-a">{e(note)}</span>' if note else ""
    acts = []
    for s in STEPS:
        if d["can"].get(s) and d["tokens"].get(s):
            acts.append(f'<form method="post" action="/act"><input type="hidden" name="token" value="{e(d["tokens"][s])}">'
                        f'<input type="hidden" name="back" value="{e(back)}">'
                        f'<button class="btn bwl-{s}" type="submit">{e(LABEL[s])}</button></form>')
        else:
            acts.append(f'<button class="btn bwl-{s}" type="button" disabled>{e(LABEL[s])}</button>')
    img = (f'<img class="bwl-dot" src="{e(d["dot"]["src"])}" srcset="{e(d["dot"]["src2x"])} 2x" '
           f'alt="{e(d["alt"])}" width="36" height="36">')
    return (f'<aside class="bwl bwl-{e(d["light"])}" aria-label="BW Light" data-light="{e(d["light"])}">'
            '<div class="bwl-h"><svg viewBox="0 0 48 48" aria-hidden="true" focusable="false"><use href="#logo"/></svg>'
            '<b>BW Light</b><small>Only you can turn it green.</small></div>'
            f'<div class="bwl-b">{img}<span class="bwl-t"><b>{e(d["word"])}.</b> <span class="bwl-a">{alert}</span>'
            f'{note_html}</span>'
            f'<span class="bwl-acts">{"".join(acts)}</span></div></aside>')


def act(app, purpose: str) -> tuple[str, str]:
    """/act for a compact-card button (token already taken by the caller): (message, kind)."""
    r = step(app, purpose)
    if r["ok"]:
        return {"yellow": "Marked as seen. The light is yellow.", "green": "Confirmed fixed. The light is green."}.get(
            r["light"], "Done.") + " Logged in History.", "ok"
    return "Nothing changed: " + r["why"] + ".", "warn"
