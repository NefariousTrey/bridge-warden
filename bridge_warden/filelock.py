"""Cross-process file lock that works on Linux, macOS and Windows (standard library only).

Linux / macOS: fcntl.flock (whole file, exclusive).
Windows: msvcrt.locking on the first byte of the lock file (waits until it is free).
The lock file is only ever used as a lock; nothing is written to it.
"""
from __future__ import annotations

import os
import time

try:                       # Linux, macOS, other POSIX
    import fcntl
    msvcrt = None
except ImportError:        # Windows
    fcntl = None
    import msvcrt

# Open flag so Windows never turns "\n" into "\r\n" under us (0 on Linux / macOS, where it does not exist).
O_BINARY = getattr(os, "O_BINARY", 0)


def lock(fh) -> None:
    """Block until this process holds the exclusive lock on the open file `fh`."""
    if fcntl is not None:
        fcntl.flock(fh, fcntl.LOCK_EX)
        return
    fd = fh.fileno()
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.02)


def unlock(fh) -> None:
    if fcntl is not None:
        fcntl.flock(fh, fcntl.LOCK_UN)
        return
    fd = fh.fileno()
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def utf8_stdio() -> None:
    """Windows only: print and read UTF-8 (pipes there default to the local code page, which can't show every
    character Bridge Warden prints). Linux and macOS are already UTF-8, so nothing changes there."""
    if os.name != "nt":
        return
    import sys
    for s in (sys.stdout, sys.stderr, sys.stdin):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
