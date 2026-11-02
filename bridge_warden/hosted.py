"""Bridge Warden on YOUR OWN Render service ("Deploy to Render" button, render.yaml at the repo root).

Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0 (see LICENSE).

What runs here: your own dashboard (Home, Money, History, Settings) and the real "Test my alert" phone call
through YOUR OWN Twilio account. The call menu (/voice, /gather, /other, /walk, /inbound) is served by this same
app, so no Cloudflare Worker is needed. Call logs live only in your Twilio account.

Safety (same rules as the local app, plus what a public address needs):
  * Starts only with BW_LOGIN_KEY (32+ characters; the Blueprint makes one with generateValue) and a public
    host name (RENDER_EXTERNAL_HOSTNAME, set by Render). Missing = refuses to start.
  * Answers only requests for that host. Login is a POST form (the key is never in a URL, so never in browser
    history or request logs). Wrong keys are rate limited. The session cookie is HttpOnly, SameSite=Strict, Secure.
  * POSTs must come from https://<that host>. HSTS on every reply.
  * Call paths answer ONLY a request signed by Twilio (X-Twilio-Signature with TWILIO_AUTH_TOKEN) or carrying
    a good short-lived link token (e= expiry + s= HMAC-SHA256 with BW_CALL_LINK_KEY, bound to the path, our
    query keys, the called number and your Account SID). Same checks and same words as call-worker/.
  * xAI (optional): only if XAI_API_KEY is set (Render dashboard, sync: false). Then transaction checks, help chats,
    the AG chat panel, summaries and call replies use it. Judges log in with their own judge key and get at most
    BW_JUDGE_XAI_CAP xAI messages each (default 1000, see judge_ai.py); after that they see sample answers.
    The key is never printed, logged or written to History. No XAI_API_KEY = no AI, as before.
  * Loosening a setting still needs a real terminal, which a hosted copy does not have,
    so on Render the page can only make things SAFER.
  * PayPal account events (2026-10-28, optional): POST /paypal-webhook takes PayPal SANDBOX webhooks. It is OFF
    (503 "not set up") until PAYPAL_CLIENT_ID, PAYPAL_SANDBOX_SECRET and BW_PAYPAL_WEBHOOK_ID are all set. No login
    (PayPal cannot log in), but every event gets acctwatch.py's own checks: 64 KB cap, all PAYPAL-* headers, a
    sandbox cert host, a 5 minute time window, a replay guard, and PayPal's verify-webhook-signature on the RAW
    body. Then the fixed rules, then (only if XAI_API_KEY is set) a stricter-only xAI second look on a scrubbed
    summary, then the same red light and alert (call / email) as everything else.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from . import judge_ai as JA
from . import notify as N

HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
CALL_STEPS = {"/voice": "voice", "/gather": "gather", "/other": "other", "/walk": "walk", "/inbound": "inbound"}
OUR_KEYS = {"t", "n", "k", "i", "a", "x", "nm", "e", "s", "bodySHA256"}   # same as the Worker
MIN_LOGIN_KEY = 32
MAX_CALL_BODY = 8192
PAYPAL_HOOK = "/paypal-webhook"
PAYPAL_ENV = ("PAYPAL_CLIENT_ID", "PAYPAL_SANDBOX_SECRET", "BW_PAYPAL_WEBHOOK_ID")
LOGIN_FAILS_PER_MINUTE = 10
HSTS = "max-age=31536000"
OPEN_PATHS = ("/assets/", "/robots.txt", "/hear", "/judges")   # /judges = Judge Guide (public)   # public anyway (also public in local mode)
SORRY = ("Sorry, something went wrong on this call. Nothing happened to your money. "
         "Please check the Bridge Warden app.")
ROOT = Path(__file__).resolve().parent.parent


class HostedRefused(SystemExit):
    pass


LOCK_ENV = "BW_SITE_LOCK_PASSWORD"   # private test copy: the WHOLE site needs this password (HTTP Basic, user "bw")
LOCK_USER = "bw"
MIN_LOCK_PASSWORD = 20
LOCK_OPEN = ("/healthz", "/robots.txt")   # health check ("ok") and robots.txt ("Disallow: /") need no password
LOCK_REALM = 'Basic realm="Bridge Warden (private)", charset="UTF-8"'
LOCK_ROBOTS = "noindex, nofollow, noarchive"
LOCK_ROBOTS_TXT = "User-agent: *\nDisallow: /\n"      # locked copy: no crawler may read anything
LOCK_META = '<meta name="robots" content="noindex, nofollow">'


def site_lock(env) -> str:
    """The site lock password, or "" when the lock is off. Too short = refused (never echoed)."""
    pw = str(env.get(LOCK_ENV, "") or "").strip()
    if pw and len(pw) < MIN_LOCK_PASSWORD:
        raise HostedRefused(f"Hosted mode refused: {LOCK_ENV} is set but shorter than {MIN_LOCK_PASSWORD} characters.")
    return pw


def lock_ok(header: str, password: str) -> bool:
    """HTTP Basic check for the site lock. Constant-time on both the user and the password. Never logs either."""
    import base64
    import binascii
    scheme, _, b64 = str(header or "").strip().partition(" ")
    if scheme.lower() != "basic" or not b64:
        return False
    try:
        raw = base64.b64decode(b64.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    user, sep, given = raw.partition(":")
    ok_user = hmac.compare_digest(user.encode(), LOCK_USER.encode())
    ok_pw = hmac.compare_digest(given.encode(), password.encode())
    return bool(sep) and ok_user and ok_pw


def hosted_settings(env) -> dict:
    """Read and check the hosted settings. Never returns or prints secret values in an error."""
    host = str(env.get("BW_PUBLIC_HOST") or env.get("RENDER_EXTERNAL_HOSTNAME") or "").strip().lower()
    if not HOST_RE.match(host):
        raise HostedRefused("Hosted mode refused: no public host name. Render sets RENDER_EXTERNAL_HOSTNAME for you; "
                            "for your own domain set BW_PUBLIC_HOST (like bridge-warden.example.com).")
    key = str(env.get("BW_LOGIN_KEY", "")).strip()
    if len(key) < MIN_LOGIN_KEY:
        raise HostedRefused(f"Hosted mode refused: BW_LOGIN_KEY must be set and at least {MIN_LOGIN_KEY} characters "
                            "(the Render Blueprint makes one for you).")
    return {"host": host, "login_key": key, "link_key": str(env.get("BW_CALL_LINK_KEY", "")).strip(),
            "auth_token": str(env.get("TWILIO_AUTH_TOKEN", "")).strip(),
            "data": Path(str(env.get("BW_DATA_DIR", "") or "bw-data")).expanduser()}


FREE_BANNER = ('<p class="msg warn free-note" role="note"><b>Free Render copy.</b> Your history is erased when this '
               'service sleeps or restarts. Download your proof often (History page).</p>')


def free_plan(env, data) -> bool:
    """E2EFIX: True on Render's free plan (no lasting disk). BW_FREE_PLAN=on/off decides; unset = free unless
    the data folder is an absolute path (a paid disk, like /var/data)."""
    v = str(env.get("BW_FREE_PLAN", "")).strip().lower()
    if v in ("on", "1", "yes", "true"):
        return True
    if v in ("off", "0", "no", "false"):
        return False
    p = Path(str(data))
    return not (p.is_absolute() or p.root)   # '/var/data' has a root but no drive on Windows


def with_free_banner(html_text: str) -> str:
    marker = '<main id="main" class="wrap" tabindex="-1">'
    return html_text.replace(marker, marker + FREE_BANNER, 1) if marker in html_text else FREE_BANNER + html_text


def prepare_policy(data: Path, env) -> Path:
    """Your policy.json in the data folder. Made ONCE from policy.example.json (never overwritten after that):
    your preferred name, and the real Twilio call switched on only if your Twilio settings are all there."""
    data.mkdir(parents=True, exist_ok=True)
    path = data / "policy.json"
    if path.exists():
        return path
    pol = json.loads((ROOT / "policy.example.json").read_text(encoding="utf-8"))
    name = N.clean_name(env.get("BW_PREFERRED_NAME", ""))
    if name:
        pol["preferred_name"] = name
    if N.TwilioCallAdapter(env=env).ready:
        pol.setdefault("notify", {})["call_on_fraud"] = {"enabled": True, "provider": "twilio", "experimental": True}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pol, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---- call checks (mirror call-worker/src/index.js) ------------------------------------------------------------
def twilio_signature(token: str, url: str, params: dict) -> str:
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def url_forms(raw: str) -> list:
    out = [raw]
    m = re.match(r"^(https://)([^/?#:]+)(:443)?(/[^?#]*)?(\?[^#]*)?$", raw)
    if not m:
        return out
    sch, host, _, path, query = m.group(1), m.group(2), m.group(3), m.group(4) or "/", m.group(5) or ""
    kept = [kv for kv in query[1:].split("&") if kv and urllib.parse.unquote(kv.split("=")[0]) in OUR_KEYS] if query else []
    q2 = ("?" + "&".join(kept)) if kept else ""
    for port in ("", ":443"):
        for u in (sch + host + port + path + query, sch + host + port + path + q2):
            if u not in out:
                out.append(u)
    return out


def check_twilio(token: str, url: str, params: dict, given: str) -> bool:
    if not token or not given:
        return False
    return any(hmac.compare_digest(twilio_signature(token, u, params), given) for u in url_forms(url))


def link_sig(key: str, path: str, query: str, to: str, sid: str) -> str:
    mac = hmac.new(key.encode(), N.link_message(path, query, to, sid).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def check_link(key: str, path: str, query: str, params: dict, now: float | None = None):
    """(ok, e). e = the link's expiry, reused for every follow-up link so a call can't outlive it."""
    if not key:
        return False, 0
    q = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    s, e_raw = q.get("s", ""), q.get("e", "")
    if not s or not re.fullmatch(r"[0-9]{1,12}", e_raw):
        return False, 0
    e, now = int(e_raw), int(time.time() if now is None else now)
    if e < now or e > now + N.LINK_MAX_SECONDS:
        return False, 0
    want = link_sig(key, path, query, params.get("To", ""), params.get("AccountSid", ""))
    return (True, e) if hmac.compare_digest(want, s) else (False, 0)


def sign_links(body: str, base: str, key: str, e: int, params: dict) -> str:
    """Sign every link to this app inside our TwiML (Gather action, Redirect) with the same expiry e."""
    pat = re.compile(re.escape(base.rstrip("/")) + r"/(?:voice|gather|other|walk)\?[^\"<\s]*")

    def one(m):
        u = urllib.parse.urlsplit(m.group(0).replace("&amp;", "&"))
        q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if k not in ("e", "s")]
        query = urllib.parse.urlencode(q + [("e", str(e))], quote_via=urllib.parse.quote, safe="")
        s = link_sig(key, u.path, query, params.get("To", ""), params.get("AccountSid", ""))
        return N._xml(urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, query + "&s=" + s, "")))
    return pat.sub(one, body)


def carry_voice(body: str, base: str, v: str) -> str:
    """VOICEPICK: every follow-up link to this app keeps the call's &v= (signed afterwards). Mirrors carryVoice."""
    pat = re.compile(re.escape(base.rstrip("/")) + r"/(?:voice|gather|other|walk)\?[^\"<\s]*")
    return pat.sub(lambda m: m.group(0) if re.search(r"[?&](amp;)?v=", m.group(0)) else m.group(0) + "&amp;v=" + v, body)


