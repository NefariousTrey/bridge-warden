"""2026-10-26 (night): (a) per-judge keys, (b) Dev/Test mode shows SAMPLE data only, (c) real alerts call at once.
Offline only: fake timers, fake 'real' adapters, dry-run calls, no network. No real key is ever printed.
Made by @Nefarious_Trey,
with Grok.
Copyright 2026 Douglas Gibbons III"""
import inspect
import json
import os
import threading
from pathlib import Path

import pytest

from test_v4_alert_test import drill, recs  # noqa: F401
from test_v4_ui import setup, token  # noqa: F401  (fixture)
from test_v5_judge_cap import FakeReal, real, run
from bridge_warden import dashboard as D
from bridge_warden import notify as N
from bridge_warden import web as W
from bridge_warden.models import ProposedAction

K = ["judge-one-key-not-real-000000001", "judge-two-key-not-real-000000002", "judge-three-key-not-real-00003"]
PRIVATE = Path(__file__).resolve().parents[2] / "private"


def keyfile(tmp_path, lines, name="keys.txt"):
    f = tmp_path / name
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


# ------------------------------------------------------------------ (a) per-judge keys
def test_every_key_in_the_file_is_a_judge(tmp_path):
    f = keyfile(tmp_path, ["# comment line, ignored", "", *K, "too-short", "  " + K[0] + "  "])
    env = {N.JUDGE_KEY_FILE_ENV: str(f)}
    assert N.judge_keys(env) == K                                   # one per line, short/comment/dupes dropped
    assert all(N.is_judge(k, env) for k in K)
    assert not N.is_judge("too-short", env) and not N.is_judge("# comment line, ignored", env)
    assert not N.is_judge(K[0][:-1], env) and not N.is_judge("", env) and not N.is_judge(None, env)
    assert N.judge_key(env) == K[0]                                 # old single-key helper still works


def test_old_single_key_file_and_env_still_valid(tmp_path):
    old = keyfile(tmp_path, ["old-judge-key-not-real-00000000"], "JUDGE_KEY.txt")
    new = keyfile(tmp_path, K, "JUDGE_KEYS.txt")
    assert N.is_judge("old-judge-key-not-real-00000000", {N.JUDGE_KEY_FILE_ENV: str(old)})
    both = {N.JUDGE_KEY_FILE_ENV: os.pathsep.join([str(new), str(old)]), N.JUDGE_KEY_ENV: "env-judge-key-not-real-0000"}
    assert len(N.judge_keys(both)) == 5
    for k in K + ["old-judge-key-not-real-00000000", "env-judge-key-not-real-0000"]:
        assert N.is_judge(k, both)
    assert N.judge_keys({N.JUDGE_KEY_FILE_ENV: str(tmp_path / "missing")}) == []


def test_compare_is_constant_time_over_every_key(tmp_path, monkeypatch):
    env = {N.JUDGE_KEY_FILE_ENV: str(keyfile(tmp_path, K))}
    seen = []
    real_cd = N.hmac.compare_digest
    monkeypatch.setattr(N.hmac, "compare_digest", lambda a, b: seen.append(1) or real_cd(a, b))
    assert N.is_judge(K[0], env)              # match on the FIRST key: still compares against all of them
    assert len(seen) == len(K)
    seen.clear()
    assert not N.is_judge("nobody-has-this-key-0000000000", env)
    assert len(seen) == len(K)


def test_each_key_gets_its_own_three_calls(gate, monkeypatch, tmp_path):
    a = real(monkeypatch)
    env = {N.JUDGE_KEY_FILE_ENV: str(keyfile(tmp_path, K))}
    d, t, now = drill(gate, env=env)
    assert [x["started"] for x in run(d, t, now, K[0], 4)] == [True, True, True, False]
    assert [x["started"] for x in run(d, t, now, K[1], 4)] == [True, True, True, False]   # its own 3
    assert [x["started"] for x in run(d, t, now, K[2], 1)] == [True]
    assert a.rang == 7
    jc = N.JudgeCalls(gate.audit.path.parent)
    assert [jc.used(k) for k in K] == [3, 3, 1]
    blob = str(gate.audit.records()) + (gate.audit.path.parent / N.JUDGE_CAP_FILE).read_text(encoding="utf-8")
    assert not any(k in blob for k in K)                            # never logged, never stored


def test_private_key_file_is_well_formed_without_showing_it():
    f, old = PRIVATE / "JUDGE_KEYS_20261026.txt", PRIVATE / "JUDGE_KEY.txt"
    if not f.exists():
        pytest.skip("private judge keys are not on this computer (by design)")
    keys = N.judge_keys({N.JUDGE_KEY_FILE_ENV: str(f)})
    assert len(keys) == 10 and len(set(keys)) == 10 and all(len(k) >= 16 for k in keys)
    assert os.name == "nt" or oct(f.stat().st_mode)[-3:] == "600"   # Windows: no POSIX modes
    if old.exists():                                                # the first key file stays valid alongside
        both = N.judge_keys({N.JUDGE_KEY_FILE_ENV: os.pathsep.join([str(f), str(old)])})
        assert len(both) == 11


# ------------------------------------------------------------------ (c) real alerts: no delay
class Rec(N.CallAdapter):
    name, real, ready = "twilio", True, True

    def __init__(self):
        self.calls = []

    def place_call(self, text, name=""):
        self.calls.append(threading.current_thread().name)
        return {"dialed": True}


