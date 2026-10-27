"""v5: judges get a fixed 93-second test-call delay (1 min 33 s); everyone else keeps the clock rule.
A judge is recognized only by a judge key configured on the host (env BW_JUDGE_KEY or a private file named by
BW_JUDGE_KEY_FILE), never by anything in the public code. The 20-minute cooldown applies to judges too.
Offline only: fake timers, dry-run calls, no network."""
from datetime import datetime

import pytest

from test_v4_alert_test import Timers, drill, recs  # noqa: F401
from test_v4_ui import setup, token  # noqa: F401  (fixture)
from bridge_warden import notify as N
from bridge_warden.guard import scrub

KEY = "test-judge-key-not-real-0123456789"
WALL = datetime(2026, 10, 26, 19, 46)          # clock rule: 1946 s -> halved -> 973 s


def test_constants():
    assert N.JUDGE_TEST_DELAY == 93 and N.TEST_COOLDOWN == 1200


def test_judge_gets_93_seconds(gate):
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY}, wall=lambda: WALL)
    assert d.start(judge_key=KEY)["started"]
    assert t.made[-1][0] == 93
    r = recs(gate, "alert_test")[-1]
    assert r["judge"] is True and KEY not in str(gate.audit.records())


def test_non_judge_keeps_clock_rule(gate):
    d, t, _ = drill(gate, env={N.JUDGE_KEY_ENV: KEY}, wall=lambda: WALL)
    assert d.start()["started"]
    assert t.made[-1][0] == N.drill_call_delay(WALL) == 973
    assert recs(gate, "alert_test")[-1]["judge"] is False


@pytest.mark.parametrize("given", ["", "wrong", KEY[:-1], KEY + "x", KEY.upper(), None])
def test_wrong_key_keeps_clock_rule(gate, given):
    d, t, _ = drill(gate, env={N.JUDGE_KEY_ENV: KEY}, wall=lambda: WALL)
    d.start(judge_key=given or "")
    assert t.made[-1][0] == 973


def test_no_judge_key_configured_means_nobody_is_a_judge(gate):
    d, t, _ = drill(gate, env={}, wall=lambda: WALL)
    d.start(judge_key=KEY)
    assert t.made[-1][0] == 973
    assert not N.is_judge("", {N.JUDGE_KEY_ENV: ""}) and not N.is_judge("short", {N.JUDGE_KEY_ENV: "short"})


@pytest.mark.parametrize("hhmm", [(0, 0), (0, 59), (9, 5), (12, 0), (23, 59)])
def test_clock_rule_unchanged_for_everyone_else(hhmm):
    now = datetime(2026, 10, 26, *hhmm)
    assert N.test_call_delay(now) == N.drill_call_delay(now)
    assert N.test_call_delay(now, judge=True) == 93


def test_key_from_private_file(tmp_path):
    f = tmp_path / "judge_key.txt"
    f.write_text(KEY + "\n", encoding="utf-8")
    env = {N.JUDGE_KEY_FILE_ENV: str(f)}
    assert N.is_judge(KEY, env) and not N.is_judge("nope", env)
    assert N.judge_key({N.JUDGE_KEY_FILE_ENV: str(tmp_path / "missing")}) == ""


def test_cooldown_still_applies_to_judges(gate):
    d, t, now = drill(gate, env={N.JUDGE_KEY_ENV: KEY}, wall=lambda: WALL)
    assert d.start(judge_key=KEY)["started"]
    d.end("ended by owner")
    now[0] = 10 * 60
    assert d.start(judge_key=KEY)["started"] is False             # still inside 20 minutes
    assert len(t.made) == 1 and recs(gate, "alert_test_refused")
    now[0] = N.TEST_COOLDOWN + 1
    assert d.start(judge_key=KEY)["started"] and t.made[-1][0] == 93


def test_key_is_redacted_by_scrub(monkeypatch):
    monkeypatch.setenv(N.JUDGE_KEY_ENV, KEY)
    assert KEY not in scrub("key=" + KEY)


def test_settings_page_judge_key_field_and_delay(setup, monkeypatch):
    s = setup
    _, page = s.get("/settings")
    assert 'name="judge_key"' not in page                            # no key configured: no field
    monkeypatch.setenv(N.JUDGE_KEY_ENV, KEY)
    t = Timers()
    s.app.alert_test.timer = t
    s.app.alert_test.wall = lambda: WALL
    _, page = s.get("/settings")
    assert 'name="judge_key"' in page and 'type="password"' in page and KEY not in page
    s.post("/act", token=token(page, "Test my alert"), judge_key=KEY)
    assert t.made[-1][0] == 93
    _, page = s.get("/")
    assert KEY not in page


def test_settings_page_without_key_uses_clock_rule(setup, monkeypatch):
    s = setup
    monkeypatch.setenv(N.JUDGE_KEY_ENV, KEY)
    t = Timers()
    s.app.alert_test.timer = t
    s.app.alert_test.wall = lambda: WALL
    s.post("/act", token=token(s.get("/settings")[1], "Test my alert"))
    assert t.made[-1][0] == 973
