"""Build bridge_warden/static/favicon.ico (16/32/48) and favicon-32.png from Trey's existing BW mark
(bw-mark-navy-v7b@2x.png: solid navy field reads well on browser tabs, light or dark). New files only."""
from pathlib import Path
from PIL import Image
S = Path(__file__).resolve().parents[2] / "bridge_warden" / "static"
src = Image.open(S / "bw-mark-navy-v7b@2x.png").convert("RGBA")
w, h = src.size; m = max(w, h)
sq = Image.new("RGBA", (m, m), (0, 0, 0, 0)); sq.paste(src, ((m - w) // 2, (m - h) // 2))
for n in ("favicon.ico", "favicon-32.png"):
    assert not (S / n).exists(), f"{n} exists; never overwrite"
sq.save(S / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
sq.resize((32, 32), Image.LANCZOS).save(S / "favicon-32.png")
print("ok", src.size)
