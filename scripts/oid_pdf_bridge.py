#!/usr/bin/env python3
"""Extract candidate optical tiles from an external OID-only PDF, NOT a native A8S encoder."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "ant-reader-oid-pdf-import/1"

def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def import_pdf(spec_path: Path, out_dir: Path):
    import fitz
    from PIL import Image
    spec_path=spec_path.resolve()
    cfg=json.loads(spec_path.read_text(encoding="utf-8"))
    if cfg.get("format")!=SCHEMA:
        raise ValueError("Invalid import format")
    dpi=cfg.get("dpi")
    threshold=cfg.get("threshold",160)
    if type(dpi) is not int or not 300 <= dpi <= 2400:
        raise ValueError("dpi must be 300..2400")
    if type(threshold) is not int or not 1 <= threshold <= 254:
        raise ValueError("threshold must be 1..254")
    source_desc=cfg.get("source")
    if not isinstance(source_desc,str) or len(source_desc.strip())<5:
        raise ValueError("Identify the code generator and version")
    tiles=cfg.get("tiles")
    if not isinstance(tiles,list) or not 1<=len(tiles)<=100:
        raise ValueError("Expected 1..100 tiles")
    rel=cfg.get("source_pdf")
    if not isinstance(rel,str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError("source_pdf must be a safe relative path")
    base=spec_path.parent.resolve()
    src=(base/rel).resolve()
    if not src.is_relative_to(base) or not src.is_file():
        raise ValueError("Missing/outside source PDF")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError("Output directory must be empty")
    prepared=[]
    names,o_ids=set(),set()
    with fitz.open(src) as doc:
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError("Expected unencrypted PDF")
        for t in tiles:
            if not isinstance(t,dict):
                raise ValueError("Tile must be an object")
            name,oid,page=t.get("id"),t.get("raw_oid"),t.get("page")
            box=t.get("rect_mm")
            if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}",name):
                raise ValueError("Invalid tile label")
            if type(oid) is not int or not 0<=oid<=0xFFFFFFFF:
                raise ValueError("Invalid raw_oid")
            if name in names or oid in o_ids:
                raise ValueError("Duplicate tile label or raw_oid")
            if type(page) is not int or not 1<=page<=len(doc):
                raise ValueError("Invalid page")
            if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) for v in box):
                raise ValueError("rect_mm must be [x,y,width,height]")
            x,y,w,h=box
            if min(x,y)<0 or min(w,h)<=0 or max(w,h)>45:
                raise ValueError("Invalid tile geometry")
            if w*h*(dpi/25.4)**2>20_000_000:
                raise ValueError("Tile image too large")
            mm=72/25.4
            rect=fitz.Rect(x*mm,y*mm,(x+w)*mm,(y+h)*mm)
            if not doc[page-1].rect.contains(rect):
                raise ValueError("Crop outside page")
            pix=doc[page-1].get_pixmap(clip=rect,matrix=fitz.Matrix(dpi/72,dpi/72),
                                       colorspace=fitz.csGRAY,alpha=False,annots=False)
            gray=Image.frombytes("L",(pix.width,pix.height),pix.samples)
            if min(gray.size)<32:
                raise ValueError("Code tile too small")
            mask=gray.point(lambda pixel: 255 if pixel<threshold else 0)
            dark=mask.histogram()[255]/(gray.width*gray.height)
            if not .0001<dark<.35:
                raise ValueError(f"{name}: unexpected dark pixel density; crop OID-only PDF")
            img=Image.new("RGBA",gray.size,(0,0,0,0))
            img.putalpha(mask)
            names.add(name);o_ids.add(oid)
            prepared.append((name,oid,page,box,img,dark))
    out_dir.mkdir(parents=True,exist_ok=True)
    (out_dir/"tiles").mkdir()
    exported=[]
    for name,oid,page,box,img,dark in prepared:
        dest=out_dir/"tiles"/(name+".png")
        img.save(dest,dpi=(dpi,dpi))
        exported.append({"id":name,"raw_oid":oid,"source_dpi":dpi,"source":source_desc,
                         "image":"tiles/"+dest.name,"source_pdf_page":page,"rect_mm":box,
                         "rendered_pixels":list(img.size),"dark_pixel_fraction":round(dark,6),
                         "png_sha256":_hash(dest),"a8s_status":"UNVERIFIED"})
    result={"format":"ant-reader-oid-candidates/1","status":"UNVERIFIED_A8S","candidates":exported}
    (out_dir/"oid_candidates.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    audit={"format":SCHEMA,"source_pdf_sha256":_hash(src),"source_dpi":dpi,"threshold":threshold,
           "a8s_tested":False,
           "warning":"PDF rendering and thresholding alter fine dot geometry; real A8S verification required."}
    (out_dir/"source_audit.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser(description="EXPERIMENTAL external PDF OID tile bridge; no A8S encoder")
    p.add_argument("--spec",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    result=import_pdf(a.spec,a.out)
    print(json.dumps({"status":result["status"],"candidates":len(result["candidates"])},ensure_ascii=False))

if __name__=="__main__":
    main()
