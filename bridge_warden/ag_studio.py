"""v6: optional AG Studio layer for the BW AG Grid agent (History page).

AG Studio (npm "ag-studio", by AG Grid Ltd) is COMMERCIAL software. It is NOT bundled in this Apache-2.0 repo.
If you want it, run scripts/fetch_ag_studio.sh: it downloads ag-studio@3.0.0 from npm and checks it against the
pinned SHA-256 below before saving it to bridge_warden/vendor/ag-studio/ (git-ignored). Without it, History still
shows the free AG Grid Community (MIT) spending grid and Bridge Warden's own History chat.

Unlicensed, AG Studio shows a watermark and console warnings. With an AG Studio licence (or trial) key in
BW_AG_STUDIO_LICENSE_KEY, the watermark goes away; the AI chat panel needs a key that includes AI.

The chat panel's model is xAI, called ONLY by this server (/ag-studio/v1/responses). Your xAI key never goes to the
browser and is never logged. The proxy forces the model, caps size and length, needs your login, keeps the same
Zero Data Retention gate as every other xAI call, and logs only token counts and cost (never text, never keys).
Made by @Nefarious_Trey, with Grok. Copyright 2026 Douglas Gibbons III. Apache-2.0.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

from . import help_chat as H
from . import judge_ai as JA

VERSION = "3.0.0"
BUNDLE = "ag-studio.min.js"
PINNED_SHA256 = "41b525170d224be3b5ceb4116d0952b39601a7198e0c44148bfa48aabf556a8e"   # npm ag-studio@3.0.0 dist/umd
VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "ag-studio"
GLUE = "bw-studio.js"
WIDGET = "bw-light-widget.js"      # v6: the BW Light custom widget (owner buttons call BW's own rules)
OWN = (WIDGET, GLUE)              # our two files, loaded after the pinned bundle, widget first
STATIC_DIR = Path(__file__).resolve().parent / "static"
LICENSE_ENV = "BW_AG_STUDIO_LICENSE_KEY"
XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
MAX_BODY = 256_000              # bytes from the browser
MAX_ITEMS = 60                  # conversation items per turn
MAX_TOOLS = 40
MAX_OUTPUT_TOKENS = 700         # short answers keep it cheap
EVENT = "ag_studio_chat"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_ALLOWED = {"input", "instructions", "tools", "tool_choice", "text", "parallel_tool_calls"}
STUDIO_RULES = ("You are the BW AG Grid agent inside Bridge Warden's History page. Stay on the user's own spending, "
                "subscriptions and Bridge Warden audit flags. You are read-only: you can look at data and arrange the "
                "dashboard, but you can never approve, ignore, acknowledge, turn the light green, release a hold or "
                "move money. Only the owner can, by clicking the buttons on the History page. If asked, point them "
                "to the button. Keep replies to 3 short sentences. Never invent amounts.")

_cache: dict = {}


def _file(path: Path):
    if not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _cache:
        b = path.read_bytes()
        _cache[key] = (b, hashlib.sha256(b).hexdigest(),
                       "sha256-" + base64.b64encode(hashlib.sha256(b).digest()).decode())
    return _cache[key]


def bundle():
    """(bytes, csp-hash) only if the vendored file matches the pinned hash; else None (never serve a changed file)."""
    f = _file(VENDOR_DIR / BUNDLE)
    return (f[0], f[2]) if f and f[1] == PINNED_SHA256 else None


def ready() -> bool:
    return bundle() is not None and all(_file(STATIC_DIR / n) is not None for n in OWN)


def static(name: str):
    """Serve only the Studio files (pinned bundle + our widget + our glue), and only when ready."""
    if not ready():
        return None
    if name == "vendor/" + BUNDLE:
        return bundle()
    if name in OWN:
        f = _file(STATIC_DIR / name)
        return f[0], f[2]
    return None


def csp_hashes() -> str:
    return " ".join(f"'{static(n)[1]}'" for n in ("vendor/" + BUNDLE,) + OWN) if ready() else ""


def scripts() -> str:
    return "".join(f'<script src="/static/{n}" integrity="{static(n)[1]}"></script>'
                   for n in ("vendor/" + BUNDLE,) + OWN)


PANEL_TITLE = "BW AG Grid agent, AG Studio dashboard and chat"
# v6: BW theming for the Studio panel: a white header with Trey's BW logo (served by /assets/brand/, allowlisted).
HEAD_CSS = ('.bw-head{display:flex;align-items:center;gap:10px;padding:8px 14px;background:#FFFFFF;color:#0B1220;'
            'border-bottom:1px solid #E5E7EB}.bw-head img{width:32px;height:32px}.bw-head b{font-size:15px}'
            '.bw-head small{color:#4B5563;margin-left:auto}'
            # BW theming: no teal select outline or corner resize handles on the widgets (they looked like a resizer
            # stuck on the card). Widgets keep a plain thin card border (page layout widgetBorder in bw-studio.js).
            '.bw-studio .ag-studio-layout-widget,.bw-studio .ag-studio-layout-widget:hover,'
            '.bw-studio .ag-studio-layout-widget.ag-studio-layout-widget-selected,'
            '.bw-studio .ag-studio-layout-widget.ag-studio-layout-widget-sibling-drag-interactive'
            '{--ag-studio-layout-widget-resize-border-color:transparent!important;'
            '--ag-studio-layout-widget-resize-handle-color:transparent!important}'
            '.bw-studio .ag-studio-layout-widget-focus,.bw-studio .ag-studio-layout-widget-focus .ag-studio-layout-widget-overlay'
            '{-webkit-box-shadow:none!important;box-shadow:none!important}'
            '.bw-studio .ag-studio-layout-widget:has(.bw-light)>.ag-studio-layout-widget-toolbar{display:none!important}')   # no edit icons on BW Light
HEAD_HTML = ('<header class="bw-head"><img src="/assets/brand/bw-mark-navy-v7b.png" '
             'srcset="/assets/brand/bw-mark-navy-v7b@2x.png 2x" alt="Bridge Warden"><b>Bridge Warden</b>'
             '<span>AG Studio: BW Light + spending</span><small>Only you can turn the light green.</small></header>')


def panel_html() -> str:
    """The AG Studio panel lives in its OWN small page, shown in an iframe on History (v6, 2026-10-27).
    Why: AG Studio sets inline style attributes, which History's strict CSP (rightly) blocks; blocked, its layout
    spilled over History and covered the owner's buttons. Isolated here, only this frame allows inline STYLES.
    Scripts are still only the two hash-pinned files. The frame has no forms and cannot navigate the page."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>' + PANEL_TITLE + '</title><style>html,body{margin:0;font:14px system-ui,sans-serif}#bw-studio{height:740px}'
            '#bw-studio-usage{margin:4px 8px;font-size:12px}' + HEAD_CSS + '</style></head>'
            '<body>' + HEAD_HTML + '<div id="bw-studio" class="bw-studio" role="region" aria-label="' + PANEL_TITLE + '" hidden></div>'
            '<p id="bw-studio-usage" aria-live="polite"></p>' + scripts() + '</body></html>')


