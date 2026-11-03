# Made by @Nefarious_Trey,
# with Grok.  Copyright 2026 Trey (@Nefarious_Trey).  Apache-2.0.
"""PREFLIP 2026-11-02 (pre-flip audit, MUST-FIX 1): a hosted judge must never cause a real Twilio call,
not even later through the missed-call retry that runs on the background thread with no judge context.
Reproduces the audit's path (judge AG red raise with Dev mode OFF, then a background tick 3 hours later)
and proves no request ever reaches api.twilio.com. Everything is offline: recording sender, fake keys only."""
import json
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from bridge_warden import ag_agent as AG
from bridge_warden import alerts as A
from bridge_warden import hosted as Ho
from bridge_warden import judge_ai as JA
from bridge_warden import net
from bridge_warden import notify as N
from test_v5_alerts import FakeTwilio, block, mk
import test_v5_render_hosted as HT

J1 = "judge-one-" + "b" * 20


@pytest.fixture
def hj(tmp_path, monkeypatch):
    """Hosted copy with a FULL fake Twilio env (also in os.environ, like the live service), Dev mode OFF,
    and every network call recorded instead of sent."""
    keys = tmp_path / "judges.txt"
    keys.write_text(J1 + "\n", encoding="utf-8")
    sent = []

    def rec(method, url, headers=None, body=None, timeout=None, **kw):
        sent.append((method, str(url)))
        return 201, {}, b'{"sid": "CA' + b"1" * 32 + b'"}'
    monkeypatch.setattr(net, "request", rec)
    env = HT.env_for(tmp_path, BW_JUDGE_KEY_FILE=str(keys))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=rec)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    assert not N.dev_locked(app.real_gate)        # the audit's case: Dev mode is OFF
    yield s, app, sent
    s.shutdown()
    s.server_close()


def _twilio(sent):
    return [u for _, u in sent if "twilio.com" in u]


def _later(fn):
    """Run fn on a plain background thread (no judge context), like the bw-notify loop."""
    out = {}
    t = threading.Thread(target=lambda: out.update(r=fn()), name="bw-notify")
    t.start()
    t.join(30)
    return out.get("r")


RED = {"kind": "test", "level": "red", "area": "money", "key": "preflip:red:1", "text": "a red finding"}


def test_audit_path_judge_red_raise_then_background_retry_never_reaches_twilio(hj):
    s, app, sent = hj
    gate = app.real_gate
    with JA.acting_as(J1, app.judge_xai):          # what hosted.py does for one judge request
        out = AG.raise_light(gate, dict(RED))
    assert out and out["level"] == "red"           # the in-app red still stands
    assert _twilio(sent) == []
    q = A.RetryQueue(gate.audit.path.parent).read()
    assert all(e.get("state") != "waiting_retry" for e in q.values())     # no retry was queued
    note = N.Notifier(gate)
    later = datetime.now(timezone.utc).astimezone() + timedelta(hours=3)
    assert _later(lambda: note.alerts().tick(now=later)) == []
    _later(note.check)                             # the loop's own look at new blocks: already alerted, no call
    assert _twilio(sent) == []


def test_tick_refuses_a_flagged_retry_even_if_one_was_queued(gate):
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    r = block(gate)
    for flag in ("judge", "dry_run"):
        aid = r["action_id"] + flag
        al.queue.update(lambda d, a=aid, f=flag: d.update({a: {
            "action_id": a, "state": "waiting_retry", "next_at": now[0].isoformat(), "attempts": 1,
            "first_call_at": now[0].isoformat(), "retry_minutes": [15, 15], f: True}}))
    now[0] += timedelta(minutes=1)
    assert al.tick() == [] and tw.n == 0
    assert {e["done_why"] for e in al.queue.read().values()} == {"dry_run_no_retry"}


def test_judge_acting_fire_never_dials_and_never_queues_a_retry(gate):
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    r = block(gate)
    with JA.acting_as(J1, None):
        al.fire(r["action_id"])
    assert tw.n == 0
    e = al.queue.read()[r["action_id"]]
    assert e["judge"] is True and e["retry_minutes"] == [] and e["state"] == "done"
    now[0] += timedelta(hours=3)
    assert _later(al.tick) == [] and tw.n == 0
    assert any(x["event"] == "alert_retry_skipped" for x in gate.audit.records())


def test_judge_flag_rechecked_at_send_time(gate):
    """Even an unflagged due retry is not dialed when tick itself runs inside a judge request."""
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    r = block(gate)
    al.fire(r["action_id"])                        # owner alert: 1 real (fake) call
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    now[0] += timedelta(hours=1)
    with JA.acting_as(J1, None):
        assert al.tick() == []
    assert tw.n == 1


def test_owner_real_alert_still_retries(gate):
    """The owner's own path is unchanged: a missed real call is retried."""
    tw = FakeTwilio()
    al, now = mk(gate, tw)
    r = block(gate)
    al.fire(r["action_id"])
    al.on_status(call_sid="CA" + f"{1:032x}", status="no-answer")
    assert al.queue.read()[r["action_id"]]["state"] == "waiting_retry"
    now[0] += timedelta(minutes=16)
    assert al.tick() == [r["action_id"]] and tw.n == 2


