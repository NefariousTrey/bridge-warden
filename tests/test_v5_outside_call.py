"""OUTSIDE 2026-10-27: an account-watch alert (event in PayPal itself) rides as a signed &o=1 on the Worker /voice link,
so the call says the check-PayPal line instead of "Nothing was sent". Blocked-payment alerts are unchanged."""
import re
import urllib.parse
from pathlib import Path

from test_v4_alert_test import ENV  # noqa: F401
from test_v5_name import B, sent_body
from bridge_warden import alerts as A
from bridge_warden import hosted as H
from bridge_warden import notify as N

JS = (Path(__file__).resolve().parents[1] / "call-worker" / "src" / "index.js").read_text(encoding="utf-8")


def url_of(text):
    body = sent_body(lambda f: N.TwilioCallAdapter(env={**ENV, "BW_CALL_URL": B}, sender=f).place_call(text, name="Trey"))
    return body["Url"][0]


def test_same_line_everywhere():
    assert A.OUTSIDE_LINE == N.OUTSIDE_LINE == "This happened in PayPal itself, so money may have moved. Check PayPal now."
    assert f'export const OUTSIDE_LINE = "{N.OUTSIDE_LINE}";' in JS
    assert '"o"' in re.search(r"OUR_KEYS = new Set\(\[[^\]]*\]\)", JS).group(0) and "o" in N.LINK_KEYS


def test_outside_alert_link_has_o_blocked_does_not():
    real = " ".join(N.call_lines(N.REAL_WHAT, test=False, name="Trey"))
    out = real.replace("Nothing was sent.", A.OUTSIDE_LINE)
    assert "&o=1" in url_of(out) and "/voice?" in url_of(out)
    assert "o=1" not in url_of(real)
    assert "o=1" not in N.call_url(B, "gather", False, outside=True)          # only the opening step


def test_python_twiml_mirror():
    out = N.voice_twiml(B, False, name="Trey", outside=True)
    assert A.OUTSIDE_LINE in out and "Nothing was sent" not in out
    plain = N.voice_twiml(B, False, name="Trey")
    assert "Nothing was sent." in plain and A.OUTSIDE_LINE not in plain
    assert A.OUTSIDE_LINE not in N.voice_twiml(B, True, True, outside=True)   # call-in demo never
    assert A.OUTSIDE_LINE in H.call_twiml("voice", B, "t=0&n=1&nm=Trey&o=1", {})
    assert "Nothing was sent." in H.call_twiml("voice", B, "t=0&n=1&nm=Trey", {})
