"""Command line for Bridge Warden.

  python -m bridge_warden ping                 # sandbox OAuth check
  python -m bridge_warden demo [--live]        # run the demo agent; asks you yes/no on holds
  python -m bridge_warden propose --action payout --amount 20.00 --payee a@b.com --desc "..."
  python -m bridge_warden propose --json action.json   # how a real agent hands in a proposal
  python -m bridge_warden review [--live]      # answer held actions in the terminal
  python -m bridge_warden serve [--live]       # answer held actions on http://127.0.0.1:8765
  python -m bridge_warden judge [--public]     # practice demo for judges (no keys, nothing real)
  python -m bridge_warden hosted               # YOUR own copy on Render (render.yaml, Deploy to Render)
  python -m bridge_warden audit [--verify]
  python -m bridge_warden selfcheck            # static security self-check of this code
  python -m bridge_warden forget-calls [--dry-run]   # delete your Twilio call logs (your own account)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import demo_script
from .lawful import NOTE as LAWFUL_NOTE, AI_NOTE_SHORT
from .audit import AuditLog
from .gate import Gate
from .audit import AuditTampered
from .models import ProposedAction
from .policy import PolicyError, load as load_policy_full
from .rules import RiskEngine
from .textnorm import ascii_view, display_safe, is_plain_ascii

MAX_JSON_INPUT = 64 * 1024

ICON = {"allow": "ALLOW", "hold": "HOLD ", "block": "BLOCK"}


def _client_id() -> str:
    cid = os.environ.get("PAYPAL_CLIENT_ID", "")
    if not cid:
        sys.exit("Set PAYPAL_CLIENT_ID (your PayPal sandbox app's client ID) first.")
    return cid


def build_gate(args) -> Gate:
    """Fail closed: a missing/malformed policy or a broken audit log stops everything before any money moves."""
    try:
        policy, sha, path = load_policy_full(args.policy)
    except PolicyError as e:
        sys.exit(f"Refusing to start: {e}")
    paypal = None
    if getattr(args, "live", False):
        from .paypal_client import PayPalSandbox
        paypal = PayPalSandbox(client_id=_client_id())
    ai = None
    if not getattr(args, "no_xai", False) and policy.get("xai", {}).get("enabled", False):
        from .xai_check import XaiChecker
        ai = XaiChecker(policy.get("xai"))
    try:
        return Gate(RiskEngine(policy), AuditLog(args.audit), paypal, ai=ai,
                    policy_info={"sha256": sha, "path": path})
    except AuditTampered as e:
        sys.exit(f"Refusing to start: {e}. Keep the file for investigation and start a new log with --audit.")


def _who(a: dict) -> str:
    p = a.get("payee") or a.get("capture_id") or "-"
    return display_safe(p, 300) if is_plain_ascii(p) else ascii_view(p) + "  (unusual characters!)"


def show(out: dict):
    print(f"\n[{ICON.get(out['verdict'], out['verdict'])}] {out['action_id']}  risk {out['risk_score']}/100  "
          f"AI scam {out['ai_scam_probability']:.0%}")
    for r in out["reasons"]:
        print("   -", display_safe(r, 500))
    if out.get("ai_summary"):
        print("   AI:", display_safe(out["ai_summary"], 300))
    if "result" in out:
        print("   PayPal:", json.dumps(out["result"]))


def ask_owner(gate: Gate, item: dict, answer: str | None = None) -> dict:
    a, v = item["proposal"], item["verdict"]
    print("\n  ┌─ Your agent wants a yes ─────────────────────────")
    print(f"  │ {display_safe(a['action'])}  {display_safe(a['amount'])} {display_safe(a['currency'])}  ->  {_who(a)}")
    print(f"  │ Agent says: \"{display_safe(a.get('description', ''), 1000)}\"")
    for r in v["reasons"]:
        print(f"  │ • {display_safe(r, 500)}")
    print(f"  │ fingerprint {item['proposal_hash'][:12]}")
    print("  └──────────────────────────────────────────────────")
    if answer is None:
        try:
            answer = input("  Approve? type yes or no: ").strip().lower()
        except EOFError:
            answer = "no"  # no answer means no (fail closed)
            print("no (no answer)")
    else:
        print(f"  Approve? type yes or no: {answer}")
    # The yes is bound to the exact action shown (its hash); if it changed meanwhile, nothing runs.
    res = gate.decide(a["action_id"], approve=answer in ("y", "yes"), by="owner (cli)",
                      expected_hash=item["proposal_hash"])
    print("  ->", res["status"], json.dumps(res.get("result", "")) if res.get("result") else "")
    return res


def cmd_demo(args):
    gate = build_gate(args)
    answers = iter(args.answers.split(",")) if args.answers else None
    ctx = {}
    print(f"Bridge Warden demo ({'LIVE PayPal sandbox' if gate.paypal else 'dry run'})")
    for step in demo_script():
        a = step(ctx)
        print(f"\nAgent proposes: {a.action} {a.amount} {a.currency} to {_who(a.to_dict())} - "
              f"\"{display_safe(a.description, 500)}\"")
        out = gate.propose(a)
        show(out)
        if out["verdict"] == "hold":
            item = next(p for p in gate.pending() if p["proposal"]["action_id"] == a.action_id)
            res = ask_owner(gate, item, next(answers, None) if answers else None)
            out["result"] = res.get("result")
        r = out.get("result") or {}
        if a.action == "create_order" and r.get("capture_id") and "first_capture_id" not in ctx:
            ctx["first_capture_id"] = r["capture_id"]
    if gate.ai is not None:
        print(f"\nxAI check: {gate.ai.skip_reason() or 'active'} ({gate.ai!r})")
    ok, why = gate.audit.verify()
    print(f"\nAudit log: {gate.audit.path}  ({len(gate.audit.records())} lines, chain {why})")


def cmd_propose(args):
    gate = build_gate(args)
    if args.json:
        fh = sys.stdin if args.json == "-" else open(args.json, encoding="utf-8")
        raw = fh.read(MAX_JSON_INPUT + 1)
        if len(raw) > MAX_JSON_INPUT:
            sys.exit("Proposal is too large.")
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            sys.exit("Proposal is not valid JSON.")
        if not isinstance(d, dict):
            sys.exit("Proposal must be a JSON object.")
        d.pop("proposed_at", None)  # the time is ours, not the agent's
        # An agent may pass its own action_id (lets it retry safely); re-using one for different content is refused.
        a = ProposedAction.from_dict(d)
    else:
        a = ProposedAction(args.action, args.amount, args.currency, args.payee or "", args.desc or "",
                           capture_id=args.capture_id)
    out = gate.propose(a)
    print(json.dumps(out, indent=2))


def cmd_review(args):
    if not sys.stdin.isatty():
        sys.exit("review needs a real terminal (a person typing). Agents and scripts can't answer it.")
    gate = build_gate(args)
    items = gate.pending()
    if not items:
        print("Nothing is waiting for you.")
    for it in items:
        ask_owner(gate, it)


def cmd_serve(args):
    from .web import serve
    gate = build_gate(args)
    from .notify import Notifier
    srv, login = serve(gate, port=args.port)
    mins = srv.bw_app.link_minutes
    print(f"Bridge Warden dashboard ({'LIVE sandbox' if gate.paypal else 'dry run'}). Open this link to log in. "
          f"It works once, within {mins} minutes, and is your key for this run, so don't share it:\n  {login}\n"
          "Ctrl+C to stop", flush=True)
    print("Lawful use: " + LAWFUL_NOTE, flush=True)
    print(AI_NOTE_SHORT, flush=True)
    note = Notifier(gate)
    if note.enabled:
        note.start()
        print("Phone push: on (your own server).", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_judge(args):
    """Judge / demo mode: practice data only, refuses to start if owner secrets are set."""
    import os
    from .judge import serve_judge
    port = args.port or int(os.environ.get("PORT", "8765"))
    host = args.public_host or os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    srv, _j = serve_judge(port, public_host=host, bind="0.0.0.0" if args.public else "127.0.0.1")
    where = f"https://{host}" if host else f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"Bridge Warden JUDGE DEMO on practice data (no keys, nothing real). Open {where}/", flush=True)
    print("Lawful use: " + LAWFUL_NOTE, flush=True)
    print(AI_NOTE_SHORT, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_hosted(args):
    """Your own Bridge Warden on Render (render.yaml). Refuses to start without BW_LOGIN_KEY and a public host.
    Never prints the login key or any Twilio value."""
    from .hosted import serve_hosted
    from .notify import Notifier
    port = args.port or int(os.environ.get("PORT", "10000"))
    srv, app = serve_hosted(port)
    print(f"Bridge Warden (your own copy) is running for host {app.hosted['host']} . Log in with your BW_LOGIN_KEY "
          "(Render dashboard > Environment). Call menu served here, no Worker needed.", flush=True)
    print("Lawful use: " + LAWFUL_NOTE, flush=True)
    print(AI_NOTE_SHORT, flush=True)
    note = Notifier(getattr(app, "real_gate", app.gate))   # real alerts always watch the REAL history
    if note.enabled:
        note.start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_audit(args):
    log = AuditLog(args.audit)
    if args.verify:
        ok, why = log.verify()
        print("audit chain:", why)
        sys.exit(0 if ok else 1)
    for r in log.records():
        detail = json.dumps(r.get("verdict", {}).get("verdict") or r.get("decision") or r.get("result")
                            or r.get("error") or "", ensure_ascii=True)
        print(r["at"], display_safe(r["event"], 40), display_safe(r.get("action_id", ""), 80), display_safe(detail, 500))


def cmd_ping(args):
    from .paypal_client import PayPalSandbox
    pp = PayPalSandbox(client_id=_client_id())
    pp.token()
    print("PayPal sandbox OAuth: OK (token received; not shown)")


def cmd_controls(args):
    """Your switches. Turning things on or pausing is instant; turning things off warns and asks you to confirm."""
    from . import controls as C
    from .policy import resolve_path
    try:
        path = resolve_path(args.policy)
        if path.name == "policy.example.json":
            raise PolicyError("copy policy.example.json to policy.json first; the example is never edited")
        log = AuditLog(args.audit)
        log.require_intact()
        what, arg = args.what, args.arg
        if what == "show":
            print("\n".join(display_safe(x, 400) for x in C.status_lines(C.load_file(path))))
            return
        if what == "history":
            for v in C.versions(path):
                print(v.name)
            return
        if what in ("on", "off"):
            if not arg:
                raise PolicyError("name a check, e.g. `controls off new_payee`. Checks: " + ", ".join(C.CHECKS))
            res = C.set_check(path, arg, what == "on", log)
        elif what in ("pause", "resume", "master-off"):
            res = C.set_mode(path, {"pause": "paused", "resume": "on", "master-off": "off"}[what], log)
        elif what in ("trust", "untrust"):
            if not arg:
                raise PolicyError("name a payee email")
            res = C.trust(path, arg, log, category=args.category, remove=what == "untrust")
        elif what == "undo":
            res = C.undo(path, log)
        else:
            raise PolicyError(f"unknown controls command {what}")
    except (PolicyError, AuditTampered) as e:
        sys.exit(f"Not changed: {display_safe(str(e), 500)}")
    msgs = {"changed": "Done. Logged in the audit log; `controls undo` reverses it.",
            "no_change": "Nothing to change.", "nothing_to_undo": "Nothing to undo.",
            "not_confirmed": "Not confirmed, so nothing changed.",
            "refused_no_terminal": "Turning checks off must be confirmed by you in a real terminal. Nothing changed."}
    print(msgs.get(res["status"], res["status"]))
    if res["status"] in ("not_confirmed", "refused_no_terminal"):
        sys.exit(1)
    if res["status"] == "changed":
        print("Pausing takes effect at once; other changes apply the next time Bridge Warden starts.")


def cmd_selfcheck(args):
    from .selfcheck import run
    problems = run()
    for p in problems:
        print("PROBLEM:", p)
    print("selfcheck:", "ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


def cmd_forget_calls(args):
    """RETENTION: delete the Twilio call logs between your Twilio number and your phone. Counts only, no numbers."""
    from .notify import forget_calls
    r = forget_calls(dry_run=args.dry_run)
    if not r["ready"]:
        sys.exit("Twilio is not set up on this computer (the 4 values in SETUP_YOUR_OWN.md), so nothing was done.")
    if args.dry_run:
        print(f"Found {r['found']} finished call log(s). Nothing deleted (dry run).")
    else:
        print(f"Deleted {r['deleted']} call log(s) and {r['recordings_deleted']} recording(s).")
    if r["skipped_live"]:
        print(f"Skipped {r['skipped_live']} call(s) still going. Run it again after they end.")
    if r["errors"]:
        print(f"{r['errors']} step(s) failed. Run it again, or delete them in the Twilio Console call logs.")
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="bridge_warden", description="Bridge Warden: human-yes safety layer for AI agents using PayPal")
    p.add_argument("--policy", default=None, help="policy JSON (default policy.json, else policy.example.json)")
    p.add_argument("--audit", default=str(Path("audit") / "audit.jsonl"))
    p.add_argument("--no-xai", action="store_true", help="skip the xAI second opinion even if configured")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo"); d.add_argument("--live", action="store_true")
    d.add_argument("--answers", help="pre-filled owner answers for held items, e.g. yes,no (for recording)")
    d.set_defaults(fn=cmd_demo)
    pr = sub.add_parser("propose"); pr.add_argument("--live", action="store_true")
    pr.add_argument("--json"); pr.add_argument("--action"); pr.add_argument("--amount"); pr.add_argument("--currency", default="USD")
    pr.add_argument("--payee"); pr.add_argument("--desc"); pr.add_argument("--capture-id")
    pr.set_defaults(fn=cmd_propose)
    rv = sub.add_parser("review"); rv.add_argument("--live", action="store_true"); rv.set_defaults(fn=cmd_review)
    sv = sub.add_parser("serve"); sv.add_argument("--live", action="store_true"); sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(fn=cmd_serve)
    jd = sub.add_parser("judge", help="practice demo for judges: no keys, nothing real")
    jd.add_argument("--port", type=int, default=0)
    jd.add_argument("--public", action="store_true", help="listen on all interfaces (hosted demo only)")
    jd.add_argument("--public-host", default="", help="the demo's public host name (Render sets it for you)")
    jd.set_defaults(fn=cmd_judge)
    ho = sub.add_parser("hosted", help="your own copy on Render (Deploy to Render): needs BW_LOGIN_KEY")
    ho.add_argument("--port", type=int, default=0)
    ho.set_defaults(fn=cmd_hosted)
    au = sub.add_parser("audit"); au.add_argument("--verify", action="store_true"); au.set_defaults(fn=cmd_audit)
    pg = sub.add_parser("ping"); pg.set_defaults(fn=cmd_ping)
    sc = sub.add_parser("selfcheck"); sc.set_defaults(fn=cmd_selfcheck)
    fc = sub.add_parser("forget-calls", help="delete your Twilio call logs (in your own Twilio account)")
    fc.add_argument("--dry-run", action="store_true", help="only count, delete nothing")
    fc.set_defaults(fn=cmd_forget_calls)
    ct = sub.add_parser("controls", help="show or change your switches, trusted payees, pause / resume / undo")
    ct.add_argument("what", choices=["show", "on", "off", "pause", "resume", "master-off", "trust", "untrust",
                                     "undo", "history"])
    ct.add_argument("arg", nargs="?"); ct.add_argument("--category")
    ct.set_defaults(fn=cmd_controls)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
