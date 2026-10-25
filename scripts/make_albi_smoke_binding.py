#!/usr/bin/env python3
"""Prepare a reproducible 3-OID Albi candidate experiment for a ONE-item book.

Albi raw OIDs != confirmed Xiaokedou A8S OIDs. Does not pack pen files.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oid_lab import load_candidates


def build(manifest: Path, book_dir: Path, out_dir: Path):
    candidates=load_candidates(manifest)
    regions=json.loads((book_dir/'regions.json').read_text(encoding='utf-8'))['regions']
    if len(regions)!=2 or len(candidates)<3:
        raise ValueError('Smoke experiment needs exactly two reading regions and three OID candidates')
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError('Refusing to overwrite existing binding directory')
    out_dir.mkdir(parents=True,exist_ok=True)
    copied=[]
    for i,entry in enumerate(candidates[:3]):
        target=out_dir/f'candidate_{i}_raw_{entry["raw_oid"]}.png'
        shutil.copyfile(entry['_path'],target)
        copied.append({'raw_oid':entry['raw_oid'],'source_dpi':entry['source_dpi'],
                       'source':entry['source'],'image':target.name,
                       'tested_on_a8s':False})
    binding={'format':'ant-reader-a8s-bindings/1','book_id':book_dir.name,
             'WARNING':'ALBI OID2 is unverified on Xiaokedou A8S. The generated handoff is NOT playable.',
             'cover':copied[0], 'regions':{r['logical_id']:copied[i+1] for i,r in enumerate(regions)}}
    output=out_dir/'bindings.json'
    output.write_text(json.dumps(binding,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(output)
    return output


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--book-dir',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    build(args.manifest,args.book_dir,args.out)

if __name__=='__main__':main()
