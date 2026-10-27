"""RETENTION: optional 'forget my calls' cleanup. Fake Twilio only; nothing real is contacted."""
import json
import urllib.parse

from bridge_warden import notify, net

SID = "AC" + "a" * 32
ENV = {"TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": "tok-secret-1", "TWILIO_FROM_NUMBER": "+15550001111",
       "BW_OWNER_PHONE": "+15550002222"}
C1, C2, C3 = ("CA" + c * 32 for c in "123")
R1 = "RE" + "9" * 32


class FakeTwilio:
    def __init__(self, calls, recs=None, fail_delete=()):
        self.calls = dict(calls)          # sid -> status
        self.recs = dict(recs or {})      # call sid -> [rec sid]
        self.fail = set(fail_delete)
        self.log = []

    def __call__(self, method, url, headers, body, timeout, extra_host=None):
        assert extra_host == "api.twilio.com"
        net.check_url(url, extra_host=extra_host)          # same pinning as the real sender
        assert headers["Authorization"].startswith("Basic ")
        self.log.append((method, url))
        path = urllib.parse.urlsplit(url).path.split(f"/Accounts/{SID}")[1]
        if method == "GET" and path == "/Calls.json":
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            assert q["PageSize"] == "100" and {q["From"], q["To"]} == {"+15550001111", "+15550002222"}
            rows = [{"sid": s, "status": st} for s, st in self.calls.items()] if q["From"] == "+15550001111" else []
            return 200, {}, json.dumps({"calls": rows}).encode()
        if method == "GET" and path.endswith("/Recordings.json"):
            cs = path.split("/")[2]
            return 200, {}, json.dumps({"recordings": [{"sid": r} for r in self.recs.get(cs, [])]}).encode()
        if method == "DELETE" and path.startswith("/Recordings/"):
            return 204, {}, b""
        if method == "DELETE" and path.startswith("/Calls/"):
            cs = path.split("/")[2][:-5]
            if cs in self.fail:
                return 404, {}, b"{}"
            self.calls.pop(cs, None)
            return 204, {}, b""
        return 400, {}, b"{}"


def test_not_set_up_does_nothing():
    f = FakeTwilio({C1: "completed"})
    r = notify.forget_calls(env={}, sender=f)
    assert r["ready"] is False and r["deleted"] == 0 and f.log == []


def test_deletes_finished_calls_and_recordings_skips_live():
    f = FakeTwilio({C1: "completed", C2: "in-progress", C3: "no-answer"}, recs={C1: [R1]})
    r = notify.forget_calls(env=ENV, sender=f)
    assert r == {"ready": True, "found": 2, "deleted": 2, "recordings_deleted": 1, "skipped_live": 1, "errors": 0}
    assert list(f.calls) == [C2]                         # the live call was left alone
    dels = [u for m, u in f.log if m == "DELETE"]
    assert any(R1 in u for u in dels)
    assert dels.index(next(u for u in dels if R1 in u)) < dels.index(next(u for u in dels if C1 in u))


def test_dry_run_deletes_nothing():
    f = FakeTwilio({C1: "completed", C3: "busy"})
    r = notify.forget_calls(env=ENV, sender=f, dry_run=True)
    assert r["found"] == 2 and r["deleted"] == 0
    assert all(m == "GET" for m, _ in f.log) and len(f.calls) == 2


def test_failed_delete_is_counted_and_bad_sids_ignored():
    f = FakeTwilio({C1: "completed", "CAnot-a-sid/../x": "completed"}, fail_delete={C1})
    r = notify.forget_calls(env=ENV, sender=f)
    assert r["errors"] >= 1 and r["deleted"] == 0
    assert not any("not-a-sid" in u for _, u in f.log)


def test_result_never_holds_secrets_or_numbers():
    f = FakeTwilio({C1: "completed"})
    txt = json.dumps(notify.forget_calls(env=ENV, sender=f))
    for v in ENV.values():
        assert v not in txt


def test_cli_prints_counts_only(monkeypatch, capsys):
    from bridge_warden import cli
    f = FakeTwilio({C1: "completed"})
    real = notify.forget_calls
    monkeypatch.setattr(notify, "forget_calls", lambda dry_run=False: real(env=ENV, sender=f, dry_run=dry_run))
    cli.main(["forget-calls"])
    out = capsys.readouterr().out
    assert "Deleted 1 call log(s)" in out
    for v in ENV.values():
        assert v not in out
