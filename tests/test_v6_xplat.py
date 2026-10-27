"""Cross-platform (2026-10-27): the app runs on Linux, macOS and Windows with only the standard library.
These tests run on every OS. On Linux they also fake Windows (no fcntl) to prove the Windows lock path."""
import ast
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "bridge_warden"
POSIX_ONLY = {"fcntl", "pwd", "grp", "resource", "termios", "tty", "pty", "posix", "syslog"}


def _imports(p: Path):
    for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            yield from (a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            yield n.module.split(".")[0]


def test_no_posix_only_imports_outside_the_lock_module():
    bad = {f"{p.name}: {m}" for p in PKG.rglob("*.py") if p.name != "filelock.py"
           for m in _imports(p) if m in POSIX_ONLY}
    assert not bad, bad


def test_app_text_files_are_read_and_written_as_utf8():
    """No bare read_text()/write_text()/open() in the app: Windows would use its local code page."""
    found = []
    for p in PKG.rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            kws = {k.arg for k in n.keywords}
            if name in ("read_text", "write_text") and "encoding" not in kws:
                found.append(f"{p.name}:{n.lineno}")
            if name == "open" and not isinstance(n.func, ast.Attribute) and "encoding" not in kws:
                mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                if "b" not in str(mode):
                    found.append(f"{p.name}:{n.lineno}")
    assert not found, found


def test_lock_serialises_threads(tmp_path):
    from bridge_warden import filelock
    lf, hits, inside = tmp_path / "x.lock", [], []

    def work(i):
        with open(lf, "a", encoding="utf-8") as fh:
            filelock.lock(fh)
            try:
                inside.append(i)
                assert len(inside) == 1
                hits.append(i)
                inside.pop()
            finally:
                filelock.unlock(fh)
    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(hits) == list(range(8))


FAKE_WINDOWS = r'''
import os, sys, threading, types
sys.modules["fcntl"] = None                       # like Windows: import fcntl fails
held, guard, calls = set(), threading.Lock(), []
m = types.ModuleType("msvcrt"); m.LK_NBLCK, m.LK_UNLCK = 2, 0
def locking(fd, mode, n):
    key = (os.fstat(fd).st_ino, os.lseek(fd, 0, 1), n)
    calls.append(mode)
    with guard:
        if mode == m.LK_NBLCK:
            if key in held: raise OSError(36, "busy")
            held.add(key)
        else:
            held.discard(key)
m.locking = locking
sys.modules["msvcrt"] = m
sys.path.insert(0, sys.argv[1])
from bridge_warden import filelock
assert filelock.fcntl is None and filelock.msvcrt is m
from bridge_warden.audit import AuditLog
from bridge_warden import alerts, web, cli    # nothing else needs POSIX-only modules on import
log = AuditLog(os.path.join(sys.argv[2], "audit.jsonl"), key=b"k" * 32)
ts = [threading.Thread(target=lambda i=i: [log.write("e", action_id=f"{i}-{j}") for j in range(5)]) for i in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
ok, why = log.verify(); assert ok, why
assert len(log.records()) == 20
q = alerts.RetryQueue(sys.argv[2]); q.update(lambda d: d.setdefault("x", 1))
assert m.LK_NBLCK in calls and m.LK_UNLCK in calls and not held
print("ok")
'''


def test_windows_lock_path_with_fake_msvcrt(tmp_path):
    """Runs the msvcrt branch (Windows) on any OS by hiding fcntl and faking msvcrt."""
    r = subprocess.run([sys.executable, "-c", FAKE_WINDOWS, str(ROOT), str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("ok")


def test_audit_files_use_lf_and_utf8(tmp_path):
    from bridge_warden.audit import AuditLog
    log = AuditLog(tmp_path / "a.jsonl", key=b"k" * 32)
    log.write("note", action_id="x", description="café ✓")
    raw = (tmp_path / "a.jsonl").read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    json.loads(raw.decode("utf-8").splitlines()[0])


def test_cross_platform_helpers_exist():
    for f in ("scripts/bw_setup.py", "scripts/fetch_ag_studio.py", "scripts/setup.ps1", ".gitattributes",
              ".github/workflows/ci.yml"):
        assert (ROOT / f).is_file(), f
    ga = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in ga and "*.png binary" in ga
    sh = (ROOT / "scripts/fetch_ag_studio.sh").read_text(encoding="utf-8")
    py = (ROOT / "scripts/fetch_ag_studio.py").read_text(encoding="utf-8")
    pin = [l.split('"')[1] for l in sh.splitlines() if l.startswith("PIN=")][0]
    assert pin in py                                 # both fetchers check the same pinned hash
    assert "BW_AG_STUDIO_LICENSE_KEY" not in py.split('"""', 2)[-1].replace("BW_AG_STUDIO_LICENSE_KEY (env)", "")


def test_setup_script_copies_policy_and_never_overwrites(tmp_path):
    (tmp_path / "policy.example.json").write_text('{"a": 1}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "bw_setup.py"), "--root", str(tmp_path), "--no-venv"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "policy.json").read_text(encoding="utf-8") == '{"a": 1}\n'
    (tmp_path / "policy.json").write_text('{"mine": true}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "bw_setup.py"), "--root", str(tmp_path), "--no-venv"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and (tmp_path / "policy.json").read_text(encoding="utf-8") == '{"mine": true}\n'
