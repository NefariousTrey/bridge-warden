"""Judge AI allowance: real xAI on the owner's key for judges, capped per judge key.

Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0 (see LICENSE).

How it works (hosted copy only, judges log in with their own judge key):
  * Every request a judge makes runs "as" that judge (a thread-local, set by hosted.py for that one request).
  * Every message sent to xAI (transaction checks, help chats, the AG chat panel, summaries, call replies and the
    one-word zero-data-retention preflight) goes through XaiChecker._send_counted, which takes one message from that
    judge's allowance FIRST. No allowance left = nothing is sent; the caller shows its sample answer with the note
    LIMIT_NOTE. So a judge can never cost more than the cap.
  * Cap: env BW_JUDGE_XAI_CAP (default 1000). The judge key is never stored or logged: it is turned into an HMAC
    tag with a random per-install salt (the same method as notify.JudgeCalls; judges place no real calls).
  * Saved in the data folder (judge_xai.json, atomic writes). Unreadable file = treated as used up (fail safe).
    On a paid Render disk the count lasts. On Render FREE (no disk) the file is lost when the service restarts,
    sleeps or redeploys, and each judge's count starts again from 0 (see JUDGE_TESTING.md).
  * Requests with no judge (the owner, background checks) are not counted here; the owner's normal limits apply.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

CAP_ENV = "BW_JUDGE_XAI_CAP"
DEFAULT_CAP = 1000
MAX_CAP = 100_000
FILE = "judge_xai.json"
SKIP = "judge_ai_limit"
LIMIT_NOTE = "Judge AI limit reached, showing sample answer"

_local = threading.local()


class JudgeAiLimit(RuntimeError):
    """Raised instead of sending when the current judge has no messages left. Carries no key."""

    def __init__(self):
        super().__init__(LIMIT_NOTE)


def cap(env=None) -> int:
    raw = str((os.environ if env is None else env).get(CAP_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_CAP
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_CAP
    return max(0, min(n, MAX_CAP))


def current():
    """(judge key, counter) for this request, or (None, None) when no judge is acting."""
    return getattr(_local, "key", None), getattr(_local, "counter", None)


@contextlib.contextmanager
def acting_as(key, counter):
    """Run one request (or one call step) as this judge. key '' or None = not a judge (nothing counted)."""
    old = current()
    _local.key, _local.counter = (key or None), (counter if key else None)
    try:
        yield
    finally:
        _local.key, _local.counter = old


class JudgeXaiCounter:
    """xAI messages per judge key. Persisted, atomic, fail safe."""

    def __init__(self, folder, limit: int | None = None, env=None):
        self.path = Path(folder) / FILE
        self.limit = cap(env) if limit is None else int(limit)
        self._lock = threading.Lock()

    def _read(self):
        if not self.path.exists():
            return {"salt": secrets.token_hex(16), "counts": {}}
        d = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("counts"), dict) or not d.get("salt"):
            raise ValueError("bad judge_xai file")
        return d

    @staticmethod
    def _tag(d, key: str) -> str:
        return hmac.new(d["salt"].encode(), key.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def used(self, key: str) -> int:
        with self._lock:
            try:
                d = self._read()
            except Exception:
                return self.limit
            return int(d["counts"].get(self._tag(d, key), 0))

    def left(self, key: str) -> int:
        return max(0, self.limit - self.used(key))

    def take(self, key: str) -> bool:
        """Reserve one xAI message for this key. False (no change) at the cap or if the file is unreadable."""
        with self._lock:
            try:
                d = self._read()
            except Exception:
                return False
            tag = self._tag(d, key)
            n = int(d["counts"].get(tag, 0))
            if n >= self.limit:
                return False
            d["counts"][tag] = n + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(tmp, self.path)
            return True


def limit_reason():
    """SKIP when a judge is acting and has nothing left, else None. A cheap pre-check; take() is the real gate."""
    key, counter = current()
    if key and counter is not None and counter.left(key) <= 0:
        return SKIP
    return None


def take_or_raise():
    """Called right before every xAI send. Takes one message for the acting judge, or raises JudgeAiLimit."""
    key, counter = current()
    if key and counter is not None and not counter.take(key):
        raise JudgeAiLimit()


def note_for(why) -> str:
    return LIMIT_NOTE if str(why or "").startswith(SKIP) or LIMIT_NOTE in str(why or "") else ""
