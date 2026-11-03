"""v6 History page: the BW AG Grid agent section, the two help chats, and their owner-only buttons.
Server-rendered and CSP-safe (no inline styles or scripts; SVG charts use attributes only). The page works
without JavaScript; JS only adds the spending grid and enables Ignore after "I'm sure" is ticked.
Made by @Nefarious_Trey, with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
"""
from __future__ import annotations

import html
import math

from . import ag_agent as AG
from . import help_chat as H
from . import judge_ai as JA
from . import money_map as MM

CHAT_KEEP = 12          # messages kept per lane (in memory only; History keeps a redacted line per question)
LABEL = {"red": "Red: needs you", "yellow": "Yellow: paused", "fixed": "Fixed", "ignored": "Ignored", "info": "Note"}
GROUP_NAME = {"bills": "Bills", "subscriptions": "Subscriptions", "gas": "Gas", "food": "Food", "other": "Other"}


def e(s, n=2000):
    return html.escape(str(s if s is not None else "")[:n])


def money_report(app) -> dict:
    """Dev mode: SAMPLE data. Otherwise: your own History plus any PayPal lines the read-only money check got."""
    gate = app.gate
    now = gate.clock()
    if app.dev_view():
        lines = MM.sample_lines(now)
    else:
        lines = MM.lines_from_history(gate.audit.records())
        rep = getattr(app, "money_report", None) or {}
        lines += [dict(x, flags=[]) for x in rep.get("map_lines") or []]
    cfg = (gate.engine.p.get("money_map") or {})
    return MM.analyze(lines, cfg, now)


def grid_rows(app) -> dict:
    rep = money_report(app)
    rows = [{"date": ln["at"][:10], "merchant": ln["merchant"], "group": GROUP_NAME.get(ln["category"], "Other"),
             "group_key": ln["category"], "amount": ln["amount"] if ln["kind"] == "paid" else -ln["amount"],
             "kind": {"paid": "Paid", "refund": "Refund", "failed": "Failed"}.get(ln["kind"], ln["kind"]),
             "flags": "; ".join(f["text"] for f in ln.get("flags", [])), "sample": ln.get("source") == "sample"} for ln in rep["lines"]]
    return {"rows": rows[:500], "sample": rep.get("sample", False)}


# ---------------------------------------------------------------- charts (SVG, attributes only)
def donut(totals: dict) -> str:
    tot = sum(totals.values()) or 1
    r, c = 70, 2 * math.pi * 70
    off, segs, legend = 0.0, [], []
    for k in MM.CATEGORIES:
        v = totals.get(k, 0)
        if v <= 0:
            continue
        ln = c * v / tot
        segs.append(f'<circle cx="90" cy="90" r="{r}" fill="none" stroke="{MM.CAT_COLOR[k]}" stroke-width="28" '
                    f'stroke-dasharray="{ln:.2f} {c - ln:.2f}" stroke-dashoffset="{-off:.2f}" '
                    f'transform="rotate(-90 90 90)"><title>{GROUP_NAME[k]}: ${v:,.2f}</title></circle>')
        off += ln
        legend.append(f'<li><svg class="sw" viewBox="0 0 12 12" aria-hidden="true"><rect width="12" height="12" '
                      f'rx="3" fill="{MM.CAT_COLOR[k]}"/></svg><b>{GROUP_NAME[k]}</b> ${v:,.2f} '
                      f'<span class="fine">({100 * v / tot:.0f}%)</span></li>')
    return (f'<figure class="ag-chart"><svg viewBox="0 0 180 180" role="img" aria-label="Spending by group">'
            f'{"".join(segs)}<text x="90" y="86" text-anchor="middle" class="ag-big">${tot:,.0f}</text>'
            f'<text x="90" y="106" text-anchor="middle" class="ag-small">spent</text></svg>'
            f'<figcaption><ul class="ag-legend">{"".join(legend)}</ul></figcaption></figure>')


