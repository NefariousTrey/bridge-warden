"""Make 'blue back' copies of Trey's bw-mark: the big white field inside the shield becomes the header navy
(#0B1220, --navy in web.py STYLE), so the logo blends into the header. Metal highlights and the orb stay as they are.
Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.
Reads bw-mark{,-yellow,-red}{,@2x}.png (never changed). Writes NEW files bw-mark-blue{,-yellow,-red}{,@2x}.png.
Refuses to overwrite."""
import sys
from pathlib import Path
import numpy as np
import scipy.ndimage as nd
from PIL import Image

STATIC = Path(__file__).resolve().parents[2] / "bridge_warden" / "static"
NAVY = np.array([0x0B, 0x12, 0x20], dtype=np.float64)


def field_weight(a: np.ndarray, scale: float) -> np.ndarray:
    """0..1 weight: how much each pixel belongs to the white shield field (largest near-white region)."""
    rgb, al = a[..., :3], a[..., 3]
    lo, spread = rgb.min(-1), rgb.max(-1) - rgb.min(-1)
    core = (lo > 205) & (spread < 25) & (al > 200)
    lab, n = nd.label(core)
    sizes = nd.sum(core, lab, range(1, n + 1))
    field = lab == (int(np.argmax(sizes)) + 1)
    near = nd.binary_dilation(field, iterations=max(2, int(round(3 * scale))))
    soft = np.clip((lo - 140.0) / (205.0 - 140.0), 0, 1) * (spread < 40)   # anti-aliased edge pixels
    return np.where(field, 1.0, np.where(near, soft, 0.0))


def main() -> int:
    for src_tag in ("", "-yellow", "-red"):
        for suf, scale in (("", 0.5), ("@2x", 1.0)):
            src = STATIC / f"bw-mark{src_tag}{suf}.png"
            dst = STATIC / f"bw-mark-blue{src_tag}{suf}.png"
            if dst.exists() and "--force" not in sys.argv:
                print("exists, not overwriting:", dst); continue
            a = np.asarray(Image.open(src).convert("RGBA")).astype(np.float64)
            # the field is found on the green original so all three colours get the identical mask
            base = np.asarray(Image.open(STATIC / f"bw-mark{suf}.png").convert("RGBA")).astype(np.float64)
            w = field_weight(base, scale)[..., None]
            out = a.copy()
            out[..., :3] = (1 - w) * a[..., :3] + w * NAVY
            Image.fromarray(out.round().astype(np.uint8), "RGBA").save(dst, optimize=True)
            print("wrote", dst.name, "field px:", int((w[..., 0] > 0.99).sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
