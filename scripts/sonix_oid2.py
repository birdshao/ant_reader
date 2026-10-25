#!/usr/bin/env python3
"""Research-grade Sonix-style OID2: raw 16-bit OID -> pixel-exact dot PNG.

Based on public jindroush/albituzka OID2 implementation (MPL-2.0).
It is NOT a Xiaokedou A8S validation or native NOB/NOD/NOS packer.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from PIL import Image

FRAME_DOTS=((0,0),(8,0),(16,0),(24,0),(0,8),(1,16),(0,24))

def checksum(raw: int) -> int:
    if type(raw) is not int or not 0 <= raw <= 65535:
        raise ValueError("raw_oid must be an unsigned 16-bit integer")
    hi=((raw>>2)^(raw>>8)^(raw>>12)^(raw>>14))&1
    lo=(raw^(raw>>4)^(raw>>6)^(raw>>10))&1
    return hi*2+lo

def encode_symbols(raw: int) -> list[int]:
    return [checksum(raw)]+[(raw>>s)&3 for s in range(14,-1,-2)]

def decode_symbols(symbols: list[int]) -> int:
    if len(symbols)!=9 or any(type(x) is not int or not 0<=x<=3 for x in symbols):
        raise ValueError("Expected nine base-4 symbols")
    raw=0
    for x in symbols[1:]: raw=(raw<<2)|x
    if symbols[0]!=checksum(raw):raise ValueError("Checksum mismatch")
    return raw

def data_dots(raw: int):
    directions=((1,1),(-1,1),(-1,-1),(1,-1))
    return [(8*(i%3+1)+directions[v][0],8*(i//3+1)+directions[v][1])
            for i,v in enumerate(encode_symbols(raw))]

def tile_dots(raw: int):
    return tuple(FRAME_DOTS)+tuple(data_dots(raw))

def render(raw:int,*,dpi:int=1200,width_mm:float=20.,height_mm:float=20.) -> Image.Image:
    if dpi not in (600,1200):raise ValueError("Only 600 and 1200 DPI supported")
    if not 1<=width_mm<=100 or not 1<=height_mm<=100:raise ValueError("Size must be 1..100 mm")
    w,h=(int(v*dpi/25.4) for v in (width_mm,height_mm))
    scale=dpi//600
    period=32*scale
    img=Image.new("RGBA",(w,h),(255,255,255,0))
    pix=img.load()
    for ox in range(0,w,period):
        for oy in range(0,h,period):
            for dx,dy in tile_dots(raw):
                cx,cy=ox+scale*dx,oy+scale*dy
                for ix in range(scale):
                    for iy in range(scale):
                        if cx+ix<w and cy+iy<h:pix[cx+ix,cy+iy]=(0,0,0,255)
    return img

def decode_ideal_tile(image:Image.Image,*,dpi:int=1200,origin=(0,0))->int:
    """Ideal *digital* tile verification only, not an optical camera decoder."""
    if dpi not in (600,1200):raise ValueError("Invalid DPI")
    s=dpi//600; ox,oy=origin
    if ox<0 or oy<0 or ox+32*s>image.width or oy+32*s>image.height:
        raise ValueError("Complete 32x32 primitive tile required")
    im=image.convert("RGBA")
    def marked(x,y):return im.getpixel((ox+x*s,oy+y*s))[3]>=128
    if any(not marked(x,y) for x,y in FRAME_DOTS):raise ValueError("Missing frame dot")
    sym=[]
    for row in range(1,4):
        for col in range(1,4):
            loc=((1,1),(-1,1),(-1,-1),(1,-1))
            found=[n for n,(dx,dy) in enumerate(loc) if marked(8*col+dx,8*row+dy)]
            if len(found)!=1:raise ValueError("Missing or ambiguous data dot")
            sym.append(found[0])
    return decode_symbols(sym)

def digest_pixels(image:Image.Image)->str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()

def import_upstream_internal_table(source:str)->list[int]:
    """Safely read a literal Perl int2raw table; never evaluate/execute Perl."""
    m=re.search(r'\@oid_tbl_int2raw\s*=\s*\((.*?)\)\s*;',source,re.DOTALL)
    if not m:raise ValueError("No int2raw Perl literal table")
    payload=re.sub(r'#.*$','',m.group(1),flags=re.MULTILINE)
    values=[]
    for x in payload.split(','):
        token=x.strip()
        if not token:continue
        rng=re.fullmatch(r'(\d+)\s*\.\.\s*(\d+)',token)
        if rng:
            a,b=map(int,rng.groups())
            if a>b or b>65535:raise ValueError("Invalid range")
            values.extend(range(a,b+1))
        elif re.fullmatch(r'\d+',token):values.append(int(token))
        else:raise ValueError("Unsafe Perl table token")
        if len(values)>65536:raise ValueError("Table too large")
    if len(values)!=65536 or min(values)<0 or max(values)>65535 or len(set(values))!=65536:
        raise ValueError("Table must be bijective on 65536 OID values")
    return values

def main():
    ap=argparse.ArgumentParser(description="Sonix-style OID2 raw renderer; A8S NOT VERIFIED")
    sub=ap.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("render")
    a.add_argument("--raw-oid",type=lambda x:int(x,0),required=True)
    a.add_argument("--dpi",type=int,default=1200)
    a.add_argument("--width-mm",type=float,default=20.)
    a.add_argument("--height-mm",type=float,default=20.)
    a.add_argument("--out",type=Path,required=True)
    a=sub.add_parser("verify")
    a.add_argument("--png",type=Path,required=True)
    a.add_argument("--dpi",type=int,default=1200)
    a.add_argument("--expected-raw-oid",type=lambda x:int(x,0))
    a=sub.add_parser("extract-table")
    a.add_argument("--upstream-source",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    if a.cmd=="render":
        pic=render(a.raw_oid,dpi=a.dpi,width_mm=a.width_mm,height_mm=a.height_mm)
        a.out.parent.mkdir(parents=True,exist_ok=True)
        if a.out.exists():raise FileExistsError(a.out)
        pic.save(a.out,format="PNG",dpi=(a.dpi,a.dpi))
        obj={"status":"A8S_UNVERIFIED","raw_oid":a.raw_oid,"size_px":pic.size,
             "pixel_sha256":digest_pixels(pic),"output":str(a.out)}
    elif a.cmd=="verify":
        with Image.open(a.png) as pic:raw=decode_ideal_tile(pic,dpi=a.dpi)
        if a.expected_raw_oid is not None and raw!=a.expected_raw_oid:
            raise ValueError("Unexpected decoded raw OID")
        obj={"status":"IDEAL_DIGITAL_TILE_ONLY","raw_oid":raw}
    else:
        array=import_upstream_internal_table(a.upstream_source.read_text(encoding="utf-8-sig"))
        if a.out.exists():raise FileExistsError(a.out)
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(json.dumps({"format":"oidproducer1020-int2raw/1","mapping":array,
                         "warning":"not verified on A8S"})+"\n",encoding="utf-8")
        obj={"entries":len(array),"internal100_raw":array[100]}
    print(json.dumps(obj,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
