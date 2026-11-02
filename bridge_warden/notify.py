"""Optional phone push when something needs you (v4). OFF by default.

Desktop alerts come from the dashboard tab itself (browser Notification API; no server involved).
This module adds an optional push to YOUR OWN ntfy-style server (for example ntfy running on this
computer). Policy:  "notify": {"webhook_enabled": true, "webhook_url": "http://127.0.0.1:8090/bridge-warden"}
Only loopback URLs pass policy validation and net.check_url, so no outside service is ever contacted.
The message is fixed text: no payee, amount or agent words leave the app.

"Call me on fraud" (v4, OFF by default): a pluggable call channel ("ADT for your money").
- "dry_run" (default): never dials, texts or contacts any service; writes "would call owner" to the signed log.
- "twilio" (EXPERIMENTAL, pending Trey's test on his own phone): uses the OWNER'S OWN Twilio account.
  Bridge Warden pays for nothing. Needs "experimental": true in policy plus these on this computer only
  (never in policy.json, never logged): TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
  BW_OWNER_PHONE. If any is missing it falls back to the dry run.
Policy:  "notify": {"call_on_fraud": {"enabled": true, "provider": "dry_run", "experimental": false}}
It fires only when a payment is BLOCKED (likely fraud), not for ordinary held payments.
"Test my alert" (Settings) schedules ONE unannounced test call (delay: drill_call_delay), with a fixed test script.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import json
import os
import random
import re
from datetime import datetime
import threading
import time as _time
import urllib.parse
from pathlib import Path
from xml.sax.saxutils import escape as _xml

from . import dashboard, net
from .guard import scrub

TITLE = "Bridge Warden needs you"
CALL_TEXT = ("This is Bridge Warden. A payment that looks like fraud was blocked. Nothing was sent. "
             "Open your Bridge Warden dashboard. If you did not expect this, lock your PayPal: change your password "
             "and turn on two-step login.")
TEST_CALL_TEXT = ("This is a Bridge Warden test. If real suspicious activity happens, you'll get a call like this "
                  "explaining how to lock your PayPal.")
TEST_DELAY_MAX = 1200           # seconds: the clock rule never waits longer than 20 minutes
MIDNIGHT_DELAY = 333            # seconds at 00:00; minus the minute during the midnight hour


def drill_call_delay(now: datetime) -> float:
    """THE one place the test-call wait is set (Trey's rule). The 24-hour clock time read as seconds (HHMM):
    19:46 -> 1946 s. Over 1200 s it is halved (19:46 -> 973 s, 23:59 -> 1179.5 s); 12:00 -> 1200 s stays.
    During the midnight hour (00:00-00:59) it is 333 minus the minute: 00:00 -> 333, 00:03 -> 330, 00:59 -> 274."""
    if now.hour == 0:
        return MIDNIGHT_DELAY - now.minute
    s = now.hour * 100 + now.minute
    return s / 2 if s > TEST_DELAY_MAX else s
JUDGE_TEST_DELAY = 93         # seconds (1 min 33 s): the ONLY delay a judge gets; everyone else: drill_call_delay
JUDGE_KEY_ENV = "BW_JUDGE_KEY"            # the judge key itself (e.g. a host secret), never in the code
JUDGE_KEY_FILE_ENV = "BW_JUDGE_KEY_FILE"  # or: path(s) to private file(s), one judge key per line
JUDGE_KEY_MIN = 16             # a configured key shorter than this is ignored (no judge mode for it)
JUDGE_KEYS_MAX = 200           # per-judge keys: plenty for a judging panel; more lines are ignored


JUDGE_UNTIL_ENV = "BW_JUDGE_UNTIL"    # PREFLIP 2026-11-02: from this date (US Eastern) judge keys stop working
JUDGE_UNTIL_SHIPPED = "2026-12-16"    # judging is free through Dec 15, 2026
JUDGE_UNTIL_DEFAULT = JUDGE_UNTIL_SHIPPED


def judge_until(env=None):
    """The first date (a datetime.date, US Eastern) on which judge keys no longer work. Env BW_JUDGE_UNTIL as
    YYYY-MM-DD (default 2026-12-16). A bad value falls back to the default, so it can never extend judging."""
    from datetime import date
    env = os.environ if env is None else env
    try:
        d = date.fromisoformat(str(env.get(JUDGE_UNTIL_ENV) or "").strip())
    except ValueError:
        d = None
    dflt = date.fromisoformat(JUDGE_UNTIL_DEFAULT)
    return d if d is not None else dflt


def judging_over(env=None, today=None) -> bool:
    """True on or after BW_JUDGE_UNTIL (US Eastern): then every judge key is refused."""
    if today is None:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).date()
    return today >= judge_until(env)


def judge_keys(env=None) -> list:
    """Every configured judge key (per-judge keys). BW_JUDGE_KEY (one key) plus every line of the file(s)
    named by BW_JUDGE_KEY_FILE (several files may be joined with os.pathsep). One key per line; blank lines
    and lines starting with "#" are skipped; a key shorter than 16 characters is ignored. Never logged.
    From BW_JUDGE_UNTIL on (default 2026-12-16, US Eastern) there are no judge keys at all."""
    env = os.environ if env is None else env
    if judging_over(env):
        return []
    raw = [str(env.get(JUDGE_KEY_ENV) or "")]
    for f in str(env.get(JUDGE_KEY_FILE_ENV) or "").split(os.pathsep):
        if f.strip():
            try:
                raw += Path(f.strip()).read_text(encoding="utf-8").splitlines()
            except Exception:
                pass                       # missing / unreadable file: no keys from it
    out = []
    for k in (x.strip() for x in raw):
        if len(k) >= JUDGE_KEY_MIN and not k.startswith("#") and k not in out:
            out.append(k)
    return out[:JUDGE_KEYS_MAX]


def judge_key(env=None) -> str:
    """The first configured judge key ("" = judge mode off). Kept for older callers; use judge_keys()."""
    ks = judge_keys(env)
    return ks[0] if ks else ""


def is_judge(given, env=None) -> bool:
    """True only if `given` matches ONE of the configured judge keys. Constant-time: every key is compared,
    with no early exit. Never logs either value."""
    keys = judge_keys(env)
    if not keys or not isinstance(given, str) or not given.strip():
        return False
    g = given.strip().encode("utf-8")
    hit = False
    for k in keys:
        hit |= hmac.compare_digest(g, k.encode("utf-8"))
    return hit


JUDGE_CALL_CAP = 3            # real voice test calls per judge key (server-side, persisted)
JUDGE_CAP_SAY = "You've used your 3 demo test calls. Thanks for testing Bridge Warden!"
# JUDGEFIX 2026-11-01: on the hosted demo a logged-in judge NEVER reaches Twilio. A real call would ring the
# owner's own phone (BW_OWNER_PHONE), which is useless to the judge and costs the owner. So while a judge is
# acting (judge_ai thread-local, set by hosted.py for that one request) the Twilio adapter reports not ready:
# no call, no text, no Twilio read. Test my alert sends a hosted judge to Hear the call (/hear) instead.
JUDGE_NO_PHONE_SAY = ("Judge demo: no phone call is placed. Here is the same call, in your browser. "
                      "Nothing happens to your money.")


def judge_acting() -> bool:
    """True while a hosted judge's request is running (never for the owner, never on a background thread)."""
    from . import judge_ai as JA
    return bool(JA.current()[0])
JUDGE_CAP_FILE = "judge_calls.json"   # in the audit folder; holds a random salt + HMAC tags, never the key


class JudgeCalls:
    """Counts REAL test calls per judge key. The key itself is never stored or logged: each key is turned into
    an HMAC tag with a random per-install salt. Atomic writes. Unreadable file = treated as full (fail safe)."""

    def __init__(self, folder):
        self.path = Path(folder) / JUDGE_CAP_FILE
        self._lock = threading.Lock()

    def _read(self):
        if not self.path.exists():
            return {"salt": secrets.token_hex(16), "counts": {}}
        d = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("counts"), dict) or not d.get("salt"):
            raise ValueError("bad judge_calls file")
        return d

    def _tag(self, d, key: str) -> str:
        return hmac.new(d["salt"].encode(), key.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def used(self, key: str) -> int:
        try:
            d = self._read()
        except Exception:
            return JUDGE_CALL_CAP
        return int(d["counts"].get(self._tag(d, key), 0))

    def take(self, key: str) -> bool:
        """Reserve one call for this key. False (and no change) when the cap is reached or the file is unreadable."""
        with self._lock:
            try:
                d = self._read()
            except Exception:
                return False
            tag = self._tag(d, key)
            n = int(d["counts"].get(tag, 0))
            if n >= JUDGE_CALL_CAP:
                return False
            d["counts"][tag] = n + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(tmp, self.path)
            return True


def test_call_delay(now: datetime, judge: bool = False) -> float:
    """Judges: a fixed JUDGE_TEST_DELAY. Everyone else: the clock rule (drill_call_delay), unchanged."""
    return float(JUDGE_TEST_DELAY) if judge else drill_call_delay(now)
TEST_COOLDOWN = 1200            # one test per 20 minutes, enforced here on the server (Trey), not only in the UI
COOLDOWN_SAY = "A test is already running. You can start another in a little while."   # exact; no time left
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
SID = re.compile(r"^AC[0-9a-fA-F]{32}$")
TWILIO_ENV = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "BW_OWNER_PHONE")


