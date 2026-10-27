"""Append-only, hash-chained, HMAC-signed audit log (JSON Lines).

Every decision (policy loaded, proposed, verdict, AI check, owner yes/no, executing, executed, failed)
gets one line. Each line carries:
  seq   - its number (1, 2, 3, ... across rotated files)
  prev  - the SHA-256 of the line before it (so edits, inserts and deletions break the chain)
  hash  - SHA-256 of the line itself
  mac   - HMAC-SHA256 of the hash with a local key (so the chain can't simply be recomputed after an edit)
A small "head" file remembers the last seq and hash, so cutting lines off the end is caught too.

Rotation: when the file passes max_bytes it is renamed to <name>.000001.jsonl (then .000002, ...)
and a new file starts whose first line links to the last line of the old one. verify() checks the
whole chain across all files. Nothing is ever deleted or rewritten.

The HMAC key comes from env CHECKER_AUDIT_KEY, or a key file created next to the log (mode 0600).
Limit (stated plainly): someone who can read that key file AND rewrite the log can forge it. Keep the
key outside the agent's reach (env, or a file the agent's OS user can't read) for full protection.
Secrets are scrubbed from every record before it is written.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from .guard import scrub_obj

GENESIS = "0" * 64
PRIVATE_MODE = 0o600     # E2EFIX (2026-10-27): history files are owner-only, like the key file
# Files Bridge Warden keeps next to the history (also made owner-only). Names only; nothing else in the folder.
PRIVATE_NAMES = ("acctwatch_state.json", "acctwatch_latency.jsonl", "alert_retries.json", ".audit_hmac.key")


def private(path) -> None:
    """chmod 0600 if the file exists. Never raises (a file system that can't do modes just keeps working)."""
    try:
        p = Path(path)
        if p.is_file() and (p.stat().st_mode & 0o777) != PRIVATE_MODE:
            os.chmod(p, PRIVATE_MODE)
    except OSError:
        pass


def private_open(path, mode="a"):
    """Open for writing; a new file is created owner-only (0600) from the first byte."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if "a" in mode else os.O_TRUNC)
    fh = os.fdopen(os.open(path, flags, PRIVATE_MODE), mode)
    private(path)
    return fh
DEFAULT_MAX_BYTES = 5_000_000
_lock = threading.RLock()


class AuditTampered(RuntimeError):
    pass


def _digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path, max_bytes: int = DEFAULT_MAX_BYTES, key: bytes | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._key = key if key is not None else self._load_key()
        self.make_private()

    def make_private(self) -> None:
        """audit.jsonl and the files beside it (head, lock, rotated parts, watcher/retry state) -> 0600."""
        folder, stem = self.path.parent, self.path.stem
        try:
            names = [p for p in folder.iterdir() if p.is_file()]
        except OSError:
            return
        for p in names:
            n = p.name
            if n == self.path.name or n.startswith(self.path.name + ".") or n.startswith(stem + ".") \
                    or n.split(".lock")[0].split(".tmp")[0] in PRIVATE_NAMES:
                private(p)

    # ---- key ----------------------------------------------------------------------------
    def _load_key(self) -> bytes:
        env = os.environ.get("CHECKER_AUDIT_KEY", "")
        if env:
            return env.encode()
        kf = self.path.parent / ".audit_hmac.key"
        try:
            fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        return kf.read_text().strip().encode()

    def __repr__(self):
        return f"AuditLog({str(self.path)!r})"

    def _mac(self, h: str) -> str:
        return hmac.new(self._key, h.encode(), hashlib.sha256).hexdigest()

    # ---- files --------------------------------------------------------------------------
    @property
    def head_path(self) -> Path:
        return self.path.with_name(self.path.name + ".head")

    def segments(self) -> list:
        """Rotated files (oldest first), then the current file."""
        rx = re.compile(re.escape(self.path.stem) + r"\.(\d{6})" + re.escape(self.path.suffix) + "$")
        rot = sorted((p for p in self.path.parent.iterdir() if rx.match(p.name)), key=lambda p: p.name)
        return rot + ([self.path] if self.path.exists() else [])

    @contextlib.contextmanager
    def _file_lock(self):
        """Cross-process lock, so an agent's `propose` and the owner's `serve` can't interleave lines."""
        with _lock, private_open(self.path.with_name(self.path.name + ".lock"), "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def _tail(self) -> tuple:
        for seg in reversed(self.segments()):
            last = None
            with seg.open() as fh:
                for line in fh:
                    if line.strip():
                        last = line
            if last:
                r = json.loads(last)
                return int(r.get("seq", 0)), r["hash"]
        return 0, GENESIS

    def _rotate_if_needed(self):
        if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
            n = len(self.segments())  # current file counts; rotated names are 1-based
            target = self.path.with_name(f"{self.path.stem}.{n:06d}{self.path.suffix}")
            if target.exists():
                raise AuditTampered(f"rotation target already exists: {target.name}")
            os.rename(self.path, target)  # a rename, not a copy+delete: no line can be lost
            private(target)

    def _write_head(self, seq: int, h: str):
        tmp = self.head_path.with_name(self.head_path.name + ".tmp")
        with private_open(tmp, "w") as fh:
            fh.write(json.dumps({"seq": seq, "hash": h, "mac": self._mac(f"head:{seq}:{h}")}))
        os.replace(tmp, self.head_path)
        private(self.head_path)

    # ---- write / read -------------------------------------------------------------------
    def write(self, event: str, **data) -> dict:
        with self._file_lock():
            self._rotate_if_needed()
            seq, prev = self._tail()
            rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
                   **scrub_obj(data), "seq": seq + 1, "prev": prev}
            rec["hash"] = _digest(rec)
            rec["mac"] = self._mac(rec["hash"])
            with private_open(self.path, "a") as fh:   # append only, never rewrite (owner-only file)
                fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._write_head(rec["seq"], rec["hash"])
            return rec

    def records(self) -> list:
        out = []
        for seg in self.segments():
            out.extend(json.loads(l) for l in seg.read_text().splitlines() if l.strip())
        return out

    def verify(self) -> tuple:
        prev, seq = GENESIS, 0
        try:
            recs = self.records()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, "a line is not valid JSON"
        for i, rec in enumerate(recs, 1):
            body = {k: v for k, v in rec.items() if k not in ("hash", "mac")}
            if rec.get("prev") != prev or _digest(body) != rec.get("hash"):
                return False, f"chain broken at record {i}"
            if not isinstance(rec.get("mac"), str) or not hmac.compare_digest(rec["mac"], self._mac(rec["hash"])):
                return False, f"signature (HMAC) wrong or missing at record {i}"
            if rec.get("seq") != seq + 1:
                return False, f"sequence gap at record {i}"
            prev, seq = rec["hash"], rec["seq"]
        if self.head_path.exists():
            try:
                h = json.loads(self.head_path.read_text())
            except json.JSONDecodeError:
                return False, "head file is damaged"
            if not hmac.compare_digest(str(h.get("mac")), self._mac(f"head:{h.get('seq')}:{h.get('hash')}")):
                return False, "head file signature is wrong"
            if h.get("seq") != seq or h.get("hash") != prev:
                return False, f"log was cut short or rolled back (head says {h.get('seq')} records, found {seq})"
        elif recs:
            return False, "head file is missing"
        return True, "ok"

    def require_intact(self):
        ok, why = self.verify()
        if not ok:
            raise AuditTampered(f"audit log {self.path} failed verification: {why}")

    # ---- history for the rules ----------------------------------------------------------
    def executed_history(self) -> list:
        """What moved money, or MIGHT have, for duplicate/velocity/daily-cap rules (fail closed):
        every 'executing' record counts unless PayPal clearly rejected it afterwards."""
        recs = self.records()
        rejected = {r["action_id"] for r in recs if r["event"] == "failed" and r.get("outcome") == "rejected"}
        results = {r["action_id"]: r.get("result") or {} for r in recs if r["event"] == "executed"}
        executing = {r["action_id"] for r in recs if r["event"] == "executing"}
        out = []
        for r in recs:
            if r["event"] in ("executing", "executed") and r["action_id"] not in rejected:
                if r["event"] == "executed" and r["action_id"] in executing:
                    continue  # counted once, via its 'executing' record
                a = r.get("proposal", {})
                out.append({"at": r.get("clock_at") or r["at"], "action": a.get("action"), "payee": a.get("payee"),
                            "amount": a.get("amount"), "capture_id": results.get(r["action_id"], {}).get("capture_id")})
        return out
