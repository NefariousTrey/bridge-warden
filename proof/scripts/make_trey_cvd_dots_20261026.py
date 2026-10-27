"""Build Trey's colour-blind status orbs for Bridge Warden v4 (2026-10-26).
Copies of hidden-dots/source/hidden-{x,bang,check}.jpg -> square crop around the orb,
transparent background (same idea as the energy rings), sizes 48/96/128/256, PNG + WebP."""
import shutil, numpy as np
from PIL import Image, ImageFilter
SRC="assets/dots-trey-cvd-20261026/source"   # run from the repo root
D="assets/dots-trey-cvd-20261026"
MAP={"red-x":"hidden-x.jpg","yellow-bang":"hidden-bang.jpg","green-check":"hidden-check.jpg"}
CX,CY,H,R=588,835,480,384    # orb centre, half crop, orb rim radius (source px, rim peak ~380)
SIZES=(48,96,128,256)
def master(fn,N=768):
    im=Image.open(f"{SRC}/{fn}").convert("RGB").crop((CX-H,CY-H,CX+H,CY+H)).resize((N,N),Image.LANCZOS)
    a=np.asarray(im).astype(float); v=a.max(2)
    yy,xx=np.mgrid[0:N,0:N]; d=np.hypot(xx-N/2+.5,yy-N/2+.5)/(N/2)
    smoke=np.asarray(Image.fromarray(v.astype('uint8')).filter(ImageFilter.GaussianBlur(N/10))).astype(float)
    ref=np.median(v[d>0.92]); bg=np.minimum(smoke,ref*1.35)+6
    al=np.clip((v-bg)/(255-bg),0,1)**0.8
    rr=R/H
    disc=np.clip((rr-d)/(rr*0.03),0,1)                 # solid orb face
    al=np.maximum(al,disc)*np.clip((1.0-d)/(1.0-rr*1.10),0,1)**1.5  # fade sparks to 0 at edge
    mx=np.maximum(a.max(2,keepdims=True),1); rgb=np.where(disc[...,None]>0, a, np.clip(a/mx*np.maximum(mx,180),0,255))
    return Image.fromarray(np.dstack([rgb,al*255]).astype('uint8'),'RGBA')
def build():
    out={}
    for name,fn in MAP.items():
        shutil.copy2(f"{SRC}/{fn}",f"{D}/source/{fn}")
        m=master(fn)
        for px in SIZES:
            im=m.resize((px,px),Image.LANCZOS); b=f"{D}/bw-dot-trey-cvd-{name}-{px}"
            im.save(b+".png",optimize=True); im.save(b+".webp",quality=90,method=6); out[(name,px)]=im
    return out
if __name__=="__main__":
    f=build()
    s=Image.new("RGBA",(3*300,600),"#0B1220"); w=Image.new("RGBA",(900,300),"#FFFFFF"); s.paste(w,(0,300))
    for i,n in enumerate(MAP):
        for y in (0,300):
            t=f[(n,256)]; s.alpha_composite(t,(i*300+22,y+22))
    s.save("dots-trey-cvd-preview-20261026.png")
