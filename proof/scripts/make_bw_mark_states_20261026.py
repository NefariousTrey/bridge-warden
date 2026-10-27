"""Make yellow and red copies of Trey's bw-mark (the lock orb only), so the logo dot can match the status light.
Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.
Reads bridge_warden/static/bw-mark.png and bw-mark@2x.png (never changed). Writes NEW files:
bw-mark-yellow.png, bw-mark-yellow@2x.png, bw-mark-red.png, bw-mark-red@2x.png. Refuses to overwrite."""
import colorsys, sys
from pathlib import Path
import numpy as np
from PIL import Image

STATIC = Path(__file__).resolve().parents[2] / "bridge_warden" / "static"
# Orb circle in the 256px art (centre x, centre y, radius). Scaled for the 128px file.
CX, CY, R = 126.0, 90.0, 50.0
HUES = {"yellow": 46 / 360, "red": 2 / 360}     # green orb is ~125 deg


def recolor(src: Path, hue: float, scale: float) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im).astype(np.float64) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - CX * scale, yy - CY * scale) / (R * scale)
    inside = np.clip((1.08 - d) / 0.08, 0, 1)                 # soft edge
    out = a.copy()
    for y in range(h):
        for x in range(w):
            k = inside[y, x]
            if k <= 0 or a[y, x, 3] == 0:
                continue
            r, g, b = a[y, x, :3]
            hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
            if not (70 / 360 <= hh <= 175 / 360) or ss < 0.15:
                continue                                       # only the green glow
            nr, ng, nb = colorsys.hls_to_rgb(hue, ll, ss)
            out[y, x, :3] = (1 - k) * a[y, x, :3] + k * np.array([nr, ng, nb])
    return Image.fromarray((out * 255).round().astype(np.uint8), "RGBA")


def main() -> int:
    for name, hue in HUES.items():
        for src, suf, scale in (("bw-mark.png", "", 0.5), ("bw-mark@2x.png", "@2x", 1.0)):
            dst = STATIC / f"bw-mark-{name}{suf}.png"
            if dst.exists() and "--force" not in sys.argv:
                print("exists, not overwriting:", dst); continue
            recolor(STATIC / src, hue, scale).save(dst, optimize=True)
            print("wrote", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
