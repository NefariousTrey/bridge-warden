"""Judges get at most 3 REAL voice test calls per judge key (server-side, persisted). The 4th is refused politely
and no call is placed. The 20-minute cooldown and the 93-second judge delay stay. The key is never stored or logged.
Non-judges are not capped. Offline only: fake timers, a fake 'real' adapter, no network.
Made by @Nefarious_Trey,
with Grok. Copyright 2026 Trey (@Nefarious_Trey)."""
from test_v4_alert_test import drill, recs  # noqa: F401
from test_v4_ui import setup, token  # noqa: F401  (fixture)
from bridge_warden import notify as N

KEY = "test-judge-key-not-real-0123456789"
KEY2 = "another-judge-key-not-real-98765"


class FakeReal(N.CallAdapter):
    name, real, ready = "twilio", True, True

    def __init__(self):
        self.rang = 0

    def place_call(self, text, name=""):
        self.rang += 1
        return {"dialed": True}


def real(monkeypatch):
    a = FakeReal()
    monkeypatch.setattr(N, "call_adapter", lambda *x, **k: a)
    return a


def run(d, t, now, key, n):
    """n tests, each after the cooldown; fires every scheduled call."""
    out = []
    for _ in range(n):
        now[0] += N.TEST_COOLDOWN + 1
        made = len(t.made)
        r = d.start(judge_key=key)
        out.append(r)
        if len(t.made) > made:
            t.made[-1][1]()
        d.end("ended by owner")
    return out


def test_three_allowed_fourth_blocked(gate, monkeypatch):
    a = real(monkeypatch)
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})
    r = run(d, t, now, KEY, 4)
    assert [x["started"] for x in r] == [True, True, True, False]
    assert r[3].get("judge_cap") and a.rang == 3 and len(t.made) == 3
    assert all(sec == 93 for sec, _ in t.made)                       # judge delay unchanged
    assert recs(gate, "judge_cap_reached")
    assert KEY not in str(gate.audit.records())
    f = gate.audit.path.parent / N.JUDGE_CAP_FILE
    assert f.exists() and KEY not in f.read_text(encoding="utf-8")


def test_count_is_persisted_across_restarts(gate, monkeypatch):
    real(monkeypatch)
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})
    run(d, t, now, KEY, 3)
    d2, t2, now2 = drill(gate, env={N.JUDGE_KEY_ENV: KEY})          # "restart": a new drill object
    assert run(d2, t2, now2, KEY, 1)[0]["started"] is False and not t2.made


def test_non_judges_are_not_capped(gate, monkeypatch):
    a = real(monkeypatch)
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})
    assert all(x["started"] for x in run(d, t, now, "", 5)) and a.rang == 5
    assert all(x["started"] for x in run(d, t, now, "wrong-key", 2))
    assert not recs(gate, "judge_cap_reached")


def test_cap_is_per_key(gate, monkeypatch):
    real(monkeypatch)
    jc = N.JudgeCalls(gate.audit.path.parent)
    assert [jc.take(KEY) for _ in range(4)] == [True, True, True, False]
    assert jc.take(KEY2) and jc.used(KEY2) == 1 and jc.used(KEY) == 3


def test_cooldown_checked_first(gate, monkeypatch):
    real(monkeypatch)
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})
    now[0] = N.TEST_COOLDOWN + 1
    assert d.start(judge_key=KEY)["started"]
    d.end("x")
    r = d.start(judge_key=KEY)                                        # inside 20 minutes
    assert r["started"] is False and not r.get("judge_cap")
    assert N.JudgeCalls(gate.audit.path.parent).used(KEY) == 1        # refusal did not use a call


def test_dry_run_tests_do_not_count(gate):
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})               # no Twilio: dry run
    assert all(x["started"] for x in run(d, t, now, KEY, 5))


def test_unreadable_count_file_fails_safe(gate, monkeypatch):
    real(monkeypatch)
    (gate.audit.path.parent / N.JUDGE_CAP_FILE).write_text("{oops", encoding="utf-8")
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY})
    assert run(d, t, now, KEY, 1)[0].get("judge_cap") and not t.made


def test_web_shows_polite_message(setup, monkeypatch):
    s = setup
    real(monkeypatch)
    monkeypatch.setenv(N.JUDGE_KEY_ENV, KEY)
    jc = N.JudgeCalls(s.gate.audit.path.parent)
    for _ in range(3):
        jc.take(KEY)
    s.post("/act", token=token(s.get("/settings")[1], "Test my alert"), judge_key=KEY)
    _, page = s.get("/settings")
    assert "You&#x27;ve used your 3 demo test calls. Thanks for testing Bridge Warden!" in page or \
        "You've used your 3 demo test calls. Thanks for testing Bridge Warden!" in page
    assert KEY not in page and not s.app.alert_test.pending()
