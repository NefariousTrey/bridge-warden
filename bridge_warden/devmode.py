"""Dev mode (test only). Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.

While Dev mode is ON:
- Nothing reaches a real account. The Gate never calls PayPal (no orders, payouts or refunds), every new request
  waits, and an approve is refused. This is enforced in gate.py, not just hidden in the page.
- No real phone calls or webhook pushes. Calls (including "Test my alert") use the dry-run adapter: they only
  write "would call owner" to the signed log.
- Test buttons in Settings can show the status light yellow (simulated pause) or red (simulated alert), and add
  a simulated flagged buy or sell that shows in Guard History marked TEST.

The switch is saved in devmode.json next to the audit log, so it stays on (also across restarts, and for the CLI
using the same folder) until the owner switches it off. If that file can't be read, Dev mode counts as ON (safe side).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FILE = "devmode.json"
SIMS = ("green", "gray", "red")              # same states as the status light (gray = yellow / paused)
TEST_PREFIX = "devtest-"                     # action ids of simulated moves. They can never be paid.
LOCK_TEXT = "Dev mode is on: test only, nothing reaches a real account."
BANNER = "Dev mode: test only, nothing reaches a real account"
SIM_TEXT = {"gray": "TEST: simulated pause. Nothing real is paused.",
            "red": "TEST: simulated alert. Nothing real happened."}


def is_test_id(action_id) -> bool:
    return isinstance(action_id, str) and action_id.startswith(TEST_PREFIX)


class DevMode:
    def __init__(self, folder: str | Path | None):
        self.path = Path(folder) / FILE if folder else None

    def _read(self) -> dict:
        if self.path is None or not self.path.exists():
            return {}
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, dict) else {"on": True}
        except Exception:
            return {"on": True}                 # unreadable = locked (fail safe)

    def on(self) -> bool:
        return bool(self._read().get("on"))

    def sim(self) -> str:
        d = self._read()
        s = d.get("sim", "green")
        return s if d.get("on") and s in SIMS else "green"

    def lock_reason(self) -> str | None:
        return LOCK_TEXT if self.on() else None

    def set(self, on: bool, sim: str = "green") -> None:
        if self.path is None:
            raise RuntimeError("Dev mode needs a folder to save its switch.")
        sim = sim if (on and sim in SIMS) else "green"
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"on": bool(on), "sim": sim}))
        os.replace(tmp, self.path)              # all or nothing
