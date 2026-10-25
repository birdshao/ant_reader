#!/usr/bin/env python3
"""Synthetic print-degradation stress tests for Sonix-style OID2 artwork.

This tests ideal registered digital code tiles, NOT print/scan calibration, pen
sensor recognition, A8S protocol compatibility or actual hardware success.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from PIL import Image, ImageFilter
if __package__:
    from .sonix_oid2 import FRAME_DOTS, decode_symbols, render
else:
    from sonix_oid2 import FRAME_DOTS, decode_symbols, render

SCHEMA = "ant-reader-oid-print-stress/1"
PROFILES = ("baseline", "blur_0_4", "blur_0_8", "blur_1_2", "dot_gain_1", "dot_loss_1", "low_contrast", "jpeg_70")
SAMPLE_DIRECTIONS = ((1,1),(-1,1),(-1,-1),(1,-1))


def to_white_rgb(pic: Image.Image) -> Image.Image:
    """Flatten transparent black OID data onto white as a normal print bitmap."""
    im = pic.convert("RGBA")
    base = Image.new("RGBA", im.size, "white")
    return Image.alpha_composite(base, im).convert("RGB")


def distort(pic: Image.Image, profile: str) -> Image.Image:
    if profile not in PROFILES:
        raise ValueError(f"Unknown stress profile: {profile}")
    gray = to_white_rgb(pic).convert("L")
    if profile == "baseline":
        return gray
    if profile.startswith("blur_"):
        radius = {"blur_0_4": 0.4, "blur_0_8": 0.8, "blur_1_2": 1.2}[profile]
        return gray.filter(ImageFilter.GaussianBlur(radius))
    if profile == "dot_gain_1":
        return gray.filter(ImageFilter.MinFilter(3))
    if profile == "dot_loss_1":
        return gray.filter(ImageFilter.MaxFilter(3))
    if profile == "low_contrast":
        return gray.point(lambda x: 135 + round(x * 120 / 255))
    buf = io.BytesIO()
    gray.save(buf, "JPEG", quality=70, subsampling=0)
    buf.seek(0)
    with Image.open(buf) as im:
        return im.convert("L")


def decode_tile_registered(gray: Image.Image, dpi: int, origin: tuple[int, int], threshold: int = 128) -> int | None:
    """Decode a tile at a known exact origin, without registration recovery."""
    if dpi not in (600, 1200) or not 0 < threshold < 255:
        raise ValueError("Expected 600/1200 DPI and threshold 1..254")
    size = dpi // 600
    ox, oy = origin
    if ox < 0 or oy < 0 or ox + 32*size > gray.width or oy + 32*size > gray.height:
        raise ValueError("Full tile required")
    pix = gray.load()

    # Sampling a known source pixel exposes blur/erosion sensitivity;
    # this is NOT the decision function of a physical point-reading pen.
    def dark(x: int, y: int) -> bool:
        return pix[ox + x*size, oy + y*size] < threshold

    if any(not dark(x,y) for x,y in FRAME_DOTS):
        return None
    symbols = []
    for row in range(1,4):
        for col in range(1,4):
            found = [n for n,(dx,dy) in enumerate(SAMPLE_DIRECTIONS)
                     if dark(col*8+dx, row*8+dy)]
            if len(found) != 1:
                return None
            symbols.append(found[0])
    try:
        return decode_symbols(symbols)
    except ValueError:
        return None


def measure(pic: Image.Image, *, raw_oid: int, dpi: int, threshold: int=128) -> dict:
    if dpi not in (600, 1200):
        raise ValueError("Expected DPI 600 or 1200")
    if type(raw_oid) is not int or not 0 <= raw_oid <= 65535:
        raise ValueError("raw_oid must be 0..65535")
    period = 32*(dpi//600)
    gray = pic.convert("L")
    nx, ny = gray.width//period, gray.height//period
    if not nx or not ny:
        raise ValueError("Image has no complete OID tile")
    good = wrong = unreadable = 0
    for y in range(ny):
        for x in range(nx):
            decoded = decode_tile_registered(gray, dpi, (x*period,y*period), threshold)
            if decoded is None:
                unreadable += 1
            elif decoded == raw_oid:
                good += 1
            else:
                wrong += 1
    total = nx*ny
    return {"total_tiles":total,"correct":good,"wrong_oid":wrong,
            "unreadable":unreadable,"digital_correct_rate":round(good/total, 5)}


def run(raw_oid: int, dpi: int, width_mm: float=20., height_mm:float=20., threshold:int=128) -> dict:
    base = render(raw_oid, dpi=dpi, width_mm=width_mm, height_mm=height_mm)
    outcomes = []
    for name in PROFILES:
        im = distort(base, name)
        outcomes.append({"profile":name, **measure(im,raw_oid=raw_oid,dpi=dpi,threshold=threshold)})
    return {"schema":SCHEMA,"status":"SYNTHETIC_DIGITAL_ONLY_A8S_UNVERIFIED",
            "warning":"Tile origins known, no scanner optics or geometric errors modelled; results do not predict A8S recognition rates.",
            "raw_oid":raw_oid,"dpi":dpi,"threshold":threshold,
            "dimensions_px":list(base.size),"profiles":outcomes}


def main() -> None:
    p=argparse.ArgumentParser(description="Digital Sonix OID2 print-stress study (NOT A8S hardware verification)")
    p.add_argument("--raw-oid",required=True,type=lambda v:int(v,0))
    p.add_argument("--dpi",type=int,default=1200,choices=(600,1200))
    p.add_argument("--width-mm",type=float,default=20.)
    p.add_argument("--height-mm",type=float,default=20.)
    p.add_argument("--threshold",type=int,default=128)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    data=run(a.raw_oid,a.dpi,a.width_mm,a.height_mm,a.threshold)
    if a.out.exists():p.error("Refusing to overwrite an existing report")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"saved":str(a.out),"status":data["status"],"profiles":len(data["profiles"])},ensure_ascii=False))


if __name__ == "__main__":
    main()
