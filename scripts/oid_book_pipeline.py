#!/usr/bin/env python3
"""Assemble an experimental OID book with mandatory pre/post digital preflight.

Only accepts already-prepared book + OID bindings. A8S hardware and native
book-pack generation remain out of scope. Never upgrades UNVERIFIED to tested.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import book_assembly
from scripts import oid_book_preflight as qa


def build(book_dir: Path, binding: Path, out: Path, *, scans: Path | None = None,
          margin_mm: float = 1.0, allow_missing_audio: bool = False) -> dict:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Refusing nonempty output directory')
    before=qa.analyze(book_dir,binding,scans=scans,margin_mm=margin_mm)
    if before['status']=='BLOCKED':
        raise ValueError('Preflight blocked: '+json.dumps(before['summary'],ensure_ascii=False))
    if before['summary']['missing_audio_ids'] and not allow_missing_audio:
        raise ValueError('Missing audio: '+', '.join(before['summary']['missing_audio_ids']))
    assembled=book_assembly.compose(book_dir,binding,out,allow_missing_audio=allow_missing_audio,
                                     margin_mm=margin_mm)
    after=qa.analyze(book_dir,binding,scans=scans,assembly_audit=out/'audit.json',margin_mm=margin_mm)
    qa.save(after,out/'preflight.json',out/'preflight.csv')
    if after['status']=='BLOCKED':
        raise RuntimeError('Assembled output failed post-assembly verification; inspect preflight.json')
    return {'status':after['status'],'book_id':after['book_id'],
            'regions':len(after['regions']),'assembly_status':assembled['status'],
            'a8s_compatible':'UNTESTED','print_book':str(out/'EXPERIMENTAL_print_book.pdf'),
            'preflight_report':str(out/'preflight.json')}


def main(argv=None):
    p=argparse.ArgumentParser(description='Experimental OID2 book assembly + automatic preflight')
    p.add_argument('--book-dir',type=Path,required=True)
    p.add_argument('--binding',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--scans',type=Path)
    p.add_argument('--margin-mm',type=float,default=1.0)
    p.add_argument('--allow-missing-audio',action='store_true')
    a=p.parse_args(argv)
    try:
        print(json.dumps(build(a.book_dir,a.binding,a.out,scans=a.scans,
                               margin_mm=a.margin_mm,allow_missing_audio=a.allow_missing_audio),ensure_ascii=False))
    except (ValueError,FileNotFoundError,FileExistsError,KeyError,RuntimeError) as exc:
        p.exit(2,'ERROR: '+str(exc)+'\n')


if __name__=='__main__': main()