def call_twiml(step: str, base: str, query: str, params: dict, ai=None) -> str:
    """The TwiML for one call step. Same routing as the Worker. ai: optional xAI helper for unclear speech
    (only when XAI_API_KEY is set; it can only pick menu choice 1-4)."""
    q = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    test = q.get("t") != "0"
    n = 2 if q.get("n") == "2" else 1
    kind = N.kind_of(q.get("k") or "unauthorized")
    if step == "inbound":
        return N.voice_twiml(base, True, True, kind)
    if step == "voice":
        return N.voice_twiml(base, test, False, kind, N.clean_name(q.get("nm", "")), q.get("o") == "1")
    if step == "walk":
        return N.walk_twiml(base, test, kind, q.get("i"), q.get("a"), q.get("x"),
                            params.get("Digits"), params.get("SpeechResult"))
    if step == "gather":
        return N.gather_twiml(base, test, n, params.get("Digits"), params.get("SpeechResult"), ai, kind)
    return N.other_twiml(base, test, n, params.get("SpeechResult"), ai, kind)


def answer_call(cfg: dict, env, path: str, query: str, params: dict, signature: str, now: float | None = None,
                ai=None):
    """(status, body, ctype). Refuses (403) anything not signed by Twilio and without a good link token."""
    step = CALL_STEPS.get(path)
    if step is None:
        return 404, "not found\n", "text/plain; charset=utf-8"
    base = "https://" + cfg["host"]
    full = base + path + (("?" + query) if query else "")
    ok = check_twilio(cfg["auth_token"], full, params, signature)
    e = 0
    if not ok:
        ok, e = check_link(cfg["link_key"], path, query, params, now)
    if not ok:
        return 403, ("not set up\n" if not cfg["auth_token"] and not cfg["link_key"] else "forbidden\n"), \
            "text/plain; charset=utf-8"
    qv = dict(urllib.parse.parse_qsl(query, keep_blank_values=True)).get("v", "")
    voice = N.voice_of(qv) if qv else env.get("BW_CALL_VOICE", "")   # VOICEPICK: signed &v= wins; unknown = free
    try:
        body = call_twiml(step, base, query, params, ai)
        if qv:
            body = carry_voice(body, base, N.voice_of(qv))
        if cfg["link_key"]:
            body = sign_links(body, base, cfg["link_key"], e or int((time.time() if now is None else now) + 900), params)
    except Exception:
        body = f"<Response>{N._say(SORRY)}<Hangup/></Response>"
    return 200, '<?xml version="1.0" encoding="UTF-8"?>' + N.apply_voice(body, voice), "text/xml; charset=utf-8"