def month_bars(by_month: dict) -> str:
    months = list(by_month.items())[-6:]
    if not months:
        return ""
    top = max(sum(d.values()) for _, d in months) or 1
    w, h, bw = 320, 170, 36
    gap = (w - 20 - bw * len(months)) / max(1, len(months))
    out = []
    for i, (m, d) in enumerate(months):
        x, y = 20 + i * (bw + gap), h - 24
        for k in MM.CATEGORIES:
            v = d.get(k, 0)
            if v <= 0:
                continue
            bh = (h - 40) * v / top
            y -= bh
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw}" height="{bh:.1f}" fill="{MM.CAT_COLOR[k]}">'
                       f'<title>{m} {GROUP_NAME[k]}: ${v:,.2f}</title></rect>')
        out.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" text-anchor="middle" class="ag-small">{e(m[5:])}/{e(m[2:4])}'
                   f'</text>')
    return (f'<figure class="ag-chart"><svg viewBox="0 0 {w} {h}" role="img" aria-label="Spending by month, '
            f'stacked by group">{"".join(out)}</svg><figcaption class="fine">Each bar is one month. Colors match '
            'the groups on the left. Hover a block for the amount.</figcaption></figure>')


# ---------------------------------------------------------------- the section
def _issue_card(app, it, act_form, hidden) -> str:
    st = it["status"]
    steps = "".join(f'<li>{e(s[0])} &middot; record #{e(s[1])}</li>' for s in it["steps"])
    body = [f'<li class="ag-issue lv-{e(st)}" id="issue-{e(it["id"])}"><div class="what"><span class="tag '
            f'{ {"red": "red", "yellow": "held", "fixed": "safe", "ignored": "gray"}.get(st, "gray") }">'
            f'{e(LABEL.get(st, st))}</span> <b>{e(it["text"])}</b>'
            f'<span class="fine">Raised by the {AG.NAME} &middot; record #{e(it["seq"])}</span>'
            + (f'<ul class="fine">{steps}</ul>' if steps else "") + '</div>']
    if st == "red":
        body.append(act_form(app, f"ag:seen:{it['id']}", "I've seen this", "shield", "btn",
                             aria="I've seen this. The light steps down to yellow."))
        body.append('<p class="fine">Seeing it steps red down to yellow (paused). Red never goes straight to '
                    'green.</p>')
    elif st == "yellow":
        sure_id = f"sure-{it['id']}"
        body.append('<div class="row">' + act_form(app, f"ag:fixed:{it['id']}", "It's fixed, confirm", "approve",
                                                   "btn", aria="It's fixed. Confirm and turn this issue off.")
                    + "</div>")
        n = app.issue_nonce("-", "-", f"ag:ignore:{it['id']}")
        body.append(f'<form method="post" action="/act" class="ag-ignore">{hidden("token", n)}'
                    f'<p class="msg warn" role="note">{e(AG.RECOMMEND)}</p>'
                    f'<label class="sure"><input type="checkbox" name="sure" value="yes" data-sure="btn-{sure_id}" '
                    f'id="{sure_id}"> {e(AG.SURE_TEXT)}</label>'
                    f'<button class="btn btn-quiet" type="submit" id="btn-{sure_id}" disabled>Ignore</button></form>')
    return "".join(body) + "</li>"