class CallAdapter:
    """Interface for a phone call / SMS alert provider. place_call() must return a dict and must not raise."""
    name = "base"
    real = False

    def place_call(self, text: str, name: str = "") -> dict:   # pragma: no cover - interface
        raise NotImplementedError


class DryRunCallAdapter(CallAdapter):
    """Makes NO call. No network, no number, no account, no cost. Just says what it would do."""
    name = "dry_run"

    def place_call(self, text: str, name: str = "", voice=None) -> dict:
        return {"would": "call owner", "text": text, "dialed": False, "cost": 0}


# VOICE 2026-10-26: the <Say> voice is a setting. Default "man" = Twilio's free Basic voice. Natural voices
# (Polly.* / Google.*) cost a small Twilio text-to-speech fee per 100 characters, billed to the owner's own
# Twilio: https://www.twilio.com/en-us/voice/pricing/us . Same rule as call-worker/src/index.js (CALL_VOICE).
FREE_VOICE = "man"
VOICE_OK = re.compile(r"^(man|woman|alice|Polly\.[A-Z][A-Za-z\u00C0-\u017F]{1,20}(-(Neural|Generative))?|"
                      r"Google\.[a-z]{2,3}-[A-Z]{2}-(Standard|Wavenet|Neural2|Chirp3-HD)-[A-Za-z]{1,12})$")


def voice_of(v) -> str:
    v = str(v or "").strip()
    return v if VOICE_OK.match(v) else FREE_VOICE


# VOICEPICK 2026-10-26 (Trey): Google Charon is Bridge Warden's default call voice; each owner can pick their own in
# Settings (policy.json "call_voice"). Same allow-list as the Worker. Twilio's list: https://www.twilio.com/docs/voice/twiml/say/text-speech
# Cost = Twilio text-to-speech for a ~300-character call, billed to the owner's own Twilio, plus minutes (~$0.014/min US).
DEFAULT_VOICE = "Google.en-US-Chirp3-HD-Charon"
VOICE_TIER_COST = {"Free": "$0", "Standard": "~$0.0024", "Neural": "~$0.0096", "Generative": "~$0.039"}
MINUTE_COST = "~$0.014/min"
VOICE_CHOICES = (   # (Twilio voice id, plain label) -- the Settings picker; every id passes VOICE_OK
    ("Google.en-US-Chirp3-HD-Charon", "Charon (Google, male) - our pick"),
    ("Google.en-US-Chirp3-HD-Aoede", "Aoede (Google, female)"),
    ("Google.en-US-Chirp3-HD-Puck", "Puck (Google, male)"),
    ("Polly.Matthew-Generative", "Matthew (Amazon, male)"),
    ("Polly.Joanna-Neural", "Joanna (Amazon, female)"),
    ("Polly.Matthew-Neural", "Matthew (Amazon, male)"),
    ("Polly.Joanna", "Joanna (Amazon, female)"),
    ("Polly.Matthew", "Matthew (Amazon, male)"),
    ("man", "Basic man (Twilio, robotic)"),
    ("woman", "Basic woman (Twilio, robotic)"),
)


def voice_tier(v) -> str:
    v = voice_of(v)
    if v in ("man", "woman", "alice"):
        return "Free"
    if v.endswith("-Generative") or "-Chirp3-HD-" in v:
        return "Generative"
    if v.endswith("-Neural") or "-Neural2-" in v or "-Wavenet-" in v:
        return "Neural"
    return "Standard"


def voice_cost(v) -> str:
    t = voice_tier(v)
    return "free" if t == "Free" else f"{VOICE_TIER_COST[t]} per call + {MINUTE_COST}"


def default_voice(env=None) -> str:
    """What a call says when the owner has NOT picked a voice (server settings, unchanged by VOICEPICK):
    BW_CALL_VOICE if set; else, with a call Worker (BW_CALL_URL), the Worker's CALL_VOICE (Charon on Bridge
    Warden's own Worker); else Twilio's free "man"."""
    env = (os.environ if env is None else env) or {}
    e = str(env.get("BW_CALL_VOICE", "") or "").strip()
    if e:
        return voice_of(e)
    return DEFAULT_VOICE if str(env.get("BW_CALL_URL", "") or "").strip() else FREE_VOICE


def pick_voice(saved=None, env=None) -> str:
    """The voice a call will use: the owner's Settings pick (policy.json call_voice) if set, else default_voice.
    Anything not on the allow-list becomes the free "man" voice."""
    if str(saved or "").strip():
        return voice_of(saved)
    return default_voice(env)


def _takes_voice(adapter) -> bool:
    import inspect
    try:
        return "voice" in inspect.signature(adapter.place_call).parameters
    except (TypeError, ValueError):
        return False


def place(adapter, text: str, name: str = "", voice=None) -> dict:
    """adapter.place_call with the voice when the adapter understands it (older adapters: name only)."""
    if voice is not None and _takes_voice(adapter):
        return adapter.place_call(text, name=name, voice=voice)
    return adapter.place_call(text, name=name)


def apply_voice(xml: str, voice) -> str:
    """Swap the voice on every <Say> we built (voice="man"). Unknown names = free voice, no change."""
    v = voice_of(voice)
    return xml if v == FREE_VOICE else xml.replace('<Say voice="man">', f'<Say voice="{v}" language="en-US">')


CALL_MAX_ENV = "BW_CALL_MAX_SECONDS"
CALL_MAX_DEFAULT = 1800       # hard stop: Twilio hangs up any real alert/test call after 30 minutes (TimeLimit)
CALL_MAX_CEILING = 14400      # Twilio's own maximum (4 hours)


def call_max_seconds(env=None) -> int:
    """Twilio TimeLimit for every real call. Env BW_CALL_MAX_SECONDS, default 1800. Bad value = default."""
    raw = str((os.environ if env is None else env).get(CALL_MAX_ENV, "") or "").strip()
    try:
        n = int(raw) if raw else CALL_MAX_DEFAULT
    except ValueError:
        n = CALL_MAX_DEFAULT
    return n if 1 <= n <= CALL_MAX_CEILING else CALL_MAX_DEFAULT


