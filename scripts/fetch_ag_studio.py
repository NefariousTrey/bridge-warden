#!/usr/bin/env python3
"""Optional: fetch AG Studio (COMMERCIAL, by AG Grid Ltd, NOT Apache) for the BW AG Grid agent dashboard + chat panel.

Same job as scripts/fetch_ag_studio.sh, but works on Windows, macOS and Linux with only Python (no npm, tar or bash):

    python scripts/fetch_ag_studio.py

Downloads ag-studio@3.0.0 from the public npm registry, checks the npm sha512 AND the pinned SHA-256 of the bundle,
and saves it to bridge_warden/vendor/ag-studio/ (git-ignored, never committed). Using it means accepting AG Grid's
licence: https://www.ag-grid.com/eula/AG-Grid-Enterprise-License-Latest.html (shipped as LICENSE.html in the package).
Unlicensed use shows a watermark. Trial key: https://www.ag-grid.com/studio/license-pricing/?tab=trial
-> put it in BW_AG_STUDIO_LICENSE_KEY (env). This script never reads or prints that key.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

PIN = "41b525170d224be3b5ceb4116d0952b39601a7198e0c44148bfa48aabf556a8e"   # sha256 of dist/umd/ag-studio.min.js
TARBALL = "https://registry.npmjs.org/ag-studio/-/ag-studio-3.0.0.tgz"
INTEGRITY = "sha512-/kXv0vsy3TIY0mjdQzLEVvfbQmf8hlrTW+9ju7tET5bGNE8qCA4t5ay9TYUciMixkypsqAochTx1Ip5wy8Q7Nw=="
BUNDLE, LICENCE = "package/dist/umd/ag-studio.min.js", "package/LICENSE.html"
ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", default=str(ROOT / "bridge_warden" / "vendor" / "ag-studio"))
    a = ap.parse_args(argv)
    with urllib.request.urlopen(TARBALL, timeout=120) as r:     # noqa: S310 (fixed https URL)
        tgz = r.read()
    got512 = "sha512-" + base64.b64encode(hashlib.sha512(tgz).digest()).decode()
    if got512 != INTEGRITY:
        print("STOP: package hash mismatch. Nothing saved.", file=sys.stderr)
        return 1
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        js = tf.extractfile(BUNDLE).read()
        lic = tf.extractfile(LICENCE).read()
    got = hashlib.sha256(js).hexdigest()
    if got != PIN:
        print(f"STOP: hash mismatch ({got}). Nothing saved.", file=sys.stderr)
        return 1
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ag-studio.min.js").write_bytes(js)
    (dest / "AG-STUDIO-LICENSE.html").write_bytes(lic)
    print(f"Saved AG Studio 3.0.0 to {dest} (hash checked). Restart Bridge Warden to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
