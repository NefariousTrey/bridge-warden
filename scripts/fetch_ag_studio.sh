#!/usr/bin/env bash
# Optional: fetch AG Studio (COMMERCIAL, by AG Grid Ltd, NOT Apache) for the BW AG Grid agent dashboard + chat panel.
# Downloads ag-studio@3.0.0 from the public npm registry, checks the pinned SHA-256, saves the UMD bundle to
# bridge_warden/vendor/ag-studio/ (git-ignored, never committed). Using it means accepting AG Grid's licence:
# https://www.ag-grid.com/eula/AG-Grid-Enterprise-License-Latest.html (shipped as LICENSE.html in the package) . Unlicensed use shows a watermark. Trial key:
# https://www.ag-grid.com/studio/license-pricing/?tab=trial  -> put it in BW_AG_STUDIO_LICENSE_KEY (env).
set -euo pipefail
PIN="41b525170d224be3b5ceb4116d0952b39601a7198e0c44148bfa48aabf556a8e"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/bridge_warden/vendor/ag-studio"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
npm pack ag-studio@3.0.0 --silent >/dev/null
tar -xzf ag-studio-3.0.0.tgz package/dist/umd/ag-studio.min.js package/LICENSE.html
GOT="$(sha256sum package/dist/umd/ag-studio.min.js | cut -d' ' -f1)"
if [ "$GOT" != "$PIN" ]; then echo "STOP: hash mismatch ($GOT). Nothing saved." >&2; exit 1; fi
mkdir -p "$DEST"
cp package/dist/umd/ag-studio.min.js "$DEST/"
cp package/LICENSE.html "$DEST/AG-STUDIO-LICENSE.html"
echo "Saved AG Studio 3.0.0 to $DEST (hash checked). Restart Bridge Warden to use it."