class TwilioCallAdapter(CallAdapter):
    """EXPERIMENTAL. Places one voice call through the OWNER'S OWN Twilio account (they pay Twilio directly;
    Bridge Warden pays nothing). Secrets and numbers come from this computer's environment only and are never
    logged or shown. Missing setup = dry run. Only api.twilio.com, HTTPS, no redirects."""
    name = "twilio"
    real = True

    def __init__(self, env=None, sender=None):
        env = os.environ if env is None else env
        self._sid, self._tok, self._from, self._to = (str(env.get(k, "")).strip() for k in TWILIO_ENV)
        self._base = str(env.get("BW_CALL_URL", "")).strip()   # optional, https only (see call-worker/)
        self._link_key = str(env.get("BW_CALL_LINK_KEY", "")).strip()   # optional, same as the Worker's CALL_LINK_KEY
        self._voice = voice_of(env.get("BW_CALL_VOICE", ""))   # optional; default "man" = Twilio's free voice
        self._send = sender or net.request
        su = str(env.get("BW_CALL_STATUS_URL", "")).strip()   # optional, https only (MISSEDCALL)
        pu = urllib.parse.urlsplit(su) if su else None
        self._status_url = su if (pu and pu.scheme == "https" and pu.hostname and not pu.query and not pu.username
                                  and re.fullmatch(r"[A-Za-z0-9/_.-]{0,200}", pu.path or "")) else ""
        self._detect_machine = str(env.get("BW_CALL_DETECT_MACHINE", "")).strip().lower() in ("1", "on", "true", "yes")
        self._time_limit = call_max_seconds(env)   # hard max call length (Twilio TimeLimit), default 30 minutes

    def __repr__(self):
        return f"TwilioCallAdapter(ready={self.ready})"

    @property
    def ready(self) -> bool:
        if judge_acting():   # JUDGEFIX: a hosted judge never reaches Twilio (no call, no text, no read)
            return False
        return bool(SID.match(self._sid) and self._tok and E164.match(self._from) and E164.match(self._to))

    def place_call(self, text: str, name: str = "", voice=None) -> dict:
        """voice = this call's voice (VOICEPICK; checked again with voice_of, unknown = free); None = BW_CALL_VOICE.
        With a Worker it rides as &v= on the signed URL (covered by the link token / Twilio signature).
        name = the owner's preferred name for the greeting ("Hi Trey, ..."). Checked again here (clean_name);
        with a Worker it rides as &nm= on the signed /voice URL, so Twilio's signature covers it."""
        if not self.ready:
            return {"would": "call owner", "dialed": False, "cost": 0,
                    "note": ("Judge demo: no phone call is placed." if judge_acting() else
                             "Twilio is not set up on this computer, so this was a dry run.")}
        lines = [x.strip() for x in re.split(r"(?<=[.?!])\s+(?=[A-Z])", text) if x.strip()][:30]
        v = self._voice if voice is None else voice_of(voice)
        base = call_base(self._base)
        if base:   # owner's own call Worker (BW_CALL_URL): it runs the press-or-say menu (CALL_SCRIPT_v3)
            nm = clean_name(name)
            plain = (text.replace(CALL_GREET_NAME.format(name=nm), CALL_GREET)
                     .replace(TEST_GREET_NAME.format(name=nm), TEST_GREET) if nm else text)   # name never picks the kind
            u = call_url(base, "voice", SAFE_END in text, 1, alert_kind(plain), name=nm,
                         voice="" if voice is None else v,   # no pick = no &v=, the Worker uses its CALL_VOICE
                         outside=OUTSIDE_LINE in text)       # OUTSIDE: alerts.py swapped in the PayPal-side line
            if self._link_key:   # LINKTOKEN: Twilio's trial proxy sends no signature header, so the URL carries one
                u = sign_link(u, self._link_key, self._to, self._sid)
            data = {"To": self._to, "From": self._from, "Url": u}
        else:      # no public address: the call only speaks; the owner chooses in the app
            data = {"To": self._to, "From": self._from, "Twiml": apply_voice(twiml(lines), v)}
        data["TimeLimit"] = str(self._time_limit)   # Twilio hangs up after this many seconds, whatever happens
        if self._status_url:   # MISSEDCALL: Twilio tells us how the call ended (signed; checked by alerts.py)
            data.update(StatusCallback=self._status_url, StatusCallbackMethod="POST")
        if self._detect_machine:   # optional, small extra Twilio fee: a voicemail pick-up counts as missed
            data["MachineDetection"] = "Enable"
        body = urllib.parse.urlencode(data).encode()
        auth = base64.b64encode(f"{self._sid}:{self._tok}".encode()).decode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls.json"
        try:
            code, _, raw = self._send("POST", url, {"Authorization": "Basic " + auth,
                                                  "Content-Type": "application/x-www-form-urlencoded"},
                                    body, 10, extra_host="api.twilio.com")
        except Exception as ex:
            return {"dialed": False, "error": scrub(str(ex), extra=[self._tok, self._sid, self._to, self._from,
                                                                    self._base, self._link_key, name])[:160]}
        ok = code in (200, 201)
        sid = _call_sid_of(raw) if ok else None
        return {"dialed": ok, "status": code, "cost": "billed to your own Twilio" if ok else 0,
                **({"call_sid": sid} if sid else {}),
                **({} if ok else {"error": f"Twilio said HTTP {code}"})}

    def call_status(self, call_sid: str):
        """MISSEDCALL fallback when Twilio cannot reach us: read how one call ended (a free API read).
        Returns {"status", "answered_by"} or None. Only our own call ids; nothing is logged."""
        if not self.ready or not CALL_SID.match(str(call_sid or "")):
            return None
        auth = base64.b64encode(f"{self._sid}:{self._tok}".encode()).decode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls/{call_sid}.json"
        try:
            code, _, raw = self._send("GET", url, {"Authorization": "Basic " + auth}, None, 10,
                                      extra_host="api.twilio.com")
            d = json.loads(raw or b"{}") if code == 200 else {}
        except Exception:
            return None
        st = str(d.get("status") or "")
        return {"status": st, "answered_by": str(d.get("answered_by") or "")} if re.fullmatch(r"[a-z-]{3,20}", st) else None

    def _get(self, path: str):
        auth = base64.b64encode(f"{self._sid}:{self._tok}".encode()).decode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/{path}"
        try:
            code, _, raw = self._send("GET", url, {"Authorization": "Basic " + auth}, None, 10,
                                      extra_host="api.twilio.com")
            return json.loads(raw or b"{}") if code == 200 else None
        except Exception:
            return None

    def call_usage(self, call_sid: str):
        """v6: what ONE call used, as Twilio reports it (free API read). Real numbers only:
        {"duration_seconds", "price", "price_unit"}; price is None until Twilio posts it. None if unknown."""
        if not self.ready or not CALL_SID.match(str(call_sid or "")):
            return None
        d = self._get(f"Calls/{call_sid}.json")
        if not isinstance(d, dict):
            return None
        num = lambda v: str(v) if v is not None and re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", str(v)) else None  # noqa: E731
        return {"duration_seconds": num(d.get("duration")), "price": num(d.get("price")),
                "price_unit": str(d.get("price_unit") or "")[:3].upper() or None}

    def balance(self):
        """v6: your Twilio balance, as Twilio reports it (Balance.json, free read). {"balance", "currency"} or None."""
        if not self.ready:
            return None
        d = self._get("Balance.json")
        if not isinstance(d, dict) or not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", str(d.get("balance", ""))):
            return None
        return {"balance": str(d["balance"]), "currency": str(d.get("currency") or "")[:3].upper()}


def usage_text(use, bal) -> str:
    """v6: one line under a call. Only Twilio's own numbers; never an estimate."""
    if not use:
        bits = ["no cost posted yet by Twilio"]
    else:
        bits = [f"{use['duration_seconds']} seconds" if use.get("duration_seconds") else "duration not posted yet",
                (f"cost {use['price'].lstrip('-')} {use.get('price_unit') or ''} (from Twilio)".strip()
                 if use.get("price") else "cost not posted yet by Twilio")]
    bits.append(f"Twilio balance {bal['balance']} {bal['currency']} (from Twilio)" if bal else
                "remaining balance: limit not available from provider")
    return "Call usage: " + ", ".join(bits) + "."


def _call_sid_of(raw):
    try:
        sid = str((json.loads(raw or b"{}") or {}).get("sid") or "")
    except Exception:
        return None
    return sid if CALL_SID.match(sid) else None


ADAPTERS = {"dry_run": DryRunCallAdapter, "twilio": TwilioCallAdapter}


def call_adapter(cfg: dict, env=None, sender=None, force=False):
    """The configured adapter, or None when call-on-fraud is off. force=True (Test my alert) always returns one:
    dry run unless the owner opted in to the experimental Twilio adapter."""
    c = (cfg or {}).get("call_on_fraud") or {}
    if not c.get("enabled") and not force:
        return None
    if c.get("enabled") and c.get("provider") == "twilio" and c.get("experimental"):
        return TwilioCallAdapter(env=env, sender=sender)
    return DryRunCallAdapter()


def saved_voice(gate, env=None):
    """The owner's saved call voice (allow-listed), read fresh from policy.json so a Settings change reaches the
    next real call without a restart; else the loaded policy. None = no pick: the adapter keeps the server default
    (BW_CALL_VOICE inline, or the Worker's CALL_VOICE: no &v= on the link)."""
    saved = None
    try:
        info = getattr(gate, "policy_info", None) or {}
        path = info.get("path")
        if path and os.path.basename(str(path)) != "policy.example.json":
            with open(path, encoding="utf-8") as f:
                saved = (json.load(f) or {}).get("call_voice")
    except Exception:
        saved = None
    if saved is None:
        try:
            saved = gate.engine.p.get("call_voice")
        except Exception:
            saved = None
    return voice_of(saved) if str(saved or "").strip() else None


def dev_locked(gate) -> bool:
    """Dev mode (test only): no real calls or pushes. Calls fall back to the dry-run adapter."""
    f = getattr(gate, "dev_lock", None)
    try:
        return bool(f()) if callable(f) else False
    except Exception:
        return True   # can't tell: stay on the safe side