def call_status(cfg: dict, gate, params: dict, signature: str) -> int:
    """MISSEDCALL: Twilio's StatusCallback. Refused (403) unless Twilio signed it with YOUR auth token. 204 = taken.
    Only the call id, status and answered-by are read; nothing else from the request is kept."""
    from . import alerts as AL
    if not AL.twilio_signature_ok(cfg.get("auth_token", ""), "https://" + cfg["host"] + "/call-status", params,
                                  signature):
        return 403
    sid = str(params.get("CallSid", ""))
    if not AL.CALL_SID.match(sid):
        return 400
    AL.Alerts(gate).on_status(call_sid=sid, status=params.get("CallStatus", ""),
                              answered_by=params.get("AnsweredBy", ""))
    return 204


# ---- login -----------------------------------------------------------------------------------------------------
class LoginGuard:
    """Constant-time key check, plus a soft limit on wrong tries (the key itself is 256-bit random)."""

    def __init__(self, key: str, clock=time.monotonic):
        self.key, self.clock, self.fails, self.lock = key, clock, [], threading.Lock()

    def check(self, given: str, is_judge=None) -> str:
        """'ok' (owner key), 'judge' (one of the judge keys, if is_judge is given), 'bad' or 'slow'."""
        with self.lock:
            now = self.clock()
            self.fails = [t for t in self.fails if t > now - 60]
            if len(self.fails) >= LOGIN_FAILS_PER_MINUTE:
                return "slow"
            if given and hmac.compare_digest(given.encode(), self.key.encode()):
                return "ok"
            if given and is_judge is not None and is_judge(given):
                return "judge"
            self.fails.append(now)
            return "bad"