def chat_box(app, lane: str, act_form_nonce, hidden) -> str:
    gate = app.gate
    rep = money_report(app) if lane == H.HISTORY else None
    st = app.__dict__.setdefault("help_chat_state", {}).setdefault(lane, {"step": 0})
    msgs = app.__dict__.setdefault("help_chat_msgs", {}).setdefault(lane, [])
    g = H.guide(gate, lane, rep)
    n = min(st.get("step", 0), len(g["steps"]))
    steps = "".join(f'<li{" class=now" if i == n else ""}>{e(s)}</li>' for i, s in enumerate(g["steps"]))
    log = []
    for m in msgs[-CHAT_KEEP:]:
        who = (f'<span class="tag ai">AI</span>' if m["by_ai"] else '<span class="tag gray">Local rules</span>')
        log.append(f'<li class="me"><b>You:</b> {e(m["q"], 300)}</li><li class="bot">{who} {e(m["a"], 700)}'
                   + (f'<p class="msg warn">{e(m["warn"], 300)}</p>' if m.get("warn") else "")
                   + f'<p class="fine use">{e(m["usage"], 300)}</p></li>')
    tok = act_form_nonce(f"chat:{lane}")
    other = ("Questions about your past spending or subscriptions? Use the BW AG Grid agent chat on History."
             if lane == H.NOW else "Questions about a payment waiting right now, or a call? Use the BW help chat on "
             "Home.")
    return (f'<section class="ag-chat" aria-labelledby="chat-{lane}"><h3 id="chat-{lane}">{e(H.TITLE[lane])}</h3>'
            f'<p class="fine">Only for {e(H.LANE_WHAT[lane])}. {e(other)} It can explain and walk you through a fix. '
            'It cannot press any button, ignore anything, turn the light green, or move money.</p>'
            f'<div class="ag-guide"><b>{e(g["title"])}</b><ol>{steps}</ol></div>'
            f'<ul class="ag-log" id="answer-{lane}">{"".join(log)}</ul>'
            f'<form method="post" action="/act">{hidden("token", tok)}<label for="q-{lane}">Ask, or type '
            f'\u201cnext\u201d for the next step</label><input id="q-{lane}" name="q" maxlength="300" '
            'autocomplete="off" placeholder="next"><div class="row"><button class="btn btn-ai" type="submit">Ask'
            '</button></div></form><p class="fine">Steps and \u201cnext\u201d are free (no AI). ' + _ai_cost_words() +
            '</p>'
            '</section>')


def _ai_cost_words() -> str:
    """JUDGEFIX 2026-11-01: who pays for a chat question. A hosted judge uses our key (free, counted); the owner
    uses their own key. Never 'billed to you' for a judge."""
    key, counter = JA.current()
    if key and counter is not None:
        return (f"A question uses real xAI on our key, free to you. You have {counter.left(key)} of "
                f"{counter.limit} judge AI messages left. Under each answer we show what xAI says it used.")
    return ("A question uses your own xAI key, so it is billed to you. Answers are kept short to keep it cheap. "
            "Under each answer we show what xAI says it used. xAI does not report your remaining credit, so we say "
            "so instead of guessing.")


def _studio_cost_words() -> str:
    key, counter = JA.current()
    if key and counter is not None:
        return (f"Each answer uses real xAI on our key, free to you ({counter.left(key)} of {counter.limit} "
                "judge AI messages left). Under each answer is what xAI says it used.")
    return ("Each answer uses your own xAI key through this server; under each answer is what xAI says it used. "
            "Remaining credit: " + H.NO_LIMIT + ".")