def panel_csp() -> str:
    """Scripts: only the pinned bundle + our glue. Styles: inline allowed in THIS frame only (AG Studio needs it).
    No outside hosts. Framed only by Bridge Warden itself. No forms."""
    return (f"default-src 'none'; script-src {csp_hashes()}; style-src 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src data:; connect-src 'self'; worker-src blob:; form-action 'none'; frame-ancestors 'self'; "
            "base-uri 'none'")


PANEL_HEADERS_EXTRA = {"X-Frame-Options": "SAMEORIGIN", "Cache-Control": "no-store"}


def license_key(env=None) -> str:
    """The owner's AG Studio key from env. Never logged, never written to History."""
    k = (env if env is not None else os.environ).get(LICENSE_ENV, "").strip()
    # Real AG keys hold spaces (e.g. "{11 December 2026}"), so printable ASCII incl. space; no tabs/newlines.
    return k if re.fullmatch(r"[\x20-\x7e]{10,4000}", k or "") else ""


def config(app, env=None) -> dict:
    ai = getattr(app.gate, "ai", None)
    why = None
    if ai is None:
        why = "no xAI key set (XAI_API_KEY): the chat panel explains this instead of answering"
    else:
        why = ai.skip_reason()
    return {"license_key": license_key(env), "ai_ready": why is None, "ai_note": why or "",
            "name": "BW AG Grid agent", "cost_note": _cost_note()}


def _cost_note() -> str:
    key, counter = JA.current()
    if key and counter is not None:      # a judge on the hosted demo: our key, free to them, capped
        return (f"Real xAI, free to you on our key. You have {counter.left(key)} of {counter.limit} judge AI "
                "messages left. Under each answer: what xAI says it used.")
    return ("Each answer uses your own xAI key (billed to you). Under each answer: what xAI says it used. "
            "Remaining credit: " + H.NO_LIMIT + ".")


