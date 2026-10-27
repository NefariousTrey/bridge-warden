"""v6: run the node tests for the AG Studio glue (bw-studio.js) when node is installed.
Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache 2.0."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_bw_studio_glue_node_tests():
    p = Path(__file__).parent / "node" / "test_bw_studio.mjs"
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "6 passed" in r.stdout