LOCAL_FOOTER = "Runs only on this computer."          # web.page() footer, true only for a local copy
HOSTED_FOOTER = "Runs on its own Render service."       # same words as web.py's Judge Guide footer


LOGIN_BODY = ("<h1>Log in</h1><p>Paste your login key. Find it in your Render dashboard: your Bridge Warden service, "
              "then <b>Environment</b>, then <b>BW_LOGIN_KEY</b>. Keep it secret.</p>"
              "<p>Judges: paste your judge key here.</p>"
              '<form method="post" action="/login"><p><label for="k">Login key</label></p>'
              '<p><input id="k" name="k" type="password" autocomplete="current-password" required></p>'
              '<p><button type="submit">Log in</button></p></form>'
              '<p>Judging? Read the <a href="/judges">Judge Guide</a> first.</p>')


ZDR_ENV = "XAI_ZDR_CONFIRMED"     # "1" = the owner confirmed Zero Data Retention on their xAI team (checked per call too)
JUDGE_SESSIONS_MAX = 500


def hosted_ai(gate, env, transport=None):
    """The xAI checker for a hosted copy, or None when XAI_API_KEY is not set. The key is read from env only and is
    never printed or logged (XaiChecker scrubs it from every error)."""
    key = str(env.get("XAI_API_KEY", "") or "").strip()
    cfg = dict(gate.engine.p.get("xai") or {})
    if not key or not cfg.get("enabled", True):
        return None
    from .xai_check import XaiChecker
    if str(env.get(ZDR_ENV, "")).strip().lower() in ("1", "on", "yes", "true"):
        cfg["owner_confirmed_zdr"] = True
    return XaiChecker(cfg, api_key=key, transport=transport, env=env)