def test_real_alert_calls_at_once_with_no_timer_and_no_test_delay(gate, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a real alert must not wait")
    monkeypatch.setattr(N.threading, "Timer", boom)
    monkeypatch.setattr(N, "test_call_delay", boom)
    monkeypatch.setattr(N, "drill_call_delay", boom)
    note = N.Notifier(gate)
    note.caller = Rec()
    note.check()                                                    # first look: remembers the counts
    r = gate.propose(ProposedAction("payout", "250.00", "USD", "support-desk@personal.example.com",
                                    "URGENT: buy gift cards for the CEO right away, keep this between us"))
    assert r["verdict"] == "block"
    assert note.check() is True
    assert note.caller.calls == [threading.current_thread().name]   # placed right here, in this same step
    assert [x for x in gate.audit.records() if x["event"] == "call_placed"]


def test_random_and_judge_delays_live_only_in_the_test_button():
    src_notifier = inspect.getsource(N.Notifier)
    for word in ("test_call_delay", "drill_call_delay", "JUDGE_TEST_DELAY", "Timer", "sleep", ".rng"):
        assert word not in src_notifier, word
    assert "test_call_delay(" in inspect.getsource(N.FraudDrill.start)
    users = [n for n, o in vars(N).items() if inspect.isclass(o) or inspect.isfunction(o)
             if o.__module__ == N.__name__ and "test_call_delay(" in inspect.getsource(o) and n != "test_call_delay"]
    assert {vars(N)[n] for n in users} == {N.FraudDrill}            # (AlertTest is just its old name)
    assert N.ALERT_POLL_SECONDS <= 3


# ------------------------------------------------------------------ (b) Dev / Test mode: SAMPLE data only
REAL_DESC = "realdata7731@landlord.example.com"   # a real payee (shown on every page that lists moves)


def press(s, label, where="/settings"):
    _, html = s.get(where)
    return s.post("/act", token=token(html, label))


def test_dev_mode_shows_only_sample_data_and_leaves_real_data_alone(setup):
    g = setup.gate
    g.propose(ProposedAction("payout", "20.00", "USD", REAL_DESC, "rent"))
    rep = W.build_sample(g, lambda: 0.0, lambda: "")[2]           # a well-formed report, marked as the "real" one
    rep.update(look=[], ok=["REAL-MONEY-REPORT all fine."])
    setup.app.__dict__["real_money_report"] = rep
    assert "REAL-MONEY-REPORT" in setup.get("/money")[1]
    real_before = g.audit.path.read_bytes()
    pol_before = setup.pf.read_bytes()
    _, hist = setup.get("/history")
    assert REAL_DESC in hist and "sample.example" not in hist and W.SAMPLE_TAG not in hist
    press(setup, "Turn on Dev mode")
    marker = len(g.audit.path.read_bytes())                         # the switch itself is logged in the real history
    for path in ("/", "/history", "/money", "/settings", "/moves.json", "/status.json"):
        r, html = setup.get(path)
        assert r.status == 200, path
        assert REAL_DESC not in html and "REALDATA" not in html, path
    _, hist = setup.get("/history")
    assert "sample-deals@sample.example" in hist and W.SAMPLE_TAG in hist and hist.count(">TEST: ") >= 4 and W.SAMPLE_TAG in setup.get("/settings")[1]
    assert "EXAMPLE prices" in hist                                 # example prices only, never real ones
    rows = json.loads(setup.get("/moves.json")[1])["rows"]
    assert rows and all(x["id"].startswith("devtest-") for x in rows)
    assert {x["result"].split(":")[0] for x in rows} == {"TEST"}
    _, money = setup.get("/money")
    assert W.SAMPLE_MONEY in money and "REAL-MONEY-REPORT" not in money
    assert setup.app.money_report is not rep
    # buttons in Dev mode change only the sample: TEST moves, a money check, a settings change
    press(setup, "Add TEST buy")
    press(setup, "Check my money", "/money")
    assert g.audit.path.read_bytes()[marker:] == b""                # nothing more written to the real history
    assert setup.pf.read_bytes() == pol_before                      # real settings untouched
    assert g.paypal.calls == []
    press(setup, "Turn off Dev mode")
    after = g.audit.path.read_bytes()
    assert after.startswith(real_before)
    added = [json.loads(x)["event"] for x in after[len(real_before):].decode().splitlines()]
    assert added == ["dev_mode_on", "dev_mode_off"]                 # only the switch, never sample rows
    _, hist = setup.get("/history")
    assert REAL_DESC in hist and "sample.example" not in hist and W.SAMPLE_TAG not in hist
    assert setup.app.money_report is rep
    assert "TEST MODE" not in setup.get("/")[1]


def test_sample_light_stays_green_and_real_agent_requests_wait(setup):
    press(setup, "Turn on Dev mode")
    _, js = setup.get("/status.json")
    assert json.loads(js)["state"] == "green"                       # sample blocks never turn the light red
    out = setup.gate.propose(ProposedAction("payout", "20.00", "USD", REAL_DESC, "rent"))
    assert out["verdict"] == "hold" and setup.gate.paypal.calls == []   # real request: held by the Dev lock
    assert REAL_DESC not in setup.get("/")[1]                       # and hidden until Dev mode is off
    press(setup, "Turn off Dev mode")
    assert REAL_DESC in setup.get("/")[1]


def test_test_alert_in_dev_mode_uses_the_sample_and_never_rings(setup, monkeypatch):
    a = FakeReal()
    monkeypatch.setattr(N, "call_adapter", lambda *x, **k: a)
    press(setup, "Turn on Dev mode")
    sample_drill = setup.app.alert_test
    assert sample_drill is not setup.app.__dict__["real_drill"] and sample_drill.gate is setup.app.gate
    assert not [x for x in setup.gate.audit.records() if x["event"].startswith("alert_test")]
    press(setup, "Turn off Dev mode")
    assert setup.app.alert_test is setup.app.__dict__["real_drill"] and a.rang == 0