def log_call(gate, adapter, res: dict, test: bool, for_action: str | None = None):
    """Signed audit line. Never contains phone numbers, tokens or account ids. Carries the Twilio call id
    (CA + 32 hex, E2EFIX 2026-10-27) when there is one, so a call can be matched to Twilio's own record."""
    ev = ("alert_test_call" if test else ("call_placed" if res.get("dialed") else "would_call_owner"))
    note = ("TEST: " if test else "") + ("call placed to your phone" if res.get("dialed") else
                                        (res.get("error") or res.get("note") or "dry run: no call was made"))
    sid = str(res.get("call_sid") or "")
    extra = {"call_sid": sid} if CALL_SID.match(sid) else {}
    if for_action:
        extra["for_action"] = str(for_action)[:90]
    gate.audit.write(ev, action_id="-", channel="call_on_fraud", provider=adapter.name, label="TEST" if test else "",
                     dialed=bool(res.get("dialed")), note=note, **extra)


DRILL_MINUTES = 15
TEST_NOTICE = "This was a test. Nothing happened to your money. " + TEST_CALL_TEXT
MENU = ("What do you want me to do? Press 1 to keep everything blocked. Press 2 to hear how to lock your PayPal. "
        "Press 3 if you are fine.")
CHOICES = {"1": "keep_blocked", "2": "lock_help", "3": "fine"}
LOCK_STEPS = (
    "Open the PayPal app or paypal.com yourself. Do not use links from texts or emails.",
    "Change your PayPal password.",
    "Turn on two-step login (a code on your phone).",
    "In Security settings, log out of all devices you don't know.",
    "Check Payments, Automatic payments: cancel anything you don't know.",
    "Still worried? Contact PayPal from the Help page inside the app. Bridge Warden can't lock PayPal for you.",
)
DRILL_EVENT = {"label": "TEST", "kind": "blocked payment", "amount": "480.00", "currency": "USD",
               "payee": "payee A (new, never paid before)", "note": "gift cards, urgent, keep it secret",
               "result": "blocked, nothing was sent"}
DRILL_ASK = ("TEST DRILL. Act exactly as if this were a real fraud event, so the person learns the real flow. "
             "In 2 short sentences say what happened. Do not ask a question; the app will ask for their choice.")
LOCAL_WHAT = ("Bridge Warden stopped a 480 dollar payment to someone you have never paid. The note asked for gift "
              "cards and secrecy, which is how scams work. Nothing was sent.")
REAL_WHAT = "Bridge Warden blocked a payment that looks like fraud. Nothing was sent."


def call_lines(what: str, test: bool, name: str = "") -> list:
    """What the voice says (CALL_SCRIPT_v5: greets the owner by preferred name if set). Test calls always END with the test notice, so nobody is left alarmed.
    `what` (the AI or local words) is shown in the app; the call itself keeps to the short fixed script."""
    lines = [call_open(name, test), CALL_ADVICE, CALL_MENU, CALL_APP_LINE]
    return lines + ([TEST_NOTICE] if test else [])


def menu_reply(choice: str, test: bool) -> list:
    """Spoken answer to a phone choice (needs the owner's own callback, see README). Advice only:
    the phone can keep things blocked or explain; it never approves or sends money."""
    c = CHOICES.get(str(choice), str(choice))
    say = {"keep_blocked": ["Okay. Everything stays blocked until you say otherwise in the app."],
           "lock_help": ["Here is how to lock your PayPal."] + list(LOCK_STEPS),
           "fine": ["Okay. The payment stays blocked. Nothing was sent. You can review it in the app."]}.get(
        c, ["Sorry, I did not get that. Everything stays blocked."])
    return say + ([TEST_NOTICE] if test else [])


def twiml(lines: list, gather_url: str | None = None) -> str:
    """TwiML for the call. With no callback URL (the default: Bridge Warden only listens on this computer)
    the menu is read out and the choice is made in the app."""
    say = lambda t: f'<Say voice="man">{_xml(t[:600])}</Say>'   # noqa: E731
    if gather_url and gather_url.startswith("https://"):
        head, menu, rest = lines[0], lines[1], lines[2:]
        return (f'<Response>{say(head)}<Gather input="dtmf speech" numDigits="1" timeout="8" speechTimeout="auto" '
                f'hints="{HINTS}" language="en-US" action="{_xml(gather_url)}" method="POST">{say(menu)}</Gather>'
                f'{"".join(say(x) for x in rest)}</Response>')
    return "<Response>" + "".join(say(x) for x in lines) + "</Response>"


# ---------------------------------------------------------------- press-or-say menu (CALL_SCRIPT_v3, 2026-10-26)
# The SAME words, mapping and steps live in call-worker/src/index.js (the owner's own Cloudflare Worker that
# Twilio posts the keypress or speech to). Shared test cases: call-worker/test/vectors.json.
# Option 4 is "other": the caller says what they need and the bot answers. It never claims a human is on the line.
CALL_GREET = "Hi, this is Bridge Warden."
CALL_GREET_NAME = "Hi {name}, this is Bridge Warden."
CALL_OPEN_REST = "Fraud was detected on your PayPal account. Nothing was sent."
CALL_OPEN = CALL_GREET + " " + CALL_OPEN_REST       # no name set: the plain greeting
# OUTSIDE 2026-10-27 (mirrors the Worker): a PayPal-side event, money may have moved. Same text as alerts.OUTSIDE_LINE.
OUTSIDE_LINE = "This happened in PayPal itself, so money may have moved. Check PayPal now."
# TESTGREET 2026-10-26 (Trey): TEST calls never use the owner's preferred name (judges must not hear "Trey").
# The tester may type a name on the Test my alert form, used for that one call only, never logged or stored.
TEST_GREET = "Hello, this is Bridge Warden."
TEST_GREET_NAME = "Hello {name}, this is Bridge Warden."
NAME_MAX = 40
NAME_OK = re.compile(r"[A-Za-z][A-Za-z' -]*")


def clean_name(s) -> str:
    """Preferred name for the call greeting: letters, spaces, hyphens, apostrophes; starts with a letter;
    at most 40. Anything else gives "" (the plain greeting). Same rule as cleanName() in the Worker."""
    t = re.sub(r" {2,}", " ", str(s if s is not None else "").strip(" "))
    return t if len(t) <= NAME_MAX and NAME_OK.fullmatch(t) else ""


def call_open(name: str = "", test: bool = False, outside: bool = False) -> str:
    """Real alert: "Hi <preferred name>, ...". test=True: "Hello <name typed on the test form>, ..." or "Hello, ..."."""
    c = clean_name(name)
    g, gn = (TEST_GREET, TEST_GREET_NAME) if test else (CALL_GREET, CALL_GREET_NAME)
    rest = CALL_OPEN_REST.replace("Nothing was sent.", OUTSIDE_LINE) if outside else CALL_OPEN_REST
    return (gn.format(name=c) if c else g) + " " + rest
CALL_ADVICE = "We recommend you check your recent activity and lock your account."
CALL_MENU = ("Press or say 1 for help securing your account. Press or say 2 to report this activity to PayPal. "
             "Press or say 3 if this was you. Press 4 or say other.")
CALL_APP_LINE = "You can also choose in your Bridge Warden app."
CALL_REPLIES = {
    "1": ["Okay. The steps are on your screen now.",
          "First, open PayPal yourself, not from a link, and change your password."],
    "2": ["Okay. Your report is ready in the app.", "Check it, then send it to PayPal yourself."],
    "3": ["Okay. Thanks for checking.", "The payment stays on hold until you approve it in the app."],
}
CALL_CHOICES = {"1": "secure", "2": "report", "3": "was_me", "4": "other"}
OTHER_ASK = "Okay. In a few words, tell me what you need."
OTHER_FALLBACK = ("I can help you secure your account, report this activity, or check if this was you. "
                  "Here is the menu again.")
NOT_HEARD = "Sorry, I did not get that. Here is the menu again."
NO_CHOICE = "No problem. Everything stays on hold. You can choose in the app."
SAFE_END = "This was a test. Nothing happened to your money."
HINTS = "one, two, three, four, help, secure, report, me, it was me, other, something else"
_NUM = {"1": "1", "one": "1", "2": "2", "two": "2", "3": "3", "three": "3", "4": "4", "four": "4"}
_SOLO = {"won": "1", "to": "2", "too": "2", "tree": "3", "for": "4", "fore": "4"}   # whole answer only
_PHRASES = (("was me", "3"), ("was i", "3"), ("something else", "4"))
_WORDS = {"help": "1", "secure": "1", "securing": "1", "lock": "1", "report": "2", "reporting": "2", "other": "4"}
_WEAK = {"me": "3", "mine": "3"}   # counts only when nothing stronger was said ("help me" = 1)
# Ordinal words beat number words: "the second one" = 2, not 1. "last" = the last choice (4).
_ORD = {"first": "1", "1st": "1", "second": "2", "2nd": "2", "third": "3", "3rd": "3", "fourth": "4", "forth": "4",
        "4th": "4", "last": "4"}
