"""The gate: the only path from an agent's proposal to a real PayPal call.

    agent proposes -> RiskEngine verdict -> (optional xAI review, stricter only)
        allow: run | hold: wait for owner | block: never run
        owner yes (bound to the exact action hash) -> re-check -> run
        owner no -> dropped
Every step is written to the audit log.

Hardening (see THREAT_MODEL.md):
  * One lock around propose/decide, plus a file lock in the audit log: no double execution.
  * Action ids are unique. Re-sending the same proposal returns the first answer (idempotent);
    re-using an id for DIFFERENT content is refused, so an approved action can't be swapped.
  * An approval names the action's SHA-256. If the action changed, the approval does nothing.
  * Held actions expire (policy hold_expires_hours, default 24).
  * 'executing' is logged BEFORE PayPal is called. A crash or timeout never triggers a retry
    or a second payment later; an unknown outcome counts toward limits until known.
  * Startup verifies the audit log (fail closed) and records the policy's fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
from datetime import datetime, timedelta, timezone

from . import controls, price_check
from .devmode import DevMode, is_test_id
from .ai import llm_explain
from .audit import AuditLog
from .guard import BadMoney, CURRENCY, canonical_amount, scrub
from .models import ALLOW, BLOCK, HOLD, Finding, ProposedAction, worst
from .rules import RiskEngine
from .textnorm import display_safe
from .xai_check import ai_severity, build_payload, merge_stricter, payload_leaks


def proposal_hash(p: dict) -> str:
    """SHA-256 over exactly what will be executed. The owner's yes is bound to this."""
    keys = ("action_id", "action", "amount", "currency", "payee", "description", "capture_id", "agent_id")
    return hashlib.sha256(json.dumps({k: p.get(k) for k in keys}, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Gate:
    def __init__(self, engine: RiskEngine, audit: AuditLog, paypal=None, clock=None, ai=None,
                 policy_info: dict | None = None, verify_on_start: bool = True):
        self.engine, self.audit, self.paypal, self.ai = engine, audit, paypal, ai
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self.hold_all = None   # v4 fraud drill: callable -> reason while every money action must wait
        self.prices = price_check.from_env()   # v4 price sanity: None unless the owner set CHANNEL3_API_KEY
        # Dev mode (test only): saved next to the audit log, so every process using this log obeys it.
        self.dev = DevMode(getattr(getattr(audit, "path", None), "parent", None))
        if verify_on_start:
            audit.require_intact()  # fail closed: history (caps, duplicates) is only trusted if intact
        self.policy_info = policy_info
        if policy_info:
            self._record_policy(policy_info)

    def _record_policy(self, info: dict):
        last = next((r for r in reversed(self.audit.records()) if r["event"] == "policy_loaded"), None)
        now_ctl = controls.snapshot(self.engine.p)
        if last and last.get("sha256") != info["sha256"]:
            old_ctl = last.get("controls") or {}
            ctl_changes = {k: {"from": old_ctl.get(k), "to": now_ctl[k]} for k in now_ctl
                           if old_ctl.get(k) != json.loads(json.dumps(now_ctl[k]))}
            self.audit.write("policy_changed", action_id="-", old_sha256=last.get("sha256"), new_sha256=info["sha256"],
                             path=info.get("path"), control_changes=ctl_changes or None)
            self.policy_changed_since_last_run = True
        else:
            self.policy_changed_since_last_run = False
        self.audit.write("policy_loaded", action_id="-", sha256=info["sha256"], path=info.get("path"), controls=now_ctl)

    def live_pause(self) -> str | None:
        """Pausing works at once, even while running: if the policy on disk now says "paused" (or is broken),
        stop moving money. Loosening changes (turning checks off, resuming) apply on the next start only."""
        if controls.mode(self.engine.p) == "paused":
            return "Bridge Warden is paused by you."
        if not self.policy_info or not self.policy_drift():
            return None
        from .policy import PolicyError, load
        try:
            disk = load(self.policy_info["path"])[0]
        except (PolicyError, OSError):
            return "The policy file was changed and is now broken, so nothing moves until it is fixed."
        if controls.mode(disk) == "paused":
            return "Bridge Warden was paused by you, so no money moves until you resume."
        return None

    def policy_drift(self) -> str | None:
        """If the policy file changed on disk while running, log it once. The loaded policy stays in force
        until restart (the owner saw it at startup); the change is visible in the log and on the page."""
        if not self.policy_info:
            return None
        from .policy import fingerprint
        try:
            now = fingerprint(self.policy_info["path"])
        except OSError:
            now = "missing"
        if now != self.policy_info["sha256"]:
            if self.policy_info.get("drift_logged") != now:
                self.audit.write("policy_changed_on_disk", action_id="-", loaded_sha256=self.policy_info["sha256"],
                                 disk_sha256=now)
                self.policy_info["drift_logged"] = now
            return now
        return None

    # ------------------------------------------------------------------
    def _payee_status(self, a: ProposedAction) -> str:
        p = (a.payee or "").strip().lower()
        if not p:
            return "none"
        if p in {x.lower() for x in self.engine.p.get("blocked_payees", [])}:
            return "blocked"
        return "known" if p in {x.lower() for x in self.engine.p.get("known_payees", [])} else "new"

    def dev_lock(self) -> str | None:
        """Reason while Dev mode is on (nothing may reach a real account), else None."""
        return self.dev.lock_reason()

    def _ai_step(self, a: ProposedAction, v) -> None:
        """xAI second opinion. Only ever makes the verdict stricter. Logs exactly what was sent."""
        if self.ai is None or is_test_id(a.action_id):   # Dev mode test moves never use (or pay for) the AI
            return
        if controls.mode(self.engine.p) == "off":
            self.audit.write("ai_check", action_id=a.action_id, sent=False, skipped="checks_off_by_owner")
            return
        if v.verdict == BLOCK and not self.ai.cfg.get("review_local_blocks", False):
            self.audit.write("ai_check", action_id=a.action_id, sent=False, skipped="already_blocked_locally")
            return
        payload = build_payload(a, v, extra_terms=self.engine.p.get("private_terms", []),
                                vocab=getattr(self.engine.model, "vocab", None) and
                                {w for w in self.engine.model.vocab if "_" not in w},
                                payee_status=self._payee_status(a))
        leaks = payload_leaks(payload, a)
        if leaks:  # belt and braces: never send if anything private survived redaction
            res = {"called": False, "skipped": "redaction_check_failed", "leaks": leaks}
        else:
            res = self.ai.review(payload)
        before = v.verdict
        if res.get("parsed"):
            sev = ai_severity(res["parsed"])
            reason = f"xAI review ({res['parsed']['risk']} risk): {res['parsed']['reason']}"
            v.findings.append(Finding("xai_review", sev if sev != ALLOW else ALLOW, reason, 20 if sev != ALLOW else 0))
            v.verdict = merge_stricter(v.verdict, sev)
        else:
            mode = self.ai.cfg.get("on_ai_failure", "use_local")
            why = res.get("skipped") or res.get("error") or "no answer"
            if mode == "hold" and v.verdict == ALLOW:
                v.findings.append(Finding("xai_unavailable", HOLD, f"The xAI check did not answer ({why}), so this waits for you.", 10))
                v.verdict = worst(v.verdict, HOLD)
            else:
                v.findings.append(Finding("xai_unavailable", ALLOW, f"xAI check not used ({why}); local rules and scam model decided.", 0))
        self.audit.write("ai_check", action_id=a.action_id, sent=bool(res.get("called")),
                         redacted_payload=None if leaks else payload, result=res,
                         verdict_before=before, verdict_after=v.verdict)

    def _price_step(self, a: ProposedAction, v) -> None:
        """Soft price-sanity check. Only ever adds a HOLD. Logs the redacted words sent, never the key."""
        if self.prices is None or v.verdict == BLOCK or controls.mode(self.engine.p) != "on":
            return
        if not controls.is_on(self.engine.p, "price_sanity") or a.action not in ("payout", "create_order"):
            return
        q = price_check.product_query(a.description, a.payee, self.engine.p.get("private_terms", []))
        if not q:
            return
        try:
            prices = self.prices.market_prices(q, a.currency)
            f = price_check.judge(a.amount, a.currency, prices)
            res = {"called": True, "offers": len(prices),
                   "typical": round(statistics.median(prices), 2) if prices else None}
        except Exception as ex:   # a failed lookup never blocks or loosens anything
            f, res = None, {"called": True, "error": str(ex)[:160]}
        if f is not None:
            v.findings.append(f)
            v.verdict = worst(v.verdict, HOLD)
        self.audit.write("price_check", action_id=a.action_id, source=getattr(self.prices, "name", "custom"),
                         sent_words=q, result=res, flagged=f is not None)

    # ------------------------------------------------------------------
    def _first_proposal(self, action_id: str):
        return next((r for r in self.audit.records() if r["event"] == "proposed" and r["action_id"] == action_id), None)

    def propose(self, a: ProposedAction) -> dict:
        out = self._propose(a)
        if out.get("verdict") != ALLOW:     # REDYELLOW: a hold or block can change the light: log it now
            _log_light(self)
        return out

    def _propose(self, a: ProposedAction) -> dict:
        with self._lock:
            self.policy_drift()
            # Canonical money form (e.g. "20.5" -> "20.50") so what is shown, hashed and sent are identical.
            if isinstance(a.currency, str) and CURRENCY.match(a.currency or ""):
                try:
                    a.amount = canonical_amount(a.amount, a.currency)
                except BadMoney:
                    pass  # the rules will block it with a reason
            pd = a.to_dict()
            h = proposal_hash(pd)
            prior = self._first_proposal(a.action_id) if isinstance(a.action_id, str) else None
            if prior is not None:
                if prior.get("proposal_hash") == h:   # same request sent again: answer, don't re-run
                    last = next((r for r in reversed(self.audit.records())
                                 if r["action_id"] == a.action_id and r["event"] == "verdict"), None)
                    self.audit.write("duplicate_request", action_id=a.action_id, proposal_hash=h)
                    return {"action_id": a.action_id, "status": "duplicate_request_ignored",
                            "verdict": (last or {}).get("verdict", {}).get("verdict", "unknown"),
                            "risk_score": (last or {}).get("verdict", {}).get("risk_score", 0),
                            "reasons": ["This exact request was already received; it was not run again."],
                            "ai_scam_probability": 0.0, "ai_summary": None}
                self.audit.write("id_reuse_refused", action_id=a.action_id, proposal_hash=h,
                                 original_hash=prior.get("proposal_hash"))
                return {"action_id": a.action_id, "verdict": BLOCK, "status": "blocked", "risk_score": 100,
                        "reasons": ["This action id was already used for a different request. Refused, so an "
                                    "approved or held action can never be swapped for another one."],
                        "ai_scam_probability": 0.0, "ai_summary": None}
            self.audit.write("proposed", action_id=a.action_id, proposal=pd, proposal_hash=h)
            v = self.engine.check(a, self.audit.executed_history(), now=self.clock())
            paused = self.live_pause()
            if paused and v.verdict != BLOCK:
                v.findings.append(Finding("paused", BLOCK, paused, 100))
                v.verdict = BLOCK
            self._price_step(a, v)
            self._ai_step(a, v)
            drill = self.hold_all() if callable(self.hold_all) else None
            if drill and v.verdict != BLOCK:   # a drill only tightens: everything waits, blocked stays blocked
                v.findings.append(Finding("fraud_drill", HOLD, drill, 0))
                v.verdict = HOLD
            check = _state_hold(self)
            if check and v.verdict == ALLOW:   # a state check needs you: nothing runs by itself, blocked stays blocked
                v.findings.append(Finding("state_check", HOLD, check, 0))
                v.verdict = HOLD
            ag = _ag_hold(self)
            if ag and v.verdict == ALLOW:      # v6: a BW AG Grid agent issue is open: nothing new runs by itself
                v.findings.append(Finding("ag_agent", HOLD, ag, 0))
                v.verdict = HOLD
            fix = _fix_hold(self)
            if fix and v.verdict == ALLOW:     # REDYELLOW: yellow while you fix a seen red: nothing new runs by itself
                v.findings.append(Finding("fix_pause", HOLD, fix, 0))
                v.verdict = HOLD
            dev = self.dev_lock() or ("Dev mode test move: it can never be paid." if is_test_id(a.action_id) else None)
            if dev and v.verdict == ALLOW:     # Dev mode only tightens: nothing runs by itself, blocked stays blocked
                v.findings.append(Finding("dev_mode", HOLD, dev, 0))
                v.verdict = HOLD
            v.risk_score = min(100, sum(f.points for f in v.findings))
            vd = v.to_dict()
            summary = llm_explain(a.to_dict(), vd)
            if summary:
                vd["ai_summary"] = summary
            self.audit.write("verdict", action_id=a.action_id, verdict=vd, proposal_hash=h,
                             clock_at=self.clock().isoformat())
            out = {"action_id": a.action_id, "verdict": v.verdict, "risk_score": v.risk_score, "reasons": v.reasons,
                   "ai_scam_probability": vd["ai_scam_probability"], "ai_summary": vd.get("ai_summary"),
                   "proposal_hash": h}
            if v.verdict == ALLOW:
                out["result"] = self._execute(a)
            elif v.verdict == HOLD:
                out["status"] = "waiting_for_owner"
            else:
                out["status"] = "blocked"
            return out

    def _hold_ttl(self) -> timedelta:
        return timedelta(hours=int(self.engine.p.get("hold_expires_hours", 24)))

    def pending(self) -> list:
        """Held actions with no owner decision yet and not expired (derived from the audit log; nothing is deleted)."""
        recs = self.audit.records()
        closed = {r["action_id"] for r in recs if r["event"] in ("owner_decision", "executing", "executed", "expired")}
        props = {}
        for r in recs:
            if r["event"] == "proposed" and r["action_id"] not in props:  # first proposal wins, always
                props[r["action_id"]] = r
        now = self.clock()
        out, seen = [], set()
        for r in recs:
            aid = r["action_id"]
            if r["event"] != "verdict" or aid in closed or aid in seen or aid not in props:
                continue
            seen.add(aid)
            if r["verdict"]["verdict"] != HOLD or r.get("proposal_hash") != props[aid].get("proposal_hash"):
                continue
            try:
                held_at = datetime.fromisoformat(r.get("clock_at") or r["at"])
            except (KeyError, ValueError):
                continue
            if now - held_at > self._hold_ttl():
                continue
            out.append({"proposal": props[aid]["proposal"], "verdict": r["verdict"],
                        "proposal_hash": props[aid]["proposal_hash"], "held_at": r["at"]})
        return out

    def decide(self, action_id: str, approve: bool, by: str = "owner", note: str = "",
               expected_hash: str | None = None) -> dict:
        """The owner's answer. A yes must name the exact action hash the owner was shown.
        REDYELLOW: your answer can fix the problem (yellow -> green): the color change is logged right away."""
        out = self._decide(action_id, approve, by=by, note=note, expected_hash=expected_hash)
        _log_light(self)
        return out

    def _decide(self, action_id: str, approve: bool, by: str = "owner", note: str = "",
                expected_hash: str | None = None) -> dict:
        with self._lock:
            self.policy_drift()
            item = next((p for p in self.pending() if p["proposal"]["action_id"] == action_id), None)
            if item is None:
                return {"action_id": action_id, "status": "not_pending"}
            if approve and (not expected_hash or expected_hash != item["proposal_hash"]):
                self.audit.write("approval_rejected", action_id=action_id, reason="action_hash_mismatch",
                                 shown_hash=expected_hash, actual_hash=item["proposal_hash"], decided_by=by)
                return {"action_id": action_id, "status": "action_changed_not_approved"}
            paused = self.live_pause() if approve else None
            if approve and not paused and callable(self.hold_all):
                paused = self.hold_all()
            if approve and (self.dev_lock() or is_test_id(action_id)):   # Dev mode / test move: never paid
                self.audit.write("approval_rejected", action_id=action_id, reason="dev_mode", decided_by=by)
                return {"action_id": action_id, "status": "dev_mode_not_paid",
                        "reasons": [self.dev_lock() or "Dev mode test move: it can never be paid."]}
            if paused:   # checked before the decision is recorded, so the item stays waiting for after resume
                self.audit.write("approval_rejected", action_id=action_id, reason="paused", decided_by=by)
                return {"action_id": action_id, "status": "paused_not_paid", "reasons": [paused]}
            self.audit.write("owner_decision", action_id=action_id, decision="yes" if approve else "no",
                             decided_by=by, note=display_safe(note, 200), proposal_hash=item["proposal_hash"])
            if not approve:
                return {"action_id": action_id, "status": "denied_by_owner"}
            a = ProposedAction.from_dict(item["proposal"])
            # Re-check at approval time: things may have changed (e.g. a duplicate went through meanwhile).
            v = self.engine.check(a, self.audit.executed_history(), now=self.clock())
            if v.verdict == BLOCK:
                self.audit.write("recheck_blocked", action_id=action_id, verdict=v.to_dict())
                return {"action_id": action_id, "status": "blocked_on_recheck", "reasons": v.reasons}
            return {"action_id": action_id, "status": "approved", "result": self._execute(a)}

    # ------------------------------------------------------------------
    def _execute(self, a: ProposedAction) -> dict:
        """Run the action, then re-read PayPal and our log to make sure it landed once and matches."""
        res = self._execute_once(a)
        try:
            from .callaudit import run as state_check
            state_check(self, "after_action", aid=a.action_id)
        except Exception:
            pass
        return res

    def _execute_once(self, a: ProposedAction) -> dict:
        pd = a.to_dict()
        # Intent first. If we crash after this line, nothing re-runs it later, and limits count it.
        self.audit.write("executing", action_id=a.action_id, proposal=pd, proposal_hash=proposal_hash(pd),
                         clock_at=self.clock().isoformat())
        dev = self.dev_lock() or ("Dev mode test move." if is_test_id(a.action_id) else None)
        if self.paypal is None or dev:   # last lock: in Dev mode PayPal is never called, whatever path got here
            res = {"dry_run": True, "note": "No PayPal client attached; nothing was sent."}
            if dev:
                res.update(dev_mode=True, note="Dev mode: test only. PayPal was not called; nothing was sent.")
            if a.action == "create_order":
                res["capture_id"] = "DRYRUN-CAP-" + a.action_id
            self.audit.write("executed", action_id=a.action_id, proposal=pd, result=res)
            return res
        try:
            if a.action == "create_order":
                res = self.paypal.create_and_capture_order(a.amount, a.currency, a.description, a.action_id)
            elif a.action == "payout":
                res = self.paypal.payout(a.amount, a.currency, a.payee, a.description, a.action_id)
            elif a.action == "refund":
                res = self.paypal.refund(a.capture_id, a.amount, a.currency, a.action_id)
            else:  # the engine blocks unknown actions; this is a second lock
                raise ValueError("unknown action")
        except Exception as e:  # log and surface, never retry silently
            status = getattr(e, "status", None)
            outcome = "rejected" if isinstance(status, int) and 400 <= status < 500 and status != 429 else "unknown"
            err = scrub(f"{type(e).__name__}: {e}")[:300]
            self.audit.write("failed", action_id=a.action_id, proposal=pd, error=err, outcome=outcome)
            return {"error": err, "outcome": outcome}
        self.audit.write("executed", action_id=a.action_id, proposal=pd, result=res)
        return res


def _state_hold(gate):
    """Open state-check problem -> the hold reason (automatic actions wait), else None."""
    try:
        from .callaudit import hold_reason
        return hold_reason(gate)
    except Exception:
        return None


def _ag_hold(gate):
    """v6: an open BW AG Grid agent issue (yellow or red) -> automatic actions wait. Else None."""
    try:
        from .ag_agent import hold_reason
        return hold_reason(gate)
    except Exception:
        return None


def _fix_hold(gate):
    """REDYELLOW (Trey): you saw a red but a held payment is still open, so the light is yellow and Bridge
    Warden is paused for the fix: new requests wait for you instead of running, so nothing piles up. Else None."""
    try:
        from .dashboard import fix_pause_reason
        return fix_pause_reason(gate)
    except Exception:
        return None


def _log_light(gate):
    """REDYELLOW: write the light_changed History line if the color changed. Never raises."""
    try:
        from .dashboard import status
        status(gate)
    except Exception:
        pass