def section(app, nonce, act_form, hidden, studio: bool = False) -> str:
    gate = app.gate
    rep = money_report(app)
    recs = gate.audit.records()
    issues = AG.issues(recs)
    open_i = [i for i in issues if i["status"] in ("red", "yellow")]
    done_i = [i for i in issues if i["status"] in ("fixed", "ignored")][-5:]
    found = AG.scan(recs, gate.audit.verify(), rep, gate.clock())
    t = rep["totals"]
    kpi = "".join(f'<div class="kpi"><svg class="sw" viewBox="0 0 12 12" aria-hidden="true"><rect width="12" '
                  f'height="12" rx="3" fill="{MM.CAT_COLOR[k]}"/></svg><span>{GROUP_NAME[k]}</span>'
                  f'<b>${t.get(k, 0):,.2f}</b></div>' for k in MM.CATEGORIES)
    kpi += (f'<div class="kpi"><span>Refunds back</span><b>${rep["refunds"]:,.2f}</b></div>'
            f'<div class="kpi"><span>Failed payments</span><b>{rep["failed"]}</b></div>')
    flags = "".join(f'<li><span class="tag {"held" if f["level"] == "yellow" else "red" if f["level"] == "red" else "gray"}">'
                    f'{e({"red": "Serious", "yellow": "Look", "info": "Note"}[f["level"]])}</span> {e(f["text"])} '
                    f'<span class="fine">({e({"money": "money", "actions": "Bridge Warden actions", "history": "history", "light": "light", "alerts": "alerts", "ai": "xAI check"}.get(f["area"], f["area"]))})</span></li>'
                    for f in found[:20]) or "<li>Nothing found. All checks passed.</li>"
    out = [f'<h2 id="ag-h">{AG.NAME}</h2>',
           f'<p>The {AG.NAME} reads your History. It sorts your spending into bills, subscriptions, gas, food and '
           'other, finds subscriptions you pay twice or may not use, and spots money spikes. It also audits Bridge '
           'Warden itself, and checks what xAI said against the real rules and data. It may raise the light to '
           'yellow or red. Only you can step it down.</p>']
    if rep.get("sample"):
        out.append('<p class="msg warn sample-note" role="note"><b>SAMPLE</b> These are made-up example payments for '
                   'the demo, not your money.</p>')
    out.append(f'<div class="ag-kpis">{kpi}</div><div class="ag-charts">{donut(t)}{month_bars(rep["by_month"])}</div>')
    out.append(f'<div id="bw-money-grid" class="bw-grid" data-nonce="{e(nonce or "")}" role="region" '
               'aria-label="Spending, sortable grid" hidden></div>')
    if studio:
        out.append('<h3>Ask the BW AG Grid agent (AG Studio chat)</h3>'
                   '<p class="fine bw-studio-note">History lane: past and ongoing patterns, spending, subscriptions and '
                   'audit flags. Built with AG Studio by AG Grid (commercial; see NOTICE). It reads redacted data only '
                   '(groups, months, amounts). Its tools are read-only: it can point at a button, never press it. '
                   + e(_studio_cost_words()) + ' With no money data it says so, and does not ask xAI.</p>'
                   '<iframe id="bw-studio-frame" class="bw-studio" src="/ag-studio/panel" loading="lazy" '
                   'title="BW AG Grid agent, AG Studio dashboard and chat" '
                   'sandbox="allow-scripts allow-same-origin"></iframe>')
    if open_i:
        out.append('<h3>Needs you</h3><ul class="list ag-issues">' + "".join(_issue_card(app, i, act_form, hidden)
                                                                        for i in open_i) + '</ul>')
    out.append(f'<h3>What it found</h3><ul class="list ag-flags">{flags}</ul>')
    out.append('<div class="row">' + act_form(app, "ag:scan", f"Run the {AG.NAME} now", "shield", "btn",
                                              aria="Run the BW AG Grid agent now. Read-only.") + '</div>'
               '<p class="fine">Read-only: it never sends, approves, cancels or refunds. Running it is free (local '
               'rules). It raises the light only for real findings.</p>')
    if done_i:
        out.append('<details><summary>Done issues</summary><ul class="list">' + "".join(
            f'<li>{e(LABEL[i["status"]])}: {e(i["text"])}</li>' for i in done_i) + '</ul></details>')
    out.append(chat_box(app, H.HISTORY, lambda p: app.issue_nonce("-", "-", p), hidden))
    return "".join(out)


def owner_step(app, gate, purpose: str, form: dict):
    """The owner's own clicks (already nonce + same-origin checked). Returns (message, kind)."""
    _, what, iid = purpose.split(":", 2)
    if what == "seen":
        r = AG.mark_seen(gate, iid)
        return (("Seen. The light steps down to yellow (paused). Fix it, or ignore it, to go green." if r["ok"]
                 else "Nothing changed: " + r["why"] + "."), "ok" if r["ok"] else "warn")
    if what == "fixed":
        r = AG.mark_fixed(gate, iid)
        return (("Confirmed fixed. Logged in History." if r["ok"] else "Nothing changed: " + r["why"] + "."),
                "ok" if r["ok"] else "warn")
    if what == "ignore":
        sure = form.get("sure", [""])[0] == "yes"
        r = AG.mark_ignored(gate, iid, sure)
        return (("Ignored, as you chose. Logged in History." if r["ok"] else
                 "Not ignored: tick \u201cI'm sure\u201d first." if not sure else "Nothing changed: " + r["why"] + "."),
                "ok" if r["ok"] else "warn")
    return ("Unknown button.", "warn")