_FILLER = ("just a second", "a second", "one second", "just a sec", "one sec")   # "hold on a second" is not a choice
DEMO_INTRO = "This is a Bridge Warden demo call. Nothing happens to your money."
# What PayPal says to do, per situation (Trey, 2026-10-26). Plain words from PayPal's own public help and policy
# pages, each step with its source page and the date read: paypal_steps.json (a data file, shared with the browser
# demo and the call Worker). Nothing added that a page does not say. Never a phone number in the call: always
# "use the number on paypal.com".
# The call TALKS THEM THROUGH it: one step, then "Press 1 or say done ..., 2 repeat, 3 skip", then the next step,
# then a short sum-up of what they did. Real calls (choice 1 or 2) and test calls use the same walk.
# TEST mode wraps it: "This was just a test. No action is needed." + "If this were real, ..." first.
PAYPAL_STEPS = json.loads((Path(__file__).with_name("paypal_steps.json")).read_text(encoding="utf-8"))
SITUATIONS = PAYPAL_STEPS["situations"]
WALK = PAYPAL_STEPS["walk"]
KIND_ALIASES = {"fraud": "unauthorized", "login": "takeover", "buy_sell": "scam_buy"}
TEST_JUST = "This was just a test. No action is needed."
IF_REAL = "If this were real, here is what you would do:"
WALK_STOP = "Okay. You can finish the rest later."
CHOICE_HEARD = {"1": "You chose 1, help securing your account.", "2": "You chose 2, report this activity.",
                "3": "You chose 3, this was you.", "4": "You chose 4, other."}
WALK_HINTS = "done, repeat, skip, one, two, three"
_HUMAN = re.compile(r"\b(human|person|agent|representative|operator|transfer|connect(ing)? you|someone)\b", re.I)
CLASSIFY_ASK = ("A caller on a fraud-alert phone menu said the words in caller_said. The menu is: 1 = help securing "
                "the account, 2 = report the activity to PayPal, 3 = this was me, 4 = something else. Reply with ONE "
                "digit 1-4, or 0 if unclear. Nothing else.")
OTHER_PROMPT = ("TEST phone menu for Bridge Warden, an app that blocks risky PayPal payments. The caller said the words "
                "in caller_said. Answer in at most 2 short, calm sentences. Advice only: open PayPal yourself (not from "
                "a link), change the password, check recent activity, use the Bridge Warden app. Never ask for "
                "passwords or codes. Never say a human or person will help or is on the line. Never approve or send money.")


def _clean(text) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split())


def match_choice(digits=None, speech=None):
    """Keypad first, then plain keyword matching (works offline). Returns '1'-'4' or None (unclear)."""
    d = str(digits or "").strip()[:1]
    if d in ("1", "2", "3", "4"):
        return d
    t = _clean(speech)
    if not t:
        return None
    if t in _SOLO:
        return _SOLO[t]
    padded = f" {t} "
    for f in _FILLER:
        padded = padded.replace(f" {f} ", " ")
    words = padded.split()
    ords = {_ORD[w] for w in words if w in _ORD}
    if ords:
        return ords.pop() if len(ords) == 1 else None
    found = {c for p, c in _PHRASES if f" {p} " in padded}
    found |= {_NUM.get(w) or _WORDS.get(w) for w in words if w in _NUM or w in _WORDS}
    if len(found) == 1:
        return found.pop()
    if found:
        return None                      # two different choices heard: ask again
    weak = {_WEAK[w] for w in words if w in _WEAK}
    return weak.pop() if len(weak) == 1 else None


def _ai_text(ai, said: str, ask: str) -> str:
    if ai is None or not hasattr(ai, "advise") or not said:
        return ""
    try:
        res = ai.advise({"label": "TEST", "caller_said": scrub(said)[:200]}, ask)
    except Exception:   # the call must never break
        return ""
    return str((res or {}).get("text") or "").strip()


def pick_choice(digits=None, speech=None, ai=None):
    """match_choice, then (optional) the xAI helper for unclear speech. The AI can only pick 1-4."""
    c = match_choice(digits, speech)
    if c or not _clean(speech):
        return c
    m = re.search(r"\b([1-4])\b", _ai_text(ai, _clean(speech), CLASSIFY_ASK))
    return m.group(1) if m else None


def call_base(url) -> str:
    """The owner's call Worker address, only if it is plain https (no query, no secrets). Else ''."""
    u = str(url or "").strip().rstrip("/")
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return ""
    ok = (p.scheme == "https" and re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]+)?", p.netloc or "")
          and re.fullmatch(r"(/[A-Za-z0-9._/-]*)?", p.path) and not p.query and not p.fragment)
    return u if ok else ""


def kind_of(kind) -> str:
    """The situation for the walk. Old names still work; unknown = unauthorized (a payment you did not make)."""
    k = KIND_ALIASES.get(kind, kind)
    return k if k in SITUATIONS else "unauthorized"


_KIND_WORDS = (   # first match wins; plain keywords, no AI
    ("limited", ("limited", "limitation", "limit")),
    ("takeover", ("login", "log in", "logged in", "sign in", "signed in", "new device", "password changed")),
    ("phishing", ("phishing", "spoof", "fake email", "fake text", "fake call", "suspicious email",
                  "suspicious message", "suspicious text")),
    ("risky_sell", ("chargeback", "overpaid", "overpayment", "buyer", "sold", "selling", "sell", "shipping label")),
    ("scam_buy", ("buy", "buying", "seller", "invoice", "money request", "purchase", "marketplace",
                  "friends and family")),
)


def alert_kind(text: str) -> str:
    """Pick the situation from the alert words."""
    t = f" {_clean(text)} "
    for k, words in _KIND_WORDS:
        if any(f" {w} " in t for w in words):
            return k
    return "unauthorized"


def call_url(base: str, step: str, test: bool, n: int = 1, kind: str = "unauthorized", name: str = "",
             voice: str = "", outside: bool = False) -> str:
    k, nm = kind_of(kind), (clean_name(name) if step == "voice" else "")
    v = voice_of(voice) if str(voice or "").strip() else ""   # VOICEPICK: &v= (allow-listed, else free "man")
    return (f"{base.rstrip('/')}/{step}?t={1 if test else 0}&n={n}" + ("" if k == "unauthorized" else f"&k={k}")
            + (f"&nm={urllib.parse.quote(nm, safe='')}" if nm else "") + (f"&v={v}" if v else "")
            + ("&o=1" if outside and step == "voice" else ""))


# LINKTOKEN 2026-10-26 (mirrors call-worker/src/index.js linkMessage / linkSig). Twilio's TRIAL proxy fetches the
# TwiML with NO X-Twilio-Signature, so the /voice URL carries e= (expiry) + s= (HMAC-SHA256, base64url) bound to
# the path, our query keys, To and AccountSid. Short-lived: ttl <= LINK_MAX_SECONDS.
LINK_KEYS = ("t", "n", "k", "i", "a", "x", "nm", "v", "o", "e")   # v = VOICEPICK call voice (signed too)
LINK_MAX_SECONDS = 1800


def link_message(path: str, query: str, to: str, account_sid: str) -> str:
    kv = sorted((k, v) for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True) if k in LINK_KEYS)
    return "\n".join(["bw-link-v1", path, "&".join(f"{k}={v}" for k, v in kv), to or "", account_sid or ""])


def sign_link(url: str, key: str, to: str, account_sid: str, now: float | None = None, ttl: int = 600) -> str:
    ttl = max(60, min(int(ttl), LINK_MAX_SECONDS))
    e = int((_time.time() if now is None else now) + ttl)
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k not in ("e", "s")] + [("e", str(e))]
    query = urllib.parse.urlencode(q, quote_via=urllib.parse.quote, safe="")
    mac = hmac.new(key.encode(), link_message(p.path, query, to, account_sid).encode(), hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, query + "&s=" + s, ""))


def walk_url(base: str, test: bool, kind: str, i: int, done: str, x: int) -> str:
    return f"{base.rstrip('/')}/walk?t={1 if test else 0}&k={kind_of(kind)}&i={i}&a={done}&x={x}"


def walk_choice(digits=None, speech=None):
    """In the walk: '1' done, '2' repeat, '3' skip, None = unclear. Keypad first, then words."""
    d = str(digits or "").strip()[:1]
    if d in ("1", "2", "3"):
        return d
    t = _clean(speech)
    if not t:
        return None
    if t in WALK["solo"]:
        return WALK["solo"][t]
    padded = f" {t} "
    if " say again " in padded or " one more time " in padded:
        return "2"
    found = {WALK["num"].get(w) or WALK["words"].get(w) for w in t.split() if w in WALK["num"] or w in WALK["words"]}
    return found.pop() if len(found) == 1 else None