def paypal_ready(env) -> bool:
    """All three PayPal sandbox settings are filled in (values are never read out loud or logged)."""
    return all(str(env.get(k, "") or "").strip() for k in PAYPAL_ENV)


def hosted_watch(gate, env, sender=None, verifier=None, paypal_sender=None):
    """The PayPal account watcher for /paypal-webhook, or None (route off) unless all of PAYPAL_ENV are set.
    sender: Twilio transport for the alert call (tests pass a fake). verifier / paypal_sender: tests only.
    Sandbox only (PayPalSandbox refuses any other host)."""
    if not paypal_ready(env):
        return None
    from . import acctwatch as W
    from . import alerts as AL
    from .paypal_client import PayPalSandbox
    client = PayPalSandbox(str(env["PAYPAL_CLIENT_ID"]).strip(), str(env["PAYPAL_SANDBOX_SECRET"]).strip())
    if verifier is None:
        verifier = W.PayPalVerifier(client, str(env["BW_PAYPAL_WEBHOOK_ID"]).strip(), sender=paypal_sender)
    watch = W.AccountWatch(gate, verifier=verifier, env=env)

    def alerts():   # built per alert, so call settings changed on the Settings page apply at once
        caller = N.call_adapter(gate.engine.p.get("notify", {}) or {}, env=env, sender=sender)
        return AL.Alerts(gate, caller=caller, env=env)
    watch.alerts_factory = alerts
    return watch


# DEPLOYBUTTON 2026-11-02: the Deploy to Render form may not let a box stay empty, so "none" (and friends) count
# as empty for the boxes it asks about. Only these keys; never BW_LOGIN_KEY or BW_CALL_LINK_KEY.
SKIP_WORDS = ("none", "skip", "-", "n/a", "na", "no", "blank", "empty")
PROMPTED_OPTIONAL = ("BW_OWNER_PHONE", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "XAI_API_KEY",
                     *PAYPAL_ENV, "BW_SITE_LOCK_PASSWORD", "BW_PREFERRED_NAME", "BW_CALL_VOICE")
DEMO_ENV = "BW_DEMO_DATA"       # "on" (render.yaml) = a fresh copy opens in Dev mode with sample data. Unset = off.


def drop_skip_words(env) -> list:
    """Remove optional values typed as "none" etc. Returns the key names removed (names only, never values)."""
    gone = []
    for k in PROMPTED_OPTIONAL:
        if str(env.get(k, "")).strip().lower() in SKIP_WORDS and str(env.get(k, "")).strip():
            env.pop(k, None)
            gone.append(k)
    return gone