def test_judge_ag_scan_button_never_reaches_twilio_and_is_labeled_judge(hj):
    s, app, sent = hj
    st, h, _ = HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": J1}),
                      {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST})
    assert st == 303
    ck = h["set-cookie"].split(";")[0]
    st, _, page = HT.req(s, "GET", "/history", headers={"Cookie": ck})
    assert st == 200
    import re
    tok = None
    for m in re.finditer(r'<form method="post" action="/act">(.*?)</form>', page, re.S):
        if "Run the BW AG Grid agent now" in m.group(1):
            tok = re.search(r'name="token" value="([^"]+)"', m.group(1)).group(1)
    assert tok
    st, _, _ = HT.req(s, "POST", "/act", urllib.parse.urlencode({"token": tok}),
                      {"Cookie": ck, "Content-Type": "application/x-www-form-urlencoded",
                       "Origin": "https://" + HT.HOST})
    assert st == 303
    scans = [r for r in app.real_gate.audit.records() if r.get("event") == AG.SCAN]
    assert scans and scans[-1]["by"] == "judge (web)"
    note = N.Notifier(app.real_gate)
    later = datetime.now(timezone.utc).astimezone() + timedelta(hours=3)
    _later(lambda: note.alerts().tick(now=later))
    assert _twilio(sent) == []


# ---- SHOULD-FIX 3: BW_JUDGE_UNTIL ------------------------------------------------------------------------------
def test_judge_until_default_and_cutoff():
    from datetime import date
    assert N.JUDGE_UNTIL_SHIPPED == "2026-12-16"
    env = {"BW_JUDGE_KEY": J1}
    assert N.is_judge(J1, env)                                  # conftest keeps judging open for the suite
    over = {**env, "BW_JUDGE_UNTIL": "2000-01-01"}
    assert N.judge_keys(over) == [] and not N.is_judge(J1, over)
    open_env = {**env, "BW_JUDGE_UNTIL": "2099-01-01"}
    assert N.is_judge(J1, open_env)
    ship = {**env, "BW_JUDGE_UNTIL": "2026-12-16"}
    assert not N.judging_over(ship, today=date(2026, 12, 15))
    assert N.judging_over(ship, today=date(2026, 12, 16))
    assert N.judge_until({"BW_JUDGE_UNTIL": "not a date"}) == date.fromisoformat(N.JUDGE_UNTIL_DEFAULT)


def test_shipped_default_ends_judging_on_dec_16(monkeypatch):
    from datetime import date
    monkeypatch.setattr(N, "JUDGE_UNTIL_DEFAULT", N.JUDGE_UNTIL_SHIPPED)
    assert not N.judging_over({}, today=date(2026, 11, 2))
    assert N.judging_over({}, today=date(2026, 12, 16))


def test_hosted_judge_login_refused_after_cutoff(tmp_path, monkeypatch):
    keys = tmp_path / "judges.txt"
    keys.write_text(J1 + "\n", encoding="utf-8")
    env = HT.env_for(tmp_path, BW_JUDGE_KEY_FILE=str(keys), BW_JUDGE_UNTIL="2000-01-01")
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        st, h, _ = HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": J1}),
                          {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST})
        assert st == 401 and "set-cookie" not in h              # the judge key no longer logs in
    finally:
        s.shutdown()
        s.server_close()


# ---- SHOULD-FIX / NICE ------------------------------------------------------------------------------------------
from pathlib import Path   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_no_em_dashes_anywhere_in_the_repo_text():
    bad = []
    for f in ROOT.rglob("*"):
        if ".git" in f.parts or "__pycache__" in f.parts or not f.is_file():
            continue
        if f.suffix.lower() not in (".py", ".md", ".yaml", ".yml", ".txt", ".html", ".js", ".css", ".json", ".toml"):
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        if f.name == Path(__file__).name or f.name == "test_deploy_button_20261102.py":
            continue
        if "\u2014" in t or "&mdash;" in t or "\\u2014" in t:
            bad.append(str(f.relative_to(ROOT)))
    assert bad == []


def test_wording_fixes():
    from bridge_warden import money_check, web
    assert "Trey decides" not in Path(money_check.__file__).read_text(encoding="utf-8")
    assert "The app owner decides; Bridge Warden did not add it." in Path(money_check.__file__).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "bw_demo_v9_20261028.mp4" in readme and "bw_demo_v8" not in readme
    guide = (ROOT / "JUDGE_TESTING.md").read_text(encoding="utf-8")
    for t in (guide, web.judges_body()):
        assert "per judge in all" not in t and "shared by every judge" in t
        assert "Another judge may change or clear them" in t
    assert "18 and over" in readme and "18 and over" in guide
    assert "3 real test calls" not in (ROOT / "bridge_warden" / "judge_ai.py").read_text(encoding="utf-8")
    for y in ("render.yaml", "render-judge.yaml"):
        assert "    region: oregon" in (ROOT / y).read_text(encoding="utf-8")


def test_get_paypal_webhook_is_405(hj):
    s, app, sent = hj
    st, h, body = HT.req(s, "GET", "/paypal-webhook")
    assert st == 405 and h.get("allow") == "POST" and "POST" in body


def test_judges_page_shows_adults_line_and_key_stop(tmp_path):
    """PREFLIP 2026-11-02: the live Judge Guide says the judge key stops on Dec 16 and that BW is for adults."""
    from bridge_warden import web as W, notify as N
    assert N.JUDGE_UNTIL_SHIPPED == "2026-12-16" and "Dec 16, 2026" in W.JUDGE_KEY_STOP
    body = W.judges_page()
    assert "The judge key stops working on Dec 16, 2026." in body
    assert "Bridge Warden is for adults (18 and over). PayPal accounts also require 18+." in body