def walk_state(kind, i, done, x) -> tuple:
    """Clean up the walk state from the URL: i = step index, done = 'd'/'s' per finished step, x = repeats."""
    steps = SITUATIONS[kind_of(kind)]["steps"]
    try:
        i = max(0, min(int(i), len(steps)))
    except (TypeError, ValueError):
        i = 0
    done = "".join(c for c in str(done or "") if c in "ds")[:i]
    done += "s" * (i - len(done))
    try:
        x = max(0, min(int(x), 9))
    except (TypeError, ValueError):
        x = 0
    return kind_of(kind), i, done, x


def walk_step(kind, i, done, x, digits=None, speech=None) -> dict:
    """One answer in the walk -> the next state. Returns {i, done, x, lead: [lines], finished: bool}.
    1/done = mark done, next. 3/skip = next. 2/repeat = same step again. Unclear = 'Sorry' + same step.
    After max_repeats on one step: move on (counts as skipped). Silence twice on one step: stop the walk."""
    kind, i, done, x = walk_state(kind, i, done, x)
    n = len(SITUATIONS[kind]["steps"])
    if i >= n:
        return {"i": i, "done": done, "x": 0, "lead": [], "finished": True}
    c = walk_choice(digits, speech)
    heard = bool(str(digits or "").strip() or _clean(speech))
    lead = []
    if c == "1":
        done, i, x = done + "d", i + 1, 0
    elif c == "3":
        done, i, x = done + "s", i + 1, 0
        lead = [WALK["skipped"]]
    elif not heard and x >= 1:
        return {"i": i, "done": done, "x": 0, "lead": [WALK_STOP], "finished": True}
    elif x >= WALK["max_repeats"]:
        done, i, x = done + "s", i + 1, 0
        lead = [WALK["move_on"]]
    else:
        x += 1
        lead = [] if c == "2" else [WALK["not_heard"]]
    return {"i": i, "done": done, "x": x, "lead": lead, "finished": i >= n}


def walk_say(kind, i) -> list:
    """What the call says for step i: 'Step 2 of 6.' + the step + the done/repeat/skip prompt."""
    steps = SITUATIONS[kind_of(kind)]["steps"]
    return [WALK["step"].format(n=i + 1, total=len(steps)), steps[i]["say"], WALK["prompt"]]


def walk_summary(kind, done) -> list:
    """The sum-up at the end: what they did, and what they skipped."""
    steps = SITUATIONS[kind_of(kind)]["steps"]
    did = [steps[j]["short"] for j, c in enumerate(done) if c == "d"]
    skip = [steps[j]["short"] for j, c in enumerate(done) if c == "s"]
    out = [WALK["summary_lead"]]
    out.append(WALK["summary_done"].format(list=", ".join(did)) if did else WALK["summary_none"])
    if skip:
        out.append(WALK["summary_skipped"].format(list=", ".join(skip)))
    return out


def walk_end_lines(kind, done, test: bool) -> list:
    return walk_summary(kind, done) + ([] if test else [WALK["real_end"]])


WALK_INTRO = "I will take you through it one step at a time."
WALK_ABOUT = "This is about: {name}."


def walk_lead(kind, test: bool, choice=None) -> list:
    """What the call says just before step 1.
    TEST: (you chose ...) + 'This was just a test. No action is needed.' + 'If this were real, ...'.
    REAL: the short reply for 1 or 2 + 'I will walk you through what PayPal says to do.'"""
    about = [WALK_ABOUT.format(name=SITUATIONS[kind_of(kind)]["name"].lower()), WALK_INTRO]
    if test:
        return ([CHOICE_HEARD[choice]] if choice in CHOICE_HEARD else []) + [TEST_JUST, IF_REAL] + about
    return ([CALL_REPLIES[choice][0]] if choice in ("1", "2") else []) + [WALK["lead_real"]] + about


def _say(t: str) -> str:
    return f'<Say voice="man">{_xml(str(t)[:600])}</Say>'


def _gather(action: str, inner: list, speech_only: bool = False, hints: str = HINTS) -> str:
    kind = 'input="speech" timeout="6"' if speech_only else 'input="dtmf speech" numDigits="1" timeout="8"'
    return (f'<Gather {kind} speechTimeout="auto" hints="{hints}" language="en-US" action="{_xml(action)}" '
            f'method="POST">{"".join(_say(x) for x in inner)}</Gather>')


def _menu_again(base: str, test: bool, n: int, lead: str, kind: str = "unauthorized") -> str:
    """Repeat the menu ONCE (n=1 -> 2). On the second miss: the safe end (test: plus 'just a test')."""
    if n >= 2:
        return _end([NO_CHOICE] + ([TEST_JUST] if test else []), test)
    nxt = call_url(base, "gather", test, 2, kind)
    return (f"<Response>{_say(lead)}{_gather(nxt, [CALL_MENU])}"
            f'<Redirect method="POST">{_xml(nxt)}</Redirect></Response>')


def _end(lines: list, test: bool) -> str:
    return "<Response>" + "".join(_say(x) for x in lines + ([SAFE_END] if test else [])) + "<Hangup/></Response>"


def _ask_other(base: str, test: bool, n: int, kind: str) -> str:
    nxt = call_url(base, "other", test, n, kind)
    return (f"<Response>{_gather(nxt, [OTHER_ASK], speech_only=True)}"
            f'<Redirect method="POST">{_xml(nxt)}</Redirect></Response>')


def _walk_twiml(base: str, test: bool, kind: str, i: int, done: str, x: int, lead: list) -> str:
    """Say the lead lines, then step i inside a Gather (press or say done / repeat / skip).
    No answer -> /walk with nothing (= say it again once, then stop)."""
    nxt = walk_url(base, test, kind, i, done, x)
    return (f"<Response>{''.join(_say(t) for t in lead)}{_gather(nxt, walk_say(kind, i), hints=WALK_HINTS)}"
            f'<Redirect method="POST">{_xml(nxt)}</Redirect></Response>')


def start_walk(base: str, test: bool, kind: str, choice=None) -> str:
    return _walk_twiml(base, test, kind, 0, "", 0, walk_lead(kind, test, choice))


def walk_twiml(base: str, test: bool, kind: str, i=0, done="", x=0, digits=None, speech=None) -> str:
    """Step 4 (/walk): the answer to one step. Next step, the same step again, or the sum-up at the end."""
    st = walk_step(kind, i, done, x, digits, speech)
    if st["finished"]:
        return _end(st["lead"] + walk_end_lines(kind, st["done"], test), test)
    return _walk_twiml(base, test, kind, st["i"], st["done"], st["x"], st["lead"])


def voice_twiml(base: str, test: bool, demo: bool = False, kind: str = "unauthorized", name: str = "",
                outside: bool = False) -> str:
    """Step 1 (/voice): the script, then the press-or-say menu. No answer -> /gather with nothing (= ask again).
    demo=True (someone CALLED IN, /inbound on the Worker): says it is a demo first. Demo is always a TEST."""
    test = test or demo
    nxt = call_url(base, "gather", test, 1, kind)
    return (f"<Response>{_say(DEMO_INTRO) if demo else ''}{_say(call_open('' if demo else name, test, outside and not demo))}{_say(CALL_ADVICE)}"
            f'{_gather(nxt, [CALL_MENU])}<Redirect method="POST">{_xml(nxt)}</Redirect></Response>')


def gather_twiml(base: str, test: bool, n: int = 1, digits=None, speech=None, ai=None,
                 kind: str = "unauthorized") -> str:
    """Step 2 (/gather).
    TEST: 1-3 or anything said = 'This was just a test...' + the walk for this situation. 4 = asks what you
          need first. Silence = menu once more, then a safe end. No AI in a test.
    REAL: 1 or 2 = the walk (what PayPal says to do). 3 = 'thanks for checking'. 4 = 'what do you need'.
          Else repeat the menu once, then end safely."""
    if test:
        c = match_choice(digits, speech)
        if c == "4":
            return _ask_other(base, test, n, kind)
        if c or _clean(speech):
            return start_walk(base, test, kind, c)
        return _menu_again(base, test, n, NOT_HEARD, kind)
    c = pick_choice(digits, speech, ai)
    if c in ("1", "2"):
        return start_walk(base, test, kind, c)
    if c == "3":
        return _end(CALL_REPLIES[c], test)
    if c == "4":
        return _ask_other(base, test, n, kind)
    return _menu_again(base, test, n, NOT_HEARD, kind)


