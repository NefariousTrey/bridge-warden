"""Make the Bridge Warden watermark (icon only, no words) from Trey's original art.
Reads brand/BW_logo_icon_original.jpg (never changed). Removes the outside white, keeps soft edges,
writes bridge_warden/static/bw-mark.png (128px) and bw-mark@2x.png (256px).
Made by @Nefarious_Trey, with Grok. Copyright 2026 Trey (@Nefarious_Trey). Logo art: all rights reserved."""
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

V4 = Path(__file__).resolve().parents[2]
SRC = V4.parent / "brand" / "BW_logo_icon_original.jpg"
OUT = V4 / "bridge_warden" / "static"

rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
mn = rgb.min(axis=2)
# Background = near-white pixels joined to the image edge (white inside the art is kept).
near = mn > 232
lab, _ = ndimage.label(near)
edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
bg = np.isin(lab, list(edge))
# Soft edge: a thin band around the background gets alpha from how white it is.
band = ndimage.binary_dilation(bg, iterations=3) & ~bg
alpha = np.ones(mn.shape, np.float32)
alpha[bg] = 0.0
soft = np.clip((255.0 - mn) / (255.0 - 150.0), 0.0, 1.0)
alpha[band] = soft[band]
# Un-mix the white from edge pixels so no white halo shows on dark or light pages.
a = np.maximum(alpha, 1e-3)[..., None]
col = np.clip((rgb - 255.0 * (1.0 - a)) / a, 0, 255)
rgba = np.dstack([col, alpha * 255.0]).astype(np.uint8)
img = Image.fromarray(rgba, "RGBA")
box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
img = img.crop(box)
side = max(img.size) + 8
sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
sq.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
for px, name in ((128, "bw-mark.png"), (256, "bw-mark@2x.png")):
    p = OUT / name
    if p.exists():
        raise SystemExit(f"{p} exists; not overwriting")
    sq.resize((px, px), Image.LANCZOS).save(p, optimize=True)
    print("saved", p, p.stat().st_size, "bytes")
