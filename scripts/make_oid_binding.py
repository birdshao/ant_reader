#!/usr/bin/env python3
"""Bind third-party OID candidates to prepared book regions, WITHOUT native A8S packing."""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path

def load(p):
    return json.loads(p.read_text(encoding="utf-8"))

def bind(manifest_file:Path,assignment_file:Path,book_dir:Path,out_dir:Path):
    manifest=load(manifest_file)
    candidates=manifest.get("candidates")
    if not isinstance(candidates,list) or not candidates:
        raise ValueError("Candidate manifest is empty")
    by_name={}
    for c in candidates:
        if not isinstance(c,dict) or not isinstance(c.get("id"),str) or c["id"] in by_name:
            raise ValueError("Invalid or duplicate candidate id")
        by_name[c["id"]]=c
    task=load(assignment_file)
    required={r["logical_id"] for r in load(book_dir/"regions.json")["regions"]}
    regions=task.get("regions")
    cover=task.get("cover")
    if not isinstance(regions,dict) or set(regions)!=required:
        raise ValueError("Each prepared region must be assigned exactly once")
    selected=[cover]+list(regions.values())
    if any(type(n) is not str for n in selected) or len(set(selected))!=len(selected) or any(n not in by_name for n in selected):
        raise ValueError("Unknown or reused candidate id")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError("Refusing to overwrite a nonempty directory")
    base=manifest_file.parent.resolve()
    sources={}
    oids=set()
    for name in selected:
        c=by_name[name]
        rel=c.get("image")
        if not isinstance(rel,str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError("Unsafe candidate path")
        src=(base/rel).resolve()
        if not src.is_relative_to(base) or not src.is_file() or src.suffix.lower()!=".png":
            raise ValueError("Missing/outside candidate PNG")
        oid,dpi=c.get("raw_oid"),c.get("source_dpi")
        if type(oid) is not int or oid<0 or oid in oids:
            raise ValueError("Invalid or repeated raw OID")
        if type(dpi) is not int or not 300<=dpi<=2400:
            raise ValueError("Invalid source DPI")
        if not isinstance(c.get("source"),str) or len(c["source"])<4:
            raise ValueError("No code-source provenance")
        oids.add(oid)
        sources[name]=(c,src)
    out_dir.mkdir(parents=True,exist_ok=True)
    (out_dir/"tiles").mkdir()
    def convert(name):
        c,src=sources[name]
        dest=out_dir/"tiles"/(name+".png")
        shutil.copyfile(src,dest)
        return {"raw_oid":c["raw_oid"],"source":c["source"],"source_dpi":c["source_dpi"],
                "image":"tiles/"+dest.name,"tested_on_a8s":False}
    result={"format":"ant-reader-a8s-bindings/1","book_id":book_dir.name,
            "cover":convert(cover),"regions":{k:convert(v) for k,v in regions.items()}}
    (out_dir/"bindings.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out_dir/"README.txt").write_text("UNVERIFIED A8S candidate OIDs; no A8S resource pack generated.\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser(description="Create experimental OID-to-book bindings")
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--assignment",type=Path,required=True)
    p.add_argument("--book-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    r=bind(a.manifest,a.assignment,a.book_dir,a.out)
    print("Bound",len(r["regions"]),"regions; A8S compatibility unverified")

if __name__=="__main__":
    main()
