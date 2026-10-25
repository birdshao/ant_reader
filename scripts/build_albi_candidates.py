#!/usr/bin/env python3
"""Reproducible third-party Albi OID2 candidate experiment (NOT A8S-native)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

# Pin this upstream snapshot so the internal-ID -> raw-OID mapping remains stable.
ALBI_SHA = "04dbe89903534bc2b0b661684ad514f269217775"


def build(albi: Path, out: Path, internal_ids: list[int], dpi: int):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from oid_lab import make_candidate_sheet
    if not (albi / "oid_png_generator.py").is_file() or not (albi / "bnl_utils.py").is_file():
        raise FileNotFoundError("Provide a checked-out Albi_tuzka tree")
    sys.path.insert(0, str(albi.resolve()))
    try:
        from bnl_utils import oid_table
    finally:
        sys.path.pop(0)
    out.mkdir(parents=True, exist_ok=True)
    entries=[]
    for code in internal_ids:
        if not 0 <= code < len(oid_table) or oid_table[code] is None:
            raise ValueError(f"Albi internal ID not available: {code}")
        raw=int(oid_table[code])
        name=f"albi_internal_{code:05d}_raw_{raw}.png"
        cmd=[sys.executable,str(albi/'oid_png_generator.py'),str(code),'--dpi',str(dpi),
             '--size','20','--output',str(out/name)]
        subprocess.run(cmd,check=True)
        entries.append({'id':f'albi-int-{code}', 'raw_oid':raw, 'image':name,
                        'source_dpi':dpi,
                        'source':f'Albi_tuzka@{ALBI_SHA}:internal={code}:raw={raw}'})
    manifest=out/'albi_candidates.json'
    manifest.write_text(json.dumps({'candidates':entries},indent=2)+'\n',encoding='utf-8')
    pdf,audit=make_candidate_sheet(manifest,out/'albi_oid2_experiment.pdf')
    print(f"EXPERIMENT ONLY: {pdf}\nAudit: {audit}\nThis is Albi OID2, NOT verified on Xiaokedou A8S")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--albi',type=Path,required=True,help='Source tree at pinned SHA')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--internal',default='100,101,102',help='Albi INTERNAL IDs; raw codes come from their table')
    ap.add_argument('--dpi',type=int,choices=[600,1200],default=1200)
    args=ap.parse_args()
    build(args.albi,args.out,[int(x) for x in args.internal.split(',')],args.dpi)

if __name__=='__main__':main()