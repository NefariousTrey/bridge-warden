# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0.
"""Oct 27 2026 (Trey): the hosted judge demo uses REAL xAI on our key, capped per judge key (BW_JUDGE_XAI_CAP,
default 1000). At the cap: sample answer + "Judge AI limit reached, showing sample answer", nothing sent, no cost.
Also: real calls have a hard max length (Twilio TimeLimit, BW_CALL_MAX_SECONDS, default 1800 = 30 minutes).
xAI is always mocked here (no network). Every key below is fake."""
import json
import threading
import urllib.parse
from pathlib import Path

import pytest

from bridge_warden import ag_studio as STUDIO
from bridge_warden import help_chat as HC
from bridge_warden import hosted as Ho
from bridge_warden import judge_ai as JA
from bridge_warden import notify as N
from bridge_warden.models import ProposedAction
from conftest import NOON_ET  # noqa: F401
from test_xai import FAKE_KEY, MockXai, make_gate, reply
import test_v5_render_hosted as HT

J1 = "judge-one-" + "a" * 20
J2 = "judge-two-" + "b" * 20


def _counter(tmp_path, n):
    return JA.JudgeXaiCounter(tmp_path / "audit", limit=n)


# ---- the counter --------------------------------------------------------------------------------------------------
def test_cap_from_env_default_1000():
    assert JA.cap({}) == 1000 == JA.DEFAULT_CAP
    assert JA.cap({"BW_JUDGE_XAI_CAP": "25"}) == 25
    assert JA.cap({"BW_JUDGE_XAI_CAP": "lots"}) == 1000                # bad value = default, never unlimited
    assert JA.cap({"BW_JUDGE_XAI_CAP": "-5"}) == 0
    assert JA.cap({"BW_JUDGE_XAI_CAP": "999999999"}) == JA.MAX_CAP


def test_default_cap_enforced_at_1000_and_1001_falls_back(tmp_path):
    c = JA.JudgeXaiCounter(tmp_path, env={})
    assert c.limit == 1000
    assert all(c.take(J1) for _ in range(1000))
    assert c.take(J1) is False and c.used(J1) == 1000 and c.left(J1) == 0   # message 1001: refused
    assert c.left(J2) == 1000                                                   # another judge: untouched


def test_counter_is_per_key_persisted_and_never_stores_the_key(tmp_path):
    c = _counter(tmp_path, 3)
    assert [c.take(J1) for _ in range(4)] == [True, True, True, False]
    assert c.take(J2) and c.used(J2) == 1
    again = _counter(tmp_path, 3)                                              # a new process (restart with a disk)
    assert again.used(J1) == 3 and again.used(J2) == 1 and again.take(J1) is False
    raw = (tmp_path / "audit" / JA.FILE).read_text()
    assert J1 not in raw and J2 not in raw and "judge-" not in raw


def test_unreadable_file_counts_as_used_up(tmp_path):
    c = _counter(tmp_path, 5)
    c.path.parent.mkdir(parents=True)
    c.path.write_text("{broken")
    assert c.take(J1) is False and c.left(J1) == 0


# ---- every AI part stops at the cap -------------------------------------------------------------------------------
def test_review_cap_then_sample_answer_and_nothing_sent(engine, tmp_path):
    mock = MockXai(reply("low", "allow"))
    g = make_gate(engine, tmp_path, mock)
    c = _counter(tmp_path, 3)                       # 1 preflight + 2 reviews
    n = iter(range(10))
    a = lambda: ProposedAction("payout", f"{20 + next(n)}.00", "USD", "writer@personal.example.com",
                               "payout for completed blog post")
    with JA.acting_as(J1, c):
        for _ in range(2):
            out = g.propose(a())
            assert not any("Judge AI limit" in r for r in out["reasons"])
        sent = len(mock.requests)
        assert sent == 3 and c.used(J1) == 3
        g.ai.cfg["on_ai_failure"] = "hold"          # even under "hold", the limit is not an AI failure
        out = g.propose(a())                        # message 4 = one past the cap
    assert len(mock.requests) == sent               # nothing left the machine
    assert out["verdict"] == "allow", out               # "hold" mode did not hold it: the cap is not an AI failure
    last = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines() if '"ai_check"' in l][-1]
    assert last["result"]["skipped"] == JA.SKIP and last["sent"] is False
    assert JA.LIMIT_NOTE in (tmp_path / "a.jsonl").read_text()


def test_help_chat_and_advise_fall_back_with_the_note(engine, tmp_path):
    mock = MockXai(reply())
    g = make_gate(engine, tmp_path, mock)
    c = _counter(tmp_path, 0)                       # cap 0: no message at all
    with JA.acting_as(J1, c):
        res = g.ai.advise({"x": 1}, "what now?")
        assert res["called"] is False and res["skipped"] == JA.SKIP
        out = HC.ask(g, "now", "What does the red light mean for my payment?", {"step": 0})
    assert mock.requests == [] and out["by_ai"] is False
    assert JA.LIMIT_NOTE in out["answer"], out["answer"]


def test_owner_and_background_are_not_counted(engine, tmp_path):
    mock = MockXai(reply())
    g = make_gate(engine, tmp_path, mock)
    c = _counter(tmp_path, 0)
    with JA.acting_as("", c):                       # the owner: no judge acting
        assert g.ai.advise({"x": 1}, "hi").get("called") is True
    assert not (tmp_path / "audit" / JA.FILE).exists()