def _clean_request(raw: bytes):
    if len(raw) > MAX_BODY:
        return None, "too large"
    try:
        req = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "not JSON"
    if not isinstance(req, dict) or not isinstance(req.get("input"), list):
        return None, "bad request"
    body = {k: v for k, v in req.items() if k in _ALLOWED}
    if len(body["input"]) > MAX_ITEMS or len(body.get("tools") or []) > MAX_TOOLS:
        return None, "too many items"
    tools = body.get("tools") or []
    if not isinstance(tools, list) or any(not isinstance(t, dict) or t.get("type") != "function" for t in tools):
        return None, "only browser-side function tools are allowed (no server-side tools)"
    if _EMAIL.search(json.dumps(body)):
        return None, "contains an email address (not sent to xAI)"
    body["instructions"] = STUDIO_RULES + "\n\n" + str(body.get("instructions") or "")[:20_000]
    return body, None


def proxy(gate, raw: bytes, by: str = "owner (web)"):
    """POST /ag-studio/v1/responses -> (http status, dict). Same-origin + login checked by the caller."""
    body, bad = _clean_request(raw)
    if bad:
        gate.audit.write(EVENT, action_id="-", by=by, sent=False, why=bad)
        return 400, {"error": {"message": "Not sent to xAI: " + bad + "."}}
    ai = getattr(gate, "ai", None)
    why = "no xAI key set" if ai is None else (ai.skip_reason() or ai._budget_reason())
    if not why and ai.cfg.get("require_zdr", True):
        if ai._zdr_state is None:
            try:
                ai._preflight_zdr()
            except JA.JudgeAiLimit:
                why = JA.SKIP
            except Exception:
                ai._record(False)
        why = why or (None if ai._zdr_state else "zdr_header_not_true")
    if why == JA.SKIP:          # judge allowance used up: nothing sent, no cost
        gate.audit.write(EVENT, action_id="-", by=by, sent=False, why=JA.SKIP)
        return 429, {"error": {"message": JA.LIMIT_NOTE + ". Bridge Warden's own History chat still works."}}
    if why:
        gate.audit.write(EVENT, action_id="-", by=by, sent=False, why=str(why)[:120])
        return 503, {"error": {"message": f"AI not used: {why}. Bridge Warden's own History chat still works."}}
    body.update(model=ai.cfg["model"], stream=False, store=False, max_output_tokens=MAX_OUTPUT_TOKENS)
    try:
        status, headers, out = ai._send_counted("POST", XAI_RESPONSES_URL, ai._headers(), json.dumps(body).encode(),
                                                ai.cfg["timeout_seconds"])
        hv = (headers or {}).get("x-zero-data-retention")
        if ai.cfg.get("require_zdr", True) and str(hv).lower() != "true":
            ai._zdr_state = False      # the answer is thrown away below and no later call is made
        data = json.loads(out or b"{}")
        if status != 200 or not isinstance(data, dict):
            raise ValueError(f"HTTP {status}")
        ai._record(True)
    except JA.JudgeAiLimit:
        gate.audit.write(EVENT, action_id="-", by=by, sent=False, why=JA.SKIP)
        return 429, {"error": {"message": JA.LIMIT_NOTE + ". Bridge Warden's own History chat still works."}}
    except Exception as ex:
        ai._record(False)
        gate.audit.write(EVENT, action_id="-", by=by, sent=True, ok=False, why=ai._scrub(type(ex).__name__)[:80])
        return 502, {"error": {"message": "xAI did not answer. Nothing changed."}}
    if ai.cfg.get("require_zdr", True) and ai._zdr_state is False:
        gate.audit.write(EVENT, action_id="-", by=by, sent=True, ok=False, why="zdr_header_not_true")
        return 503, {"error": {"message": "AI answer thrown away: xAI did not confirm zero data retention."}}
    u = data.get("usage") or {}
    usage = {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens"),
             "cost_in_usd_ticks": u.get("cost_in_usd_ticks")}
    line = H.usage_line({"called": True, "usage": usage})
    gate.audit.write(EVENT, action_id="-", by=by, sent=True, ok=True, usage=usage,
                     tools_called=[str(i.get("name", ""))[:40] for i in data.get("output") or []
                                   if isinstance(i, dict) and i.get("type") == "function_call"][:10])
    data["bw_usage"] = line
    return 200, data