def other_twiml(base: str, test: bool, n: int = 1, speech=None, ai=None, kind: str = "unauthorized") -> str:
    """Step 3 (/other): the caller said what they need.
    TEST: always 'This was just a test...' + the walk (anything said, or nothing).
    REAL: a clear 1 or 2 = the walk, 3 = 'thanks for checking'; otherwise the bot answers (xAI, if set up) or
          explains what it can do, then offers the menu once more. Never claims a human is there."""
    c = match_choice(None, speech)
    if test:
        return start_walk(base, test, kind, c if c in ("1", "2", "3") else None)
    if c in ("1", "2"):
        return start_walk(base, test, kind, c)
    if c == "3":
        return _end(CALL_REPLIES[c], test)
    answer = _ai_text(ai, _clean(speech), OTHER_PROMPT) if c != "4" else ""
    if answer and not _HUMAN.search(answer):
        if n >= 2:
            return _end([answer[:300], NO_CHOICE], test)
        return _menu_again(base, test, n, answer[:300] + " To hear the menu again, stay on the line.", kind)
    return _menu_again(base, test, n, OTHER_FALLBACK, kind)


def call_demo_data() -> dict:
    """The ONE source for the in-browser 'Hear the call' demo (web.py embeds it as JSON). Same words, word lists
    and PayPal steps as the phone call and the Worker, so they can't drift (tests check)."""
    return {"open": CALL_OPEN, "open_test": call_open("", test=True), "advice": CALL_ADVICE, "menu": CALL_MENU, "replies": CALL_REPLIES,
            "other_ask": OTHER_ASK, "other_fallback": OTHER_FALLBACK, "not_heard": NOT_HEARD,
            "no_choice": NO_CHOICE, "safe_end": SAFE_END, "demo_intro": DEMO_INTRO,
            "test_just": TEST_JUST, "if_real": IF_REAL, "heard": CHOICE_HEARD,
            "walk_intro": WALK_INTRO, "walk_about": WALK_ABOUT, "walk_stop": WALK_STOP,
            "situations": SITUATIONS, "walk": WALK, "kind_aliases": KIND_ALIASES,
            "num": _NUM, "solo": _SOLO, "phrases": [list(x) for x in _PHRASES], "words": _WORDS, "weak": _WEAK,
            "ord": _ORD, "filler": list(_FILLER)}


class FraudDrill:
    """'Test my alert' = a fraud drill. A clearly logged TEST of the real flow:
    1. one redacted xAI message marked TEST (or local words): "act as if this were real";
    2. drill mode: EVERY outgoing money action is held (never sent) until the drill ends; approvals wait too;
    3. red light + desktop alert, then (owner's own Twilio, experimental; else dry run) one unannounced call at a
       clock-rule delay (drill_call_delay, at most 20 min) that says what 'happened', asks what to do, and ends with "This was a test";
    4. the drill ends on the first choice in the app (with a clear "This was a test"), on "End drill",
       or by itself after 15 minutes. Nothing is ever sent to PayPal by the drill."""

    def __init__(self, gate, clock=None, timer=None, rng=None, env=None, sender=None, wall=None, name_fn=None,
                 voice_fn=None):
        import time as _t
        self.voice_fn = voice_fn   # () -> the owner's call voice for TEST calls (Settings); default: pick_voice(policy)
        self.name_fn = name_fn   # () -> preferred name (Settings); default: policy "preferred_name"
        self.gate, self.clock = gate, clock or _t.monotonic
        self.timer = timer or (lambda sec, fn: threading.Timer(sec, fn))
        self.rng = rng or random.SystemRandom()
        self.wall = wall or self._owner_now    # local wall clock for drill_call_delay
        self.env, self.sender = env, sender
        self.until = 0.0
        self.last_at = None
        self.test_id = 0
        self.what, self.what_by = LOCAL_WHAT, "local"
        self._call = None
        self._lock = threading.Lock()

    # state ------------------------------------------------------------
    def active(self) -> bool:
        if self.until and self.clock() >= self.until:
            self.end("expired")
        return self.clock() < self.until

    def hold_reason(self) -> str | None:
        return ("Fraud drill (TEST) running: every money action waits until the drill ends. Nothing is sent."
                if self.active() else None)

    def _owner_now(self) -> datetime:
        tz = (self.gate.engine.p.get("owner_timezone") if getattr(self.gate, "engine", None) else None)
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)) if tz else datetime.now()
        except Exception:
            return datetime.now()

    def pending(self) -> bool:
        """A test call is still waiting to ring (it can outlast the 15-minute drill)."""
        return self._call is not None

    def wait_left(self) -> int:
        if self.last_at is None:
            return 0
        return max(0, int(self.last_at + TEST_COOLDOWN - self.clock()))

    # actions ----------------------------------------------------------
    def start(self, by="owner (web)", judge_key: str = "", call_name: str = "", call_voice: str = "") -> dict:
        """judge_key: optional. If it matches the configured judge key, the call waits JUDGE_TEST_DELAY instead of
        the clock rule. The 20-minute cooldown applies to judges too (checked first).
        call_name: optional, typed on the Test my alert form ("What should the call call you?"). Cleaned with
        clean_name (else ""), used for this one call only: never logged, never in the audit, gone after the call.
        Test calls never fall back to the owner's preferred_name (TESTGREET).
        call_voice: optional, picked on the Test my alert form for THIS test call only (VOICEPICK: a judge's pick
        never changes the owner's saved voice). Unknown = free voice. Blank = the saved voice (voice_fn)."""
        if self.active() or self.wait_left() or self.pending():
            self.gate.audit.write("alert_test_refused", action_id="-", label="TEST", by=by,
                                  note=COOLDOWN_SAY)
            return {"started": False, "wait": self.wait_left()}
        adapter = call_adapter(self.gate.engine.p.get("notify", {}) or {}, env=self.env, sender=self.sender, force=True)
        if dev_locked(self.gate) or judge_acting():
            adapter = DryRunCallAdapter()   # Dev mode / hosted judge: the drill runs, but no phone rings
        judge = is_judge(judge_key, self.env)
        self.ai_judge_key = judge_key.strip() if judge else ""   # call replies count against this judge's xAI allowance
        if judge and getattr(adapter, "real", False) and getattr(adapter, "ready", False):
            # judges get at most JUDGE_CALL_CAP REAL calls per key; dry-run tests never count. The key is not logged.
            if not JudgeCalls(self.gate.audit.path.parent).take(judge_key):
                self.gate.audit.write("judge_cap_reached", action_id="-", label="TEST", by=by,
                                      cap=JUDGE_CALL_CAP, note="No call placed: demo test-call limit reached.")
                return {"started": False, "judge_cap": True, "wait": 0}
        ai = self._ask_ai()
        delay = test_call_delay(self.wall(), judge=judge)
        with self._lock:
            self.last_at, self.until = self.clock(), self.clock() + DRILL_MINUTES * 60
            self.test_id = self.rng.randint(1, 2**31)
        self.gate.audit.write("alert_test", action_id="-", label="TEST", by=by, provider=adapter.name,
                              minutes=DRILL_MINUTES, ai=ai, judge=judge,
                              note="Fraud drill started. Simulated suspicious event. No real payment. Nothing sent "
                                   "to PayPal. All money actions are held until the drill ends.")
        name = clean_name(call_name)      # NOT self.preferred_name(): judges never hear the owner's name
        voice = voice_of(call_voice) if str(call_voice or "").strip() else self.voice()
        text = " ".join(call_lines(self.what, test=True, name=name))
        tid = self.test_id

        def fire():
            with self._lock:
                if self.test_id != tid or self._call is None:   # drill already ended: don't ring
                    return
                self._call = None
            try:
                res = place(adapter, text, name=name, voice=voice)
            except Exception as ex:   # never break the app
                res = {"dialed": False, "error": str(ex)[:120]}
            log_call(self.gate, adapter, res, test=True)
            try:   # STATE CHECK: re-read PayPal + our log after test and judge calls too (no listening)
                from .callaudit import run as state_check
                state_check(self.gate, "after_test_call", env=self.env)
            except Exception:
                pass
        t = self.timer(delay, fire)
        if hasattr(t, "daemon"):
            t.daemon = True
        self._call = t
        t.start()
        return {"started": True, "provider": adapter.name, "real": bool(getattr(adapter, "ready", False)),
                "ai": ai.get("used", False)}

    def voice(self):
        """The owner's saved pick for test calls (voice_fn = the web app's Settings pick), None = server default."""
        try:
            v = self.voice_fn() if self.voice_fn else saved_voice(self.gate, self.env)
            return voice_of(v) if str(v or "").strip() else None
        except Exception:
            return FREE_VOICE

    def preferred_name(self) -> str:
        try:
            raw = self.name_fn() if self.name_fn else (self.gate.engine.p.get("preferred_name") or "")
        except Exception:
            raw = ""
        return clean_name(raw)

    def _ask_ai(self) -> dict:
        ai = getattr(self.gate, "ai", None)
        if ai is None or not hasattr(ai, "advise"):
            self.what, self.what_by = LOCAL_WHAT, "local"
            return {"used": False, "skipped": "no_ai"}
        try:
            res = ai.advise(dict(DRILL_EVENT), DRILL_ASK)
        except Exception as ex:
            res = {"called": False, "error": str(ex)[:120]}
        if res.get("text"):
            self.what, self.what_by = res["text"], "ai"
            return {"used": True, "usage": res.get("usage")}
        self.what, self.what_by = LOCAL_WHAT, "local"
        return {"used": False, "skipped": res.get("skipped") or res.get("error") or "no_text"}

    def end(self, why: str, by="owner (web)") -> bool:
        with self._lock:
            if not self.until:
                return False
            self.until = 0.0
            cancelled = self._call is not None and why != "expired"   # expiry keeps a pending test call
            if cancelled and hasattr(self._call, "cancel"):
                self._call.cancel()
            if cancelled:
                self._call = None
        self.gate.audit.write("alert_test_ended", action_id="-", label="TEST", by=by, why=why,
                              call_cancelled=cancelled,
                              note="This was a test. Nothing happened to your money. Held items stay held for you.")
        return True

    def choose(self, choice: str, by="owner (web)") -> dict:
        """The owner 'starts fixing it' in the app: log the choice, end the drill, say clearly it was a test."""
        self.gate.audit.write("alert_test_choice", action_id="-", label="TEST", by=by, choice=choice)
        self.end("owner chose: " + choice, by=by)
        return {"test_over": True}