def chat_turn(app, lane: str, form: dict):
    gate = app.gate
    q = form.get("q", [""])[0]
    st = app.__dict__.setdefault("help_chat_state", {}).setdefault(lane, {"step": 0})
    rep = money_report(app) if lane == H.HISTORY else None
    r = H.ask(gate, lane, q, st, rep, ai=app.chat_ai() if hasattr(app, "chat_ai") else None,
              by="judge (web)" if JA.current()[0] else "owner (web)")
    st["step"] = r.get("step", st.get("step", 0))
    msgs = app.__dict__.setdefault("help_chat_msgs", {}).setdefault(lane, [])
    msgs.append({"q": q or "(show step)", "a": r["answer"], "by_ai": r["by_ai"], "usage": r["usage"],
                 "warn": r.get("warn", "")})
    del msgs[:-CHAT_KEEP]
    return r


STYLE = """
.ag-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 14px;display:flex;
flex-direction:column;gap:2px}.kpi b{font-size:1.25em}.kpi .sw{width:14px;height:14px}
.ag-charts{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}
.ag-chart{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin:0;flex:1 1 300px}
.ag-chart svg{max-width:100%;height:auto;display:block;margin:0 auto}
.ag-big{font-size:22px;font-weight:700;fill:var(--ink)}.ag-small{font-size:11px;fill:var(--soft)}
.ag-legend{list-style:none;padding:0;margin:8px 0 0}.ag-legend li{margin:4px 0}
.ag-chart .ag-legend svg.sw{display:inline-block;width:12px;height:12px;margin:0 6px 0 0;vertical-align:-1px}
.ag-issue{border-left:6px solid var(--line);padding-left:12px}.ag-issue.lv-red{border-left-color:var(--red)}
.ag-issue.lv-yellow{border-left-color:#A87400}
.ag-ignore{margin-top:10px}.sure{display:flex;gap:8px;align-items:center;font-weight:600;margin:8px 0}
.sure input{width:22px;height:22px}
.ag-chat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:8px 18px;margin:16px 0}
.ag-guide ol li.now{font-weight:700}.ag-log{list-style:none;padding:0}.ag-log li{margin:8px 0}
.ag-log .me{text-align:right}.ag-log .use{margin:2px 0 0}
#bw-money-grid,#bw-studio-frame{margin:12px 0}#bw-studio-frame{display:block;width:100%;height:780px;border:1px solid var(--line);border-radius:14px}
.ag-group .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px}
.sw-bills{background:#1D4ED8}.sw-subscriptions{background:#7C3AED}.sw-gas{background:#B45309}.sw-food{background:#047857}.sw-other{background:#475569}
.bw-studio-note{margin:6px 0}
"""


def studio_data(app) -> dict:
    """Data for the AG Studio dashboard and its chat tools. Whatever Studio shows can reach xAI when the owner asks
    the chat, so this is REDACTED like help_chat: groups, months, amounts and flag kinds only. No merchant names,
    no emails, no ids of payments, no issue wording."""
    rep = money_report(app)
    rows = [{"month": ln["at"][:7], "group": GROUP_NAME.get(ln["category"], "Other"),
             "kind": {"paid": "Paid", "refund": "Refund", "failed": "Failed"}.get(ln["kind"], "Other"),
             "amount": round(float(ln["amount"]), 2),
             "flag": ",".join(sorted({f["kind"] for f in ln.get("flags", [])})) or "none"} for ln in rep["lines"]][:500]
    issues = [{"id": i["id"], "status": i["status"], "kind": i["kind"], "area": i["area"]}
              for i in AG.issues(app.gate.audit.records())]
    subs = {}
    for f in rep["flags"]:
        if f["kind"] in ("duplicate", "still_use", "price_up"):
            subs[f["kind"]] = subs.get(f["kind"], 0) + 1
    return {"rows": rows, "summary": MM.redacted(rep), "subscriptions": subs, "issues": issues,
            "sample": bool(rep.get("sample"))}