def demo_on(env) -> bool:
    return str(env.get(DEMO_ENV, "")).strip().lower() in ("1", "on", "yes", "true")


def start_demo(app, env) -> bool:
    """First start of a Deploy to Render copy: Dev mode on with sample data (marked TEST, nothing reaches PayPal
    or a phone). Only when BW_DEMO_DATA is on AND Dev mode was never set in this data folder, so turning Dev
    mode off stays off until the folder is wiped (the free plan wipes it on restart)."""
    if not demo_on(env):
        return False
    real = app.real_gate
    dev = real.dev
    if dev.path is None or Path(dev.path).exists():
        return False
    dev.set(True, "green")
    real.audit.write("dev_mode_on", action_id="-", label="TEST", by="first start (BW_DEMO_DATA)")
    app.sample_gate()
    return True


def serve_hosted(port: int, env=None, bind: str = "0.0.0.0", sender=None, xai_transport=None,
                 paypal_verifier=None, paypal_sender=None):
    """Returns (server, app). Your own Bridge Warden on your own public host (Render)."""
    from . import web
    from .cli import build_gate
    env = os.environ if env is None else env
    drop_skip_words(env)                                 # "none" typed in the Deploy to Render form = empty
    cfg = hosted_settings(env)
    if not str(env.get("BW_CALL_URL", "")).strip():
        env["BW_CALL_URL"] = "https://" + cfg["host"]          # calls come back to THIS app (no Worker)
    pol = prepare_policy(cfg["data"], env)
    gate = build_gate(SimpleNamespace(policy=str(pol), audit=str(cfg["data"] / "audit" / "audit.jsonl"),
                                      live=False, no_xai=True))
    gate.ai = hosted_ai(gate, env, xai_transport)       # None unless XAI_API_KEY is set
    judge_xai = JA.JudgeXaiCounter(cfg["data"] / "audit", env=env)
    judge_sessions: dict = {}                            # session token -> judge key (memory only, never logged)
    app = web.WebApp(gate)
    app.judge_xai = judge_xai
    app.alert_test.env, app.alert_test.sender = env, sender
    app.email_env = env            # "Email me my proof" goes to the owner's own address from these settings
    app.hosted = cfg
    watch = hosted_watch(gate, env, sender=sender, verifier=paypal_verifier, paypal_sender=paypal_sender)
    app.paypal_watch = watch                             # None = /paypal-webhook is off ("not set up")
    start_demo(app, env)                                 # BW_DEMO_DATA=on: fresh copy opens in Dev mode
    free = free_plan(env, cfg["data"])
    guard = LoginGuard(cfg["login_key"])
    lock = site_lock(env)                                # "" = no site lock
    H = web.make_handler(gate, app=app)
    origin = "https://" + cfg["host"]

    class HostedH(H):
        def _host_ok(self):
            return self.headers.get("Host", "").lower() in (cfg["host"], cfg["host"] + ":443")

        def _same_origin_post(self):
            o, sfs = self.headers.get("Origin"), self.headers.get("Sec-Fetch-Site")
            if o == "null":
                return sfs == "same-origin"
            if o is not None and o != origin:
                return False
            return sfs is None or sfs in ("same-origin", "none")

        THEME_SECURE = True     # hosted is always https: the bw_theme cookie gets Secure

        def _send(self, body, code=200, extra=None, ctype="text/html; charset=utf-8"):
            if isinstance(body, str) and ctype.startswith("text/html"):
                body = body.replace(LOCAL_FOOTER, HOSTED_FOOTER)     # every hosted page, /login too
            if lock and isinstance(body, str) and ctype.startswith("text/html") and "<head>" in body \
                    and LOCK_META not in body:
                body = body.replace("<head>", "<head>" + LOCK_META, 1)     # locked copy: meta noindex too
            return super()._send(body, code, {"Strict-Transport-Security": HSTS, **(extra or {})}, ctype)

        def _redirect(self, where, extra=None):
            return super()._redirect(where, {"Strict-Transport-Security": HSTS, **(extra or {})})

        def _page(self, title, body, active, extra=None, mark=True, mark_back="navy"):
            out = web.page(title, body, active, web.status_with_button(app), app.take_flash(), mark=mark,
                           mark_back=mark_back).replace(LOCAL_FOOTER, HOSTED_FOOTER)
            self._send(with_free_banner(out) if free else out, extra=extra)

        def _body(self, cap):
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if n < 0 or n > cap:
                return None
            return self.rfile.read(n)

        def _cookie_token(self) -> str:
            from http.cookies import SimpleCookie
            c = SimpleCookie()
            try:
                c.load(self.headers.get("Cookie", ""))
            except Exception:
                return ""
            m = c.get(web.COOKIE)
            return m.value if m else ""

        def _session_judge_key(self) -> str:
            tok = self._cookie_token()
            if not tok:
                return ""
            for t, k in list(judge_sessions.items()):
                if hmac.compare_digest(t.encode(), tok.encode()):
                    return k if N.is_judge(k, env) else ""     # a removed judge key logs that judge out
            return ""

        def _logged_in(self):
            return super()._logged_in() or bool(self._session_judge_key())

        def _call(self, url, params):
            with JA.acting_as(getattr(app.alert_test, "ai_judge_key", ""), judge_xai):   # call replies: that judge
                code, body, ctype = answer_call(cfg, env, url.path, url.query, params,
                                                self.headers.get("X-Twilio-Signature", ""), ai=gate.ai)
            return self._send(body, code, {"Content-Security-Policy": "default-src 'none'"}, ctype)

        # ---- site lock (BW_SITE_LOCK_PASSWORD): every route needs the password, except Twilio's signed call
        # webhooks (they keep their own signature / signed-link checks) and the bare health check.
        def send_response(self, code, message=None):
            self._robots_sent = False
            return super().send_response(code, message)

        def send_header(self, keyword, value):
            if lock and keyword.lower() == "x-robots-tag":
                value, self._robots_sent = LOCK_ROBOTS + ", " + str(value), True
            return super().send_header(keyword, value)

        def end_headers(self):
            if lock and not getattr(self, "_robots_sent", False) and getattr(self, "_headers_buffer", None) is not None:
                self._robots_sent = True
                super().send_header("X-Robots-Tag", LOCK_ROBOTS)
            return super().end_headers()

        def _lock_blocks(self) -> bool:
            if not lock:
                return False
            path = urllib.parse.urlparse(self.path).path
            if path in LOCK_OPEN or path in CALL_STEPS or path in ("/call-status", PAYPAL_HOOK):
                return False
            if lock_ok(self.headers.get("Authorization", ""), lock):
                return False
            body = b"This Bridge Warden copy is private. Password needed."
            self.send_response(401)
            self.send_header("WWW-Authenticate", LOCK_REALM)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Strict-Transport-Security", HSTS)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return True

        def do_GET(self):
            if self._lock_blocks():
                return None
            if lock and urllib.parse.urlparse(self.path).path == "/robots.txt":
                return self._send(LOCK_ROBOTS_TXT, ctype="text/plain; charset=utf-8")
            with JA.acting_as(self._session_judge_key(), judge_xai):     # a judge's AI use counts against their key
                return self._do_get()

        def do_POST(self):
            if self._lock_blocks():
                return None
            if urllib.parse.urlparse(self.path).path == PAYPAL_HOOK:   # PayPal, not a judge: owner's own allowance
                with JA.acting_as("", judge_xai):
                    return self._paypal_hook()
            with JA.acting_as(self._session_judge_key(), judge_xai):
                return self._do_post()

        def _do_get(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/healthz":
                return self._send("ok", ctype="text/plain; charset=utf-8")
            if not self._host_ok():
                return self._deny("wrong host", 421)
            if url.path in CALL_STEPS:
                params = {k: v for k, v in urllib.parse.parse_qsl(url.query) if k not in OUR_KEYS}
                return self._call(url, params)
            if url.path == "/login":
                return self._send(web.page("Log in", LOGIN_BODY, "", None, mark=True))
            if not self._logged_in() and not url.path.startswith(OPEN_PATHS):
                return self._redirect("/login")      # every private page sends you to the login form
            return super().do_GET()

        def _paypal_hook(self):
            """PayPal sandbox webhook. No login; acctwatch's own checks instead. Plain-text answers only."""
            plain = {"Content-Security-Policy": "default-src 'none'", "Cache-Control": "no-store"}
            if not self._host_ok():
                return self._deny("wrong host", 421)
            if watch is None:
                return self._send("not set up", 503, plain, "text/plain; charset=utf-8")
            from . import acctwatch as W
            t0 = time.perf_counter()
            raw = self._body(W.MAX_BODY)
            if raw is None:
                return self._send("request too large", 413, plain, "text/plain; charset=utf-8")
            try:
                code, why, _res = watch.receive(dict(self.headers.items()), raw, t0)
            except Exception as e:      # never a stack trace (or a header) in the reply
                gate.audit.write("acctwatch_error", action_id="-", error=type(e).__name__)
                code, why = 500, "error"
            return self._send(str(why)[:200], code, plain, "text/plain; charset=utf-8")

        def _do_post(self):
            url = urllib.parse.urlparse(self.path)
            if not self._host_ok():
                return self._deny("wrong host", 421)
            if url.path == "/call-status":   # MISSEDCALL: Twilio's signed StatusCallback (how the call ended)
                raw = self._body(MAX_CALL_BODY)
                if raw is None:
                    return self._deny("request too large", 413)
                try:
                    params = dict(urllib.parse.parse_qsl(raw.decode("utf-8"), keep_blank_values=True,
                                                         max_num_fields=60))
                except (UnicodeDecodeError, ValueError):
                    params = {}
                code = call_status(cfg, getattr(app, "real_gate", gate), params,
                                   self.headers.get("X-Twilio-Signature", ""))
                return self._send("", code, {"Content-Security-Policy": "default-src 'none'"},
                                  "text/plain; charset=utf-8")
            if url.path in CALL_STEPS:
                raw = self._body(MAX_CALL_BODY)
                if raw is None:
                    return self._deny("request too large", 413)
                try:
                    params = dict(urllib.parse.parse_qsl(raw.decode("utf-8"), keep_blank_values=True,
                                                         max_num_fields=60))
                except (UnicodeDecodeError, ValueError):
                    params = {}
                return self._call(url, params)
            if url.path == "/login":
                if not self._same_origin_post():
                    return self._deny("cross-site request refused")
                if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
                    return self._deny("wrong content type", 415)
                raw = self._body(4096)
                if raw is None:
                    return self._deny("request too large", 413)
                try:
                    k = urllib.parse.parse_qs(raw.decode("utf-8"), max_num_fields=5).get("k", [""])[0].strip()
                except (UnicodeDecodeError, ValueError):
                    k = ""
                r = guard.check(k, is_judge=lambda g: N.is_judge(g, env))
                if r == "slow":
                    return self._deny("Too many wrong tries. Wait a minute, then try again.", 429)
                if r == "judge":         # a judge: own session, own xAI allowance. The key is never logged.
                    tok = secrets.token_urlsafe(32)
                    if len(judge_sessions) >= JUDGE_SESSIONS_MAX:
                        judge_sessions.pop(next(iter(judge_sessions)))
                    judge_sessions[tok] = k
                    gate.audit.write("hosted_login", action_id="-", by="judge (web)")
                    return self._redirect("/", {"Set-Cookie": f"{web.COOKIE}={tok}; HttpOnly; SameSite=Strict; "
                                                              "Path=/; Secure"})
                if r != "ok":
                    gate.audit.write("hosted_login_refused", action_id="-", by="web")
                    return self._deny("That login key is wrong.", 401)
                gate.audit.write("hosted_login", action_id="-", by="owner (web)")
                return self._redirect("/", {"Set-Cookie": f"{web.COOKIE}={app.session}; HttpOnly; SameSite=Strict; "
                                                          "Path=/; Secure"})
            return super().do_POST()

    srv = ThreadingHTTPServer((bind, port), HostedH)
    srv.bw_app = app
    return srv, app
