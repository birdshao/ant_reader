#!/usr/bin/env python3
"""Prepare direct-print Sonix-style OID2 tiles for experimental ant_reader books."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.sonix_oid2 import render,decode_ideal_tile,digest_pixels

def build(book_dir:Path,assignment_path:Path,out:Path,*,dpi=1200,tile_mm=20.0):
    cfg=json.loads(assignment_path.read_text(encoding="utf-8"))
    regions=json.loads((book_dir/"regions.json").read_text(encoding="utf-8"))["regions"]
    expected={r["logical_id"] for r in regions}
    assigned=cfg.get("regions")
    if cfg.get("book_id")!=book_dir.name:raise ValueError("book_id mismatch")
    if not isinstance(assigned,dict) or set(assigned)!=expected:
        raise ValueError("Missing or extra region assignment")
    keys=["__cover__"]+sorted(expected)
    values=[cfg.get("cover_raw_oid")]+[assigned[k] for k in sorted(expected)]
    if any(type(x) is not int or not 0<=x<=65535 for x in values):
        raise ValueError("raw_oid must be 16-bit")
    if len(set(values))!=len(values):raise ValueError("Duplicate raw OID")
    if out.exists() and any(out.iterdir()):raise FileExistsError(out)
    assets={}
    for key,value in zip(keys,values):
        pic=render(value,dpi=dpi,width_mm=tile_mm,height_mm=tile_mm)
        if decode_ideal_tile(pic,dpi=dpi)!=value:raise RuntimeError("Encoding verification failed")
        assets[key]=(value,pic,digest_pixels(pic))
    out.mkdir(parents=True,exist_ok=True)
    binding={"format":"ant-reader-a8s-bindings/1","book_id":book_dir.name,
             "WARNING":"Sonix-style OID2 UNVERIFIED on A8S; NOT an installable pen pack.","regions":{}}
    for key,(value,pic,hash_) in assets.items():
        filename="raw_%d_%s.png"%(value,"cover" if key=="__cover__" else key.replace(":","_"))
        pic.save(out/filename,format="PNG",dpi=(dpi,dpi))
        entry={"raw_oid":value,"source_dpi":dpi,"image":filename,
               "source":"Sonix OID2: independent Python reimplementation from jindroush/albituzka, A8S unverified",
               "tested_on_a8s":False}
        if key=="__cover__":binding["cover"]=entry
        else:binding["regions"][key]=entry
    (out/"bindings.json").write_text(json.dumps(binding,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report={"format":"ant-reader-sonix-oid2-bindings/1","status":"A8S_UNVERIFIED",
            "raw_oid_by_region":dict(zip(keys,values)),
            "pixel_sha256":{key:assets[key][2] for key in keys}}
    (out/"audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--book-dir",type=Path,required=True)
    p.add_argument("--assignment",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--dpi",type=int,choices=(600,1200),default=1200)
    p.add_argument("--tile-mm",type=float,default=20)
    a=p.parse_args()
    print(json.dumps(build(a.book_dir,a.assignment,a.out,dpi=a.dpi,tile_mm=a.tile_mm),ensure_ascii=False))

if __name__=="__main__":main()
