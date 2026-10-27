#!/usr/bin/env python3
"""One setup step for Bridge Warden on Windows, macOS or Linux (Python 3.10+, standard library only).

    python scripts/bw_setup.py              # make .venv, install test tools, copy policy.example.json -> policy.json
    python scripts/bw_setup.py --no-venv    # just the policy copy
    python scripts/bw_setup.py --ag-studio  # also fetch the optional AG Studio bundle (hash-checked)

It never overwrites anything: an existing .venv or policy.json is left as it is.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Set up Bridge Warden (any OS).")
    ap.add_argument("--root", default=str(HERE.parent), help="the repo folder (default: this repo)")
    ap.add_argument("--no-venv", action="store_true", help="skip making .venv and installing pytest")
    ap.add_argument("--ag-studio", action="store_true", help="also fetch AG Studio (optional, commercial)")
    a = ap.parse_args(argv)
    if sys.version_info < (3, 10):
        print("Bridge Warden needs Python 3.10 or newer.", file=sys.stderr)
        return 1
    root = Path(a.root).resolve()

    pol, ex = root / "policy.json", root / "policy.example.json"
    if pol.exists():
        print(f"policy.json already there, left as it is: {pol}")
    elif ex.exists():
        shutil.copyfile(ex, pol)                                  # copy, never move
        print(f"Copied policy.example.json -> {pol}")

    venv = root / ".venv"
    if not a.no_venv:
        if not venv.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
            print(f"Made {venv}")
        py = venv_python(venv)
        req = root / "requirements-dev.txt"
        if req.exists():
            subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req)], check=True)
            print("Installed test tools (pytest).")

    if a.ag_studio:
        sys.path.insert(0, str(HERE))
        import fetch_ag_studio
        if fetch_ag_studio.main([]) != 0:
            return 1

    if os.name == "nt":
        act = r".venv\Scripts\Activate.ps1   (PowerShell)   or   .venv\Scripts\activate.bat   (cmd)"
    else:
        act = ". .venv/bin/activate"
    print("\nNext:")
    if not a.no_venv:
        print(f"  {act}")
    print("  python -m bridge_warden demo        # dry run, no accounts needed")
    print("  python -m bridge_warden serve       # the web app on http://127.0.0.1:8765")
    print("  python -m pytest -q                 # tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
