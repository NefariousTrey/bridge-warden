"""Logo v7: Trey's two exact logos (sent Oct 26, 2026, ~10 PM ET), cropped tight (shield + key whole) for the header.
Made by @Nefarious_Trey,
with Grok.
Copyright 2026 Douglas Gibbons III. Trey's art: all rights reserved (see ASSETS_NOTICE.md).

Reads (never changed):  brand/BW_logo_navy_fill_trey_20261026.png   (navy fill, for pages with the navy header)
                        brand/BW_logo_white_fill_trey_20261026.jpg  (white fill, Guard History + its Why? page)
Writes NEW files in bridge_warden/static/ (refuses to overwrite):
  bw-mark-navy-v7{,-yellow,-red}{,@2x}.png   and   bw-mark-white-v7{,-yellow,-red}{,@2x}.png
Only the background OUTSIDE the shield is made clear (flood fill from the edges), so the fill INSIDE the shield
(navy or white) stays exactly as Trey painted it. Yellow/red copies recolour the lock orb only."""
import colorsys, sys
from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image

V4 = Path(__file__).resolve().parents[2]
STATIC = V4 / "bridge_warden" / "static"
SRC = {"navy": V4 / "brand/BW_logo_navy_fill_trey_20261026.png",
       "white": V4 / "brand/BW_logo_white_fill_trey_20261026.jpg"}
HUES = {"yellow": 46 / 360, "red": 2 / 360}
TOL = {"navy": 10.0, "white": 18.0}     # colour distance that still counts as "outside background"


def outside_mask(rgb: np.ndarray, tol: float) -> np.ndarray:
    """True where a pixel is background connected to the image edge."""
    h, w, _ = rgb.shape
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    near = np.linalg.norm(rgb - bg, axis=2) <= tol
    seen = np.zeros((h, w), bool)
    q = deque((y, x) for y in range(h) for x in (0, w - 1) if near[y, x])
    q.extend((y, x) for x in range(w) for y in (0, h - 1) if near[y, x])
    for y, x in q:
        seen[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and near[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def cut(kind: str) -> Image.Image:
    rgb = np.asarray(Image.open(SRC[kind]).convert("RGB")).astype(np.float64)
    out = outside_mask(rgb, TOL[kind])
    # soft edge: 1px feather so the cut line is not jagged
    alpha = (~out).astype(np.float64)
    pad = np.pad(alpha, 1, mode="edge")
    soft = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:] + 4 * alpha) / 8
    alpha = np.where(alpha > 0, np.maximum(soft, 0.5), 0)
    ys, xs = np.nonzero(alpha)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = max(y1 - y0, x1 - x0) + 4                     # tight square, 2px margin, shield + key whole
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    rgba = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    canvas = np.zeros((side, side, 4), np.uint8)
    sy, sx = cy - side // 2, cx - side // 2
    for yy in range(side):
        y = sy + yy
        if 0 <= y < rgba.shape[0]:
            xa, xb = max(sx, 0), min(sx + side, rgba.shape[1])
            canvas[yy, xa - sx:xb - sx] = rgba[y, xa:xb]
    return Image.fromarray(canvas, "RGBA")


def orb(im: Image.Image):
    """Centre and radius of the green lock orb (largest bright-green blob in the top half)."""
    a = np.asarray(im).astype(np.float64) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    green = (g > 0.45) & (g > r * 1.6) & (g > b * 1.6) & (a[..., 3] > 0.5)
    h = a.shape[0]
    green[int(h * 0.6):] = False
    ys, xs = np.nonzero(green)
    cy, cx = np.median(ys), np.median(xs)
    d = np.hypot(ys - cy, xs - cx)
    return cx, cy, np.percentile(d, 97)


def recolor(im: Image.Image, hue: float) -> Image.Image:
    a = np.asarray(im).astype(np.float64) / 255
    cx, cy, R = orb(im)
    out = a.copy()
    h, w = a.shape[:2]
    for y in range(max(0, int(cy - R * 1.1)), min(h, int(cy + R * 1.1) + 1)):
        for x in range(max(0, int(cx - R * 1.1)), min(w, int(cx + R * 1.1) + 1)):
            k = np.clip((1.08 - np.hypot(x - cx, y - cy) / R) / 0.08, 0, 1)
            if k <= 0 or a[y, x, 3] == 0:
                continue
            hh, ll, ss = colorsys.rgb_to_hls(*a[y, x, :3])
            if not (70 / 360 <= hh <= 175 / 360) or ss < 0.15:
                continue
            out[y, x, :3] = (1 - k) * a[y, x, :3] + k * np.array(colorsys.hls_to_rgb(hue, ll, ss))
    return Image.fromarray((out * 255).round().astype(np.uint8), "RGBA")


def main() -> int:
    for kind in SRC:
        big = cut(kind)
        print(kind, "crop", big.size, "orb", tuple(round(v) for v in orb(big)))
        for state, hue in [("", None), *[("-" + k, v) for k, v in HUES.items()]]:
            art = big if hue is None else recolor(big, hue)
            for suf, px in (("", 128), ("@2x", 256)):
                dst = STATIC / f"bw-mark-{kind}-v7{state}{suf}.png"
                if dst.exists() and "--force" not in sys.argv:
                    print("exists, not overwriting:", dst); continue
                art.resize((px, px), Image.LANCZOS).save(dst, optimize=True)
                print("wrote", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
