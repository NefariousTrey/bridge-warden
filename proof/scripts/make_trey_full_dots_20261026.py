"""Trey's energy dots, FULL version, TIGHT pass (2026-10-26). Trey: "close, your ring isn't touching the edge."
The cut circle now sits right on the OUTER edge of his glowing ring, measured from each source image (not guessed):
  1. refine the ring center + radius by fitting a circle to the brightest point on 360 rays,
  2. take the median radial brightness profile (max of R,G,B, 2px blur),
  3. outer edge = first radius past the ring peak where brightness falls halfway from ring peak to background.
Everything inside the circle stays exactly as he made it: no brightness-to-alpha, no fades, no backing disc.
Only pixels outside the circle go clear (1px anti-aliased edge). A little outer spark fuzz is clipped.
Loose pass (1.26x rim, old centers) is backed up outside the repo and in
make_trey_full_dots_20261026.py.bak-20261026-tight. Sizes 24/48/96/128/256, PNG + WebP, plain + glyph."""
import json, shutil, sys, numpy as np
from PIL import Image, ImageFilter
import os
sys.path.insert(0, os.environ.get("BW_ART_TOOLS", "."))   # folder with make_trey_dots_20261026.py (build helper, not shipped)
from make_trey_dots_20261026 import glyph_svg, svgpng, RING   # same glyph art; RING = rough start guess only
OLD = "assets/dots-trey-energy-20261026/source"
D = "assets/dots-trey-energy-full-20261026"
SIZES = (24, 48, 96, 128, 256)
EDGE_FRAC = 0.5                # outer edge = halfway down from ring peak to background
PAD = 2                        # source px of crop past the circle (keeps the 1px AA edge inside the square)


def _val(path):
    v = np.asarray(Image.open(path).convert("RGB")).max(2).astype("uint8")
    return np.asarray(Image.fromarray(v).filter(ImageFilter.GaussianBlur(2))).astype(float)


def _polar(v, cx, cy, rmax=520, nA=360):
    rs = np.arange(0, rmax, 0.5); th = np.linspace(0, 2 * np.pi, nA, endpoint=False)
    xi = np.clip((cx + rs[None] * np.cos(th[:, None])).round().astype(int), 0, v.shape[1] - 1)
    yi = np.clip((cy + rs[None] * np.sin(th[:, None])).round().astype(int), 0, v.shape[0] - 1)
    return rs, th, v[yi, xi]


def measure(c):
    """Return (cx, cy, ring_peak_r, outer_edge_r) in source px, measured from Trey's image."""
    v = _val(f"{D}/source/trey-ring-{c}.jpg"); cx, cy, r = map(float, RING[c])
    for _ in range(3):
        rs, th, P = _polar(v, cx, cy); m = (rs > r * .8) & (rs < r * 1.2)
        pk = rs[m][P[:, m].argmax(1)]; px, py = cx + pk * np.cos(th), cy + pk * np.sin(th)
        s = np.linalg.lstsq(np.c_[2 * px, 2 * py, np.ones_like(px)], px ** 2 + py ** 2, rcond=None)[0]
        cx, cy = s[0], s[1]; r = float(np.sqrt(s[2] + cx ** 2 + cy ** 2))
    rs, th, P = _polar(v, cx, cy); prof = np.median(P, 0)
    ipk = int(np.argmax(np.where((rs > r * .85) & (rs < r * 1.15), prof, 0)))
    bg = np.median(prof[(rs > r * 1.3) & (rs < r * 1.45)])
    thr = bg + EDGE_FRAC * (prof[ipk] - bg)
    k = int(np.nonzero(prof[ipk:] < thr)[0][0])
    return round(cx, 1), round(cy, 1), float(rs[ipk]), float(rs[ipk + k])


def master(c, N=768):
    shutil.copy2(f"{OLD}/trey-ring-{c}.jpg", f"{D}/source/trey-ring-{c}.jpg")   # copy of the copy; originals untouched
    cx, cy, rpk, R = measure(c); h = R + PAD
    im = Image.open(f"{D}/source/trey-ring-{c}.jpg").convert("RGB")
    im = im.resize((N, N), Image.LANCZOS, box=(cx - h, cy - h, cx + h, cy + h))  # sub-pixel exact crop
    yy, xx = np.mgrid[0:N, 0:N]; d = np.hypot(xx - N / 2 + .5, yy - N / 2 + .5)
    Rm = N / 2 * R / h
    al = np.clip(Rm - d + 0.5, 0, 1)   # 1px anti-aliased edge, nothing else
    out = im.convert("RGBA"); out.putalpha(Image.fromarray((al * 255).astype("uint8")))
    return out, dict(cx=cx, cy=cy, ring_peak_r=rpk, outer_edge_r=R, cut_r=R, crop_half=h,
                     cut_over_peak=round(R / rpk, 3))


def build():
    files, meas = {}, {}
    for c in RING:
        m, meas[c] = master(c)
        for px in SIZES:
            full = m.resize((px, px), Image.LANCZOS)
            gl = Image.alpha_composite(full, svgpng(glyph_svg(c, px)))
            for var, img in (("full", full), ("full-glyph", gl)):
                b = f"{D}/bw-dot-trey-{c}-{var}-{px}"
                img.save(b + ".png", optimize=True); img.save(b + ".webp", quality=90, method=6)
                files[(c, var, px)] = img
    json.dump(meas, open(f"{D}/measured-radii-tight-20261026.json", "w"), indent=1)
    return files, meas


if __name__ == "__main__":
    print(json.dumps(build()[1], indent=1))
