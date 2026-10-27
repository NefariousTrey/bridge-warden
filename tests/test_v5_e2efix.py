"""E2EFIX (2026-10-27): fixes found by the sandbox e2e run. Your data stays with you. All mocked: no calls,
no emails, no tunnels, no PayPal."""
import json
import os
import re
import stat
import urllib.parse
from pathlib import Path

import pytest

from conftest import NOON_ET
from test_v5_acctwatch import Verifier, hdr
from test_v5_alerts import FakeSMTP, FakeTwilio, SMTP_ENV
from bridge_warden import acctwatch as W
from bridge_warden import alerts as A
from bridge_warden import callaudit as CA
from bridge_warden import dashboard
from bridge_warden import web
from bridge_warden.audit import AuditLog

ROOT = Path(__file__).resolve().parent.parent
BATCH = "5UXD2E8A7EBQJ"


def payout_events(batch=BATCH, item="ITEM0000000001"):
    """What ONE stranger payout really sends: batch PROCESSING, batch SUCCESS, item SUCCEEDED (+ UNCLAIMED)."""
    bh = {"batch_header": {"payout_batch_id": batch, "batch_status": "PROCESSING",
                           "amount": {"value": "9.00", "currency": "USD"}}}
    it = {"payout_item_id": item, "payout_batch_id": batch,
          "payout_item": {"amount": {"value": "9.00", "currency": "USD"}, "receiver": "stranger@example.com"}}
    return [(f"WH-1{batch}", "PAYMENT.PAYOUTSBATCH.PROCESSING", bh),
            (f"WH-2{batch}", "PAYMENT.PAYOUTSBATCH.SUCCESS", bh),
            (f"WH-3{batch}", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", it),
            (f"WH-4{batch}", "PAYMENT.PAYOUTS-ITEM.UNCLAIMED", it)]


def raw(eid, et, res):
    return json.dumps({"id": eid, "event_type": et, "resource": res}).encode()


def mkwatch(gate, reader=None, tw=None, env=None):
    tw = tw or FakeTwilio()
    al = A.Alerts(gate, caller=tw, email=A.EmailAlerter(env={}), clock=lambda: NOON_ET)
    return W.AccountWatch(gate, verifier=Verifier(), alerts=al, env=env or {}, clock=lambda: NOON_ET,
                          reader=reader), tw


def send_all(w, events, start=1):
    return [w.receive(hdr(tid=f"TX-{start + i:08d}"), raw(*e))[2] for i, e in enumerate(events)]


# ---- 1. one alert per payout batch --------------------------------------------------------------------------
def test_one_payout_many_webhooks_one_red_one_call(gate):
    w, tw = mkwatch(gate)
    outs = send_all(w, payout_events())
    assert all(o["red"] for o in outs)
    assert tw.n == 1                                            # exactly ONE call
    assert [bool(o.get("deduped")) for o in outs] == [False, True, True, True]
    first = outs[0]["action_id"]
    assert all(o["action_id"] == first for o in outs)
    recs = gate.audit.records()
    assert len([r for r in recs if r["event"] == "verdict" and r.get("action_id", "").startswith("pp-")]) == 1
    same = [r for r in recs if r["event"] == "acctwatch_same_alert"]
    assert len(same) == 3 and all(r["for_action"] == first for r in same)
    assert len([r for r in recs if r["event"] == "acctwatch_event"]) == 4      # every event still logged
    assert dashboard.status(gate)["state"] == "red"


def test_dedupe_survives_restart(gate):
    ev = payout_events()
    w1, tw1 = mkwatch(gate)
    send_all(w1, ev[:1])
    w2, tw2 = mkwatch(gate)                                     # a new watcher = a restart
    outs = send_all(w2, ev[1:], start=10)
    assert tw1.n == 1 and tw2.n == 0 and all(o.get("deduped") for o in outs)
    st = json.loads((gate.audit.path.parent / "acctwatch_state.json").read_text())
    assert "batch:" + BATCH in st["alerted"]


def test_two_different_payouts_two_alerts(gate):
    w, tw = mkwatch(gate)
    send_all(w, payout_events()[:1])
    send_all(w, payout_events(batch="7ZZQ2E8A7EBQK")[:1], start=20)
    assert tw.n == 2


def test_dedupe_window_ends(gate):
    w, tw = mkwatch(gate, env={"BW_ACCTWATCH_DEDUPE_SECONDS": "60"})
    send_all(w, payout_events()[:1])
    from datetime import timedelta
    later = NOON_ET + timedelta(minutes=5)
    w.clock = lambda: later
    w._alerts().clock = lambda: later
    out = w.handle(json.loads(raw(*payout_events()[1])), {})
    assert not out.get("deduped") and tw.n == 2


def test_alert_key_shapes():
    assert W.alert_key({"payout_batch_id": "ABCD1234"}) == "batch:ABCD1234"
    assert W.alert_key({"batch_header": {"payout_batch_id": "ABCD1234"}}) == "batch:ABCD1234"
    assert W.alert_key({"id": "PP-D-12345"}) == "res:PP-D-12345"
    assert W.alert_key({}) == ""


# ---- 2. call SID saved ------------------------------------------------------------------------------------------
def test_call_sid_in_result_and_log(gate):
    w, tw = mkwatch(gate)
    out = send_all(w, payout_events()[:1])[0]
    sid = out["alert"]["call"]["call_sid"]
    assert re.fullmatch(r"CA[0-9a-f]{32}", sid)
    line = [r for r in gate.audit.records() if r["event"] == "call_placed"][-1]
    assert line["call_sid"] == sid and line["for_action"] == out["action_id"]
    assert "+1555" not in json.dumps(line)                     # never a phone number


def test_bad_call_sid_not_logged(gate):
    class Odd(FakeTwilio):
        def place_call(self, text, name="", voice=None):
            self.n += 1
            return {"dialed": True, "status": 201, "call_sid": "not-a-sid <script>"}
    w, tw = mkwatch(gate, tw=Odd())
    out = send_all(w, payout_events()[:1])[0]
    assert "call_sid" not in out["alert"]["call"]
    assert "call_sid" not in [r for r in gate.audit.records() if r["event"] == "call_placed"][-1]


# ---- 3. after-call check of the OUTSIDE payout ----------------------------------------------------------------
def test_outside_payout_rechecked_at_paypal(gate):
    asked = []

    def reader(b):
        asked.append(b)
        return {"batch_status": "SUCCESS", "item_status": "UNCLAIMED"}
    w, tw = mkwatch(gate, reader=reader)
    out = send_all(w, payout_events())[0]
    assert asked == [BATCH]                                     # once, for the one alert
    oc = out["alert"]["outside_check"]
    assert oc["rechecked"] and oc["batch_status"] == "SUCCESS"
    line = [r for r in gate.audit.records() if r["event"] == CA.OUTSIDE_EVENT]
    assert len(line) == 1 and line[0]["batch"] == BATCH and line[0]["for_action"] == out["action_id"]
    assert CA.attention(gate) is None                          # never a false yellow
    assert dashboard.status(gate)["state"] == "red"


@pytest.mark.parametrize("reader", [None, "boom"])
def test_outside_payout_could_not_recheck(gate, reader):
    def boom(b):
        raise RuntimeError("paypal down")
    w, tw = mkwatch(gate, reader=boom if reader == "boom" else None)
    out = send_all(w, payout_events()[:1])[0]
    assert out["alert"]["outside_check"]["note"] == "outside payout, could not re-check"
    line = [r for r in gate.audit.records() if r["event"] == CA.OUTSIDE_EVENT][-1]
    assert line["note"] == "outside payout, could not re-check" and line["rechecked"] is False
    assert CA.attention(gate) is None and tw.n == 1


def test_dispute_has_no_outside_payout_check(gate):
    w, tw = mkwatch(gate, reader=lambda b: pytest.fail("no payout to re-read"))
    out = w.receive(hdr(), raw("WH-DISP0000001", "CUSTOMER.DISPUTE.CREATED", {"dispute_id": "PP-D-0001"}))[2]
    assert out["red"] and "outside_check" not in out["alert"]


def test_build_wires_paypal_reader():
    import inspect
    assert "reader=client.payout_status" in inspect.getsource(W.build)


# ---- 4. "Email me my proof" -------------------------------------------------------------------------------------
def mail_app(gate, env=SMTP_ENV, fail=False):
    FakeSMTP.sent = []
    app = web.WebApp(gate)
    app.email_env = dict(env)
    app.email_factory = lambda h, p: FakeSMTP(h, p, fail)
    return app


def test_proof_button_only_when_email_set_up(gate):
    assert "Email me my proof" not in web.history(mail_app(gate, env={}), nonce="n1")
    assert "Email me my proof" in web.history(mail_app(gate), nonce="n1")


def test_email_proof_sends_txt_to_own_address(gate):
    app = mail_app(gate)
    r = app.email_proof()
    assert r["sent"] and not r["dry_run"]
    msg = FakeSMTP.sent[-1]
    assert msg["To"] == SMTP_ENV["BW_ALERT_EMAIL_TO"]
    att = [p for p in msg.iter_attachments()]
    assert len(att) == 1 and att[0].get_filename().startswith("bridge-warden-proof-")
    assert att[0].get_filename().endswith(".txt") and att[0].get_content_type() == "text/plain"
    line = [x for x in gate.audit.records() if x["event"] == "proof_emailed"][-1]
    assert SMTP_ENV["BW_ALERT_EMAIL_TO"] not in json.dumps(line) and "app-pass" not in json.dumps(line)


def test_email_proof_cooldown(gate):
    app = mail_app(gate)
    assert app.email_proof()["sent"]
    assert app.email_proof().get("wait") and len(FakeSMTP.sent) == 1


def test_email_proof_dry_run_in_dev_mode(gate):
    app = mail_app(gate)
    app.dev_view = lambda: True
    r = app.email_proof()
    assert r["dry_run"] and not r["sent"] and FakeSMTP.sent == []
    assert [x for x in app.gate.audit.records() if x["event"] == "would_email_proof"]   # Dev: the sample history
    assert not [x for x in gate.audit.records() if x["event"] == "proof_emailed"]


def test_email_proof_failure_hides_password(gate):
    app = mail_app(gate, fail=True)
    r = app.email_proof()
    assert not r["sent"] and "app-pass-1234" not in json.dumps(r)
    assert "app-pass-1234" not in gate.audit.path.read_text()


def test_email_proof_events_have_plain_words():
    for ev in ("proof_emailed", "would_email_proof", "proof_email_failed", "acctwatch_same_alert",
               CA.OUTSIDE_EVENT):
        assert ev in web.EVENT_WORDS


def test_dry_run_email_accepts_attachments():
    r = A.DryRunEmail().send("s", "b", attachments=[("p.txt", "x")])
    assert not r["sent"] and r["would_attach"] == ["p.txt"]


# ---- 5. free Render banner --------------------------------------------------------------------------------------
def test_free_plan_detection(tmp_path):
    from bridge_warden import hosted as Ho
    assert Ho.free_plan({}, Path("bw-data"))
    assert not Ho.free_plan({}, Path("/var/data"))
    assert Ho.free_plan({"BW_FREE_PLAN": "on"}, Path("/var/data"))
    assert not Ho.free_plan({"BW_FREE_PLAN": "off"}, Path("bw-data"))
    out = Ho.with_free_banner('<main id="main" class="wrap" tabindex="-1">X')
    assert "Download your proof often" in out and out.index("Free Render copy") < out.index("X")


def test_render_yaml_turns_banner_on():
    y = (ROOT / "render.yaml").read_text()
    assert re.search(r'key: BW_FREE_PLAN\s+value: "on"', y)


@pytest.mark.parametrize("plan,shown", [("on", True), ("off", False)])
def test_hosted_pages_show_banner(tmp_path, plan, shown):
    import threading
    import test_v5_render_hosted as T
    env = T.env_for(tmp_path, BW_FREE_PLAN=plan)
    s, app = T.Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        cookie = T.login(s)
        st, _, body = T.req(s, "GET", "/history", headers={"Cookie": cookie})
        assert st == 200 and ("Download your proof often" in body) is shown
        assert app.email_env is env
    finally:
        s.shutdown()
        s.server_close()


# ---- 6. bw-data/ never committed --------------------------------------------------------------------------------
def test_gitignore_has_bw_data():
    assert "bw-data/" in (ROOT / ".gitignore").read_text().split()


# ---- 7. owner-only files ----------------------------------------------------------------------------------------
def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_history_files_are_owner_only(gate):
    w, tw = mkwatch(gate)
    send_all(w, payout_events()[:1])
    d = gate.audit.path.parent
    for n in ("audit.jsonl", "audit.jsonl.head", "audit.jsonl.lock", "acctwatch_state.json",
              "acctwatch_state.json.lock", "acctwatch_latency.jsonl"):
        assert (d / n).exists(), n
        assert mode(d / n) == 0o600, n


def test_old_open_files_are_fixed_and_others_left_alone(tmp_path):
    a = AuditLog(tmp_path / "audit.jsonl")
    a.write("hello", action_id="-")
    for n in ("audit.jsonl", "audit.jsonl.head", "alert_retries.json"):
        p = tmp_path / n
        p.touch()
        os.chmod(p, 0o644)
    other = tmp_path / "notes.txt"
    other.write_text("mine")
    os.chmod(other, 0o644)
    AuditLog(tmp_path / "audit.jsonl")                         # next start fixes them
    assert mode(tmp_path / "audit.jsonl") == 0o600 and mode(tmp_path / "audit.jsonl.head") == 0o600
    assert mode(tmp_path / "alert_retries.json") == 0o600
    assert mode(other) == 0o644                                 # not ours: untouched


def test_retry_queue_is_owner_only(tmp_path):
    q = A.RetryQueue(tmp_path)
    q.update(lambda d: d.setdefault("x", 1))
    assert mode(tmp_path / "alert_retries.json") == 0o600


# ---- 8. docs ----------------------------------------------------------------------------------------------------
def test_setup_doc_says_data_stays_with_you():
    t = (ROOT / "SETUP_YOUR_OWN.md").read_text()
    assert "Your data stays on your computer." in t and "email yourself a copy" in t
    assert "The developer never gets it." in t


def test_runbook_exists():
    p = ROOT / "proof/scripts/RUN_ON_TREYS_PC.md"   # private PC run notes: kept local, not shipped (.gitignore)
    if not p.exists():
        pytest.skip("private PC runbook is not in the ship set")
    t = p.read_text()
    for must in ("cloudflared", "register_sandbox_webhook.py", "stranger_sandbox_payout.py", "Clean up", "never"):
        assert must in t