AlertTest = FraudDrill   # earlier name


ALERT_POLL_SECONDS = 3.0      # real suspicious activity: noticed within ~3 s, then the call goes out at once


class Notifier:
    def __init__(self, gate, sender=None):
        cfg = gate.engine.p.get("notify", {}) or {}
        self.gate = gate
        self.url = cfg.get("webhook_url", "") if cfg.get("webhook_enabled") else ""
        self.sender = sender or net.request
        self.caller = call_adapter(cfg)
        self.last = None   # (waiting, blocked, seq) at the last check
        from . import alerts as A
        self.email = A.EmailAlerter()   # FREEALERTS: the owner's own mail server, off unless set up

    @property
    def enabled(self) -> bool:
        return bool(self.url) or self.caller is not None or bool(getattr(self.email, "ready", False))

    def alerts(self):
        from . import alerts as A
        return A.Alerts(self.gate, caller=self.caller, email=self.email)

    def _new_blocks(self, after_seq: int):
        """New real blocks since the last look that no one has alerted on yet (ACCTWATCH: an outside PayPal event
        is alerted the moment it arrives, so this loop must not ring a second time). [] = all handled already."""
        recs = self.gate.audit.records()
        done = {r.get("for_action") for r in recs if r.get("event") == "alert_raised"}
        new = [m for m in dashboard.moves(recs) if m["status"] == "blocked" and m["seq"] > after_seq and not m["test"]]
        if not new:
            return None   # can't tell which one: alert anyway
        return [m["action_id"] for m in new if m["action_id"] not in done and not str(m["action_id"]).startswith("pp-")]

    def tick(self):
        """MISSEDCALL: run any due call retries (persisted queue; safe after a restart)."""
        try:
            return self.alerts().tick()
        except Exception:
            return []

    def check(self) -> bool:
        """Push once when the number of things that need you goes up. Returns True if a push was sent."""
        st = dashboard.status(self.gate)
        now = (st["waiting"], st["blocked"], st["seq"])
        prev, self.last = self.last, now
        if not self.enabled or prev is None or st["state"] != "red":
            return False
        if st["waiting"] <= prev[0] and st["blocked"] <= prev[1]:
            return False
        dev = dev_locked(self.gate)
        fired = False
        if st["blocked"] > prev[1] and (self.caller is not None or getattr(self.email, "ready", False)):
            aids = self._new_blocks(prev[2])
            if aids is None:
                aids = [f"seq-{st['seq']}"]
            if aids:   # one alert for this step: call here at once (Dev mode: dry run), email in parallel
                self.alerts().fire(aids[0], source="gate")   # VOICEPICK voice + name are read fresh inside
                fired = True
        if self.url and dev:
            self.gate.audit.write("notify_skipped", action_id="-", channel="webhook", why="dev_mode")
            return False
        if not self.url:
            return fired
        body = ("A payment is waiting for your OK." if st["waiting"] > prev[0] else "A payment was blocked.").encode()
        try:
            code, _, _ = self.sender("POST", self.url, {"Title": TITLE, "Tags": "shield", "Content-Type": "text/plain"},
                                     body, 5, allow_loopback=True)
            self.gate.audit.write("notify_sent", action_id="-", channel="webhook", status=code)
            return True
        except (net.NetError, net.BlockedTarget) as ex:
            self.gate.audit.write("notify_failed", action_id="-", channel="webhook", error=str(ex)[:200])
            return False

    def start(self, every: float = None) -> threading.Event:
        """Real alerts: checked every ALERT_POLL_SECONDS and the call is placed right then (no random delay;
        the clock-rule / 93-second delays belong ONLY to FraudDrill, the 'Test my alert' button)."""
        every = ALERT_POLL_SECONDS if every is None else every
        stop = threading.Event()

        def loop():
            self.check()
            while not stop.wait(every):
                try:
                    self.check()
                    self.tick()
                except Exception:   # never let alerts break the gate
                    pass
        if self.enabled:
            threading.Thread(target=loop, daemon=True, name="bw-notify").start()
        return stop


# ---- RETENTION (2026-10-26): optional "forget my calls" cleanup ----------------------------------------------
# Twilio keeps a log of each call (numbers, time, length, status) in YOUR Twilio account. It keeps no audio unless
# recording is on, and Bridge Warden never turns recording on. This removes those call logs through Twilio's own
# documented API: DELETE /Calls/{CallSid}.json (https://www.twilio.com/docs/voice/api/call-resource#delete-a-call-resource).
# Only calls between YOUR Twilio number and YOUR phone are touched, only finished ones (Twilio refuses to delete a
# live call), and any recordings on them are deleted first (deleting a call does not delete its recordings).
# Nothing here prints or returns a number, token or account id: only counts.
CALL_SID = re.compile(r"^CA[0-9a-fA-F]{32}$")
REC_SID = re.compile(r"^RE[0-9a-fA-F]{32}$")
CALL_DONE = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})


def forget_calls(env=None, sender=None, dry_run: bool = False, rounds: int = 10) -> dict:
    """Delete the Twilio call logs (and any recordings) between your Twilio number and your phone.
    dry_run=True only counts. Returns {"ready", "found", "deleted", "recordings_deleted", "skipped_live", "errors"}."""
    env = os.environ if env is None else env
    sid, tok, frm, to = (str(env.get(k, "")).strip() for k in TWILIO_ENV)
    out = {"ready": False, "found": 0, "deleted": 0, "recordings_deleted": 0, "skipped_live": 0, "errors": 0}
    if not (SID.match(sid) and tok and E164.match(frm) and E164.match(to)):
        return out
    out["ready"] = True
    send = sender or net.request
    root = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
    hdr = {"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()}

    def call(method, path):
        try:
            code, _, raw = send(method, root + path, hdr, None, 15, extra_host="api.twilio.com")
        except Exception:
            return 0, {}
        try:
            return code, (json.loads(raw.decode() or "{}") if raw else {})
        except Exception:
            return code, {}

    seen, live = set(), set()
    for _ in range(max(1, rounds)):
        batch = []
        for a, b in ((frm, to), (to, frm)):   # calls out to you, and demo calls in from you
            q = urllib.parse.urlencode({"From": a, "To": b, "PageSize": 100})
            code, body = call("GET", f"/Calls.json?{q}")
            if code != 200:
                out["errors"] += 1
                continue
            batch += [c for c in (body.get("calls") or []) if CALL_SID.match(str(c.get("sid", "")))]
        todo = []
        for c in batch:
            s = c["sid"]
            if s in seen or s in live:
                continue
            if c.get("status") not in CALL_DONE:
                live.add(s)
                continue
            seen.add(s)
            todo.append(s)
        out["found"] += len(todo)
        if dry_run or not todo:
            break
        for s in todo:
            code, body = call("GET", f"/Calls/{s}/Recordings.json")
            for r in (body.get("recordings") or []) if code == 200 else []:
                rs = str(r.get("sid", ""))
                if REC_SID.match(rs):
                    rc, _ = call("DELETE", f"/Recordings/{rs}.json")
                    if rc == 204:
                        out["recordings_deleted"] += 1
                    else:
                        out["errors"] += 1
            code, _ = call("DELETE", f"/Calls/{s}.json")
            if code == 204:
                out["deleted"] += 1
            else:
                out["errors"] += 1
    out["skipped_live"] = len(live)
    return out