# ---- hosted: judge login, real xAI on our key, AG chat panel, no key in logs --------------------------------------
@pytest.fixture
def hj(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(STUDIO, "ready", lambda: True)
    keys = tmp_path / "judges.txt"
    keys.write_text(J1 + "\n" + J2 + "\n")
    mock = MockXai(reply())
    env = HT.env_for(tmp_path, XAI_API_KEY=FAKE_KEY, XAI_ZDR_CONFIRMED="1", BW_JUDGE_KEY_FILE=str(keys),
                     BW_JUDGE_XAI_CAP="2")
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"),
                             xai_transport=mock)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s, app, env, mock, tmp_path
    s.shutdown()
    s.server_close()


def _login(s, k):
    st, h, _ = HT.req(s, "POST", "/login", urllib.parse.urlencode({"k": k}),
                      {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + HT.HOST})
    assert st == 303
    return h["set-cookie"].split(";")[0]


def _studio(s, ck):
    body = json.dumps({"input": [{"role": "user", "content": "How many red payments?"}]})
    return HT.req(s, "POST", "/ag-studio/v1/responses", body,
                  {"Cookie": ck, "Content-Type": "application/json", "Origin": "https://" + HT.HOST})


def test_hosted_judges_get_real_xai_until_their_cap(hj, capsys):
    s, app, env, mock, tmp_path = hj
    assert app.gate.ai is not None and app.gate.ai.skip_reason() is None        # key + ZDR from env
    j1 = _login(s, J1)
    st, _, body = _studio(s, j1)                    # preflight + 1 answer = 2 = the cap
    assert st == 200, body
    sent = len(mock.requests)
    st, _, body = _studio(s, j1)                    # one past the cap
    assert st == 429 and JA.LIMIT_NOTE in json.loads(body)["error"]["message"]
    assert len(mock.requests) == sent               # nothing sent, no cost
    st, _, _ = _studio(s, _login(s, J2))            # judge 2 has their own allowance
    assert st == 200
    st, _, _ = _studio(s, HT.login(s))              # the owner (login key) is not capped here
    assert st == 200
    # the xAI key and judge keys never reach a log, the counter file or the console
    out = capsys.readouterr()
    blobs = [out.out, out.err] + [p.read_text(errors="replace") for p in Path(env["BW_DATA_DIR"]).rglob("*")
                                  if p.is_file()]
    for b in blobs:
        assert FAKE_KEY not in b and J1 not in b and J2 not in b
    assert all(r["headers"]["Authorization"] == "Bearer " + FAKE_KEY for r in mock.requests)   # it IS used, only here


def test_hosted_without_xai_key_has_no_ai(tmp_path):
    env = HT.env_for(tmp_path)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    try:
        assert app.gate.ai is None
    finally:
        s.server_close()


def test_hosted_without_zdr_env_sends_nothing(tmp_path):
    mock = MockXai(reply())
    env = HT.env_for(tmp_path, XAI_API_KEY=FAKE_KEY)
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"),
                             xai_transport=mock)
    try:
        assert app.gate.ai.skip_reason() == "zdr_not_confirmed_by_owner" and mock.requests == []
    finally:
        s.server_close()


def test_judge_mode_still_has_no_ai():
    import inspect
    from bridge_warden import judge
    src = inspect.getsource(judge)
    assert "XAI_API_KEY" in src                    # judge mode refuses an xAI key: sample answers only


# ---- calls: hard max length 30 minutes ---------------------------------------------------------------------------
def _twilio(env_more=None):
    sent = []

    def sender(method, url, headers, body, timeout, **kw):
        sent.append(urllib.parse.parse_qs(body.decode()))
        return 201, {}, b'{"sid": "CA' + b"1" * 32 + b'"}'
    env = {"TWILIO_ACCOUNT_SID": HT.SID, "TWILIO_AUTH_TOKEN": "tok-" + "x" * 28,
           "TWILIO_FROM_NUMBER": "+15550001111", "BW_OWNER_PHONE": "+15550002222", **(env_more or {})}
    return N.TwilioCallAdapter(env=env, sender=sender), sent


@pytest.mark.parametrize("more", [{}, {"BW_CALL_URL": "https://bw-test.onrender.com"}])
def test_every_real_call_has_a_30_minute_time_limit(more):
    ad, sent = _twilio(more)
    ad.place_call("Bridge Warden test call. Your alert works.")
    assert sent and sent[0]["TimeLimit"] == ["1800"]


def test_call_max_seconds_env():
    assert N.call_max_seconds({}) == 1800
    assert N.call_max_seconds({"BW_CALL_MAX_SECONDS": "600"}) == 600
    for bad in ("0", "-1", "abc", "99999"):
        assert N.call_max_seconds({"BW_CALL_MAX_SECONDS": bad}) == 1800
    ad, sent = _twilio({"BW_CALL_MAX_SECONDS": "600"})
    ad.place_call("Bridge Warden test call.")
    assert sent[0]["TimeLimit"] == ["600"]


def test_judge_wait_between_calls_unchanged():
    assert N.JUDGE_CALL_CAP == 3
    import inspect
    assert "1200" in inspect.getsource(N) or "20 * 60" in inspect.getsource(N)


def test_render_build_fetches_ag_studio_only_with_the_key_and_never_echoes_it():
    import re
    root = Path(__file__).resolve().parent.parent
    for f in ("render.yaml", "render-judge.yaml"):
        y = (root / f).read_text()
        b = re.search(r"^\s+buildCommand: '(.*)'$", y, re.M).group(1)
        assert 'if [ -n "${BW_AG_STUDIO_LICENSE_KEY:-}" ]; then bash scripts/fetch_ag_studio.sh' in b
        assert "set -x" not in b and "echo $" not in b and 'echo "$' not in b and "printenv" not in b
    sh = (root / "scripts" / "fetch_ag_studio.sh").read_text()
    assert "$BW_AG_STUDIO_LICENSE_KEY" not in sh and "set -x" not in sh
