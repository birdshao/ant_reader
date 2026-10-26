#!/usr/bin/env python3
"""Evidence-gated A8S code mapping and vendor-client handoff.

Does NOT create, decrypt, install, or claim compatibility with NOB/NOD/NOS.
The vendor's actual code field is observed experimentally and must not be
assumed equal to printed Sonix raw OID or OidProducer internal index.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

SCHEMA = 'ant-reader-a8s-native-observations/1'
REPORT = 'ant-reader-a8s-native-mapping-report/1'
EVIDENCE = {'vendor_client_measured', 'authorized_vendor_document',
            'a8s_device_event', 'unverified_hypothesis'}
BOOL = {True, False}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def oid(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError(f'{label} must be a 16-bit integer (bool forbidden)')
    return value


def book_id(s: object) -> str:
    if not isinstance(s, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', s):
        raise ValueError('book_id must be an ASCII slug')
    return s


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'File not found or symlink: {path}')
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise ValueError('Expected a JSON object')
    return obj


def observations(path: Path) -> list[dict]:
    doc = read_json(path)
    if doc.get('format') != SCHEMA or not isinstance(doc.get('observations'), list):
        raise ValueError(f'Expected {SCHEMA} with observations array')
    if len(doc['observations']) > 10000:
        raise ValueError('More than 10000 observations')
    result = []
    for i, row in enumerate(doc['observations']):
        if not isinstance(row, dict):
            raise ValueError(f'observations[{i}]: expected object')
        b = book_id(row.get('book_id'))
        raw = oid(row.get('raw_oid'), 'raw_oid')
        vendor = oid(row.get('vendor_code'), 'vendor_code')
        evidence = row.get('evidence')
        if evidence not in EVIDENCE:
            raise ValueError('Invalid evidence type')
        confirmed = row.get('confirmed')
        if type(confirmed) is not bool:
            raise ValueError('confirmed must be a JSON boolean')
        if confirmed and evidence == 'unverified_hypothesis':
            raise ValueError('Hypotheses cannot be marked confirmed')
        source = row.get('source_note')
        if not isinstance(source, str) or not 3 <= len(source.strip()) <= 300:
            raise ValueError('source_note must describe how the code was obtained')
        result.append({'book_id':b, 'raw_oid':raw, 'vendor_code':vendor,
                       'evidence':evidence, 'confirmed':confirmed, 'source_note':source.strip()})
    return result


def analyze(rows: list[dict], oidproducer_table: list[int] | None = None) -> dict:
    by_key = {}
    reverse = {}
    conflicts = []
    for row in rows:
        key=(row['book_id'],row['raw_oid'])
        rev=(row['book_id'],row['vendor_code'])
        if key in by_key and by_key[key] != row['vendor_code']:
            conflicts.append({'reason':'raw maps to different vendor codes within same book',
                              'book_id':key[0], 'raw_oid':key[1]})
        if rev in reverse and reverse[rev] != row['raw_oid']:
            conflicts.append({'reason':'vendor code maps to different raw codes within same book',
                              'book_id':rev[0], 'vendor_code':rev[1]})
        by_key[key] = row['vendor_code']
        reverse[rev] = row['raw_oid']
    confirmed = [r for r in rows if r['confirmed']]
    verified = {(r['book_id'],r['raw_oid']):r['vendor_code'] for r in confirmed}
    for row in rows:
        key=(row['book_id'],row['raw_oid'])
        if key in verified and verified[key] != row['vendor_code']:
            conflicts.append({'reason':'hypothesis contradicts confirmed observation',
                              'book_id':key[0], 'raw_oid':key[1]})
    hypotheses={'identity_raw_to_vendor': {'matches':sum(r['raw_oid']==r['vendor_code'] for r in confirmed),
                                            'observed':len(confirmed), 'proof':False}}
    if oidproducer_table is not None:
        if len(oidproducer_table)!=65536 or set(oidproducer_table)!=set(range(65536)):
            raise ValueError('OidProducer table must be a bijection of 65536 uint16 values')
        inverse=[0]*65536
        for i,raw in enumerate(oidproducer_table):inverse[raw]=i
        hypotheses['oidproducer1020_raw_to_internal']={
            'matches':sum(inverse[r['raw_oid']]==r['vendor_code'] for r in confirmed),
            'observed':len(confirmed), 'proof':False,
            'note':'Other pen ecosystem/version; matching observations do NOT prove A8S firmware equivalence'}
    cross_book={}
    for r in confirmed:cross_book.setdefault(r['raw_oid'],set()).add((r['book_id'],r['vendor_code']))
    shared=[{'raw_oid':raw, 'contexts':len(values)} for raw,values in sorted(cross_book.items())
            if len({v for _,v in values})>1]
    return {'format':REPORT,'confirmed_observations':len(confirmed), 'total_observations':len(rows),
            'mapping_conflicts':conflicts,'cross_book_variation':shared,'hypotheses':hypotheses,
            'ready_for_vendor_staging':bool(confirmed) and not conflicts,
            'status':'EVIDENCE_ONLY_NO_NATIVE_PACK','a8s_compatible':'UNTESTED',
            'warning':'No NOB/NOD/NOS encoder, SDK or actual A8S raw-to-vendor map established.'}


def safe_audio(root: Path, rel_name: object) -> Path:
    if not isinstance(rel_name,str) or not rel_name or '\\' in rel_name:
        raise ValueError('Invalid audio path')
    rel=Path(rel_name)
    if rel.is_absolute() or '..' in rel.parts or any(part.startswith('.') for part in rel.parts):
        raise ValueError('Unsafe audio path')
    candidate=root/rel
    if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError('Missing or unsafe audio file')
    if candidate.suffix.lower()!='.mp3' or candidate.stat().st_size<300:
        raise ValueError('Require existing MP3 >=300 bytes')
    return candidate


def stage(book_dir: Path, binding_file: Path, evidence_file: Path, out: Path) -> dict:
    if out.exists():raise FileExistsError('Refusing to overwrite output directory')
    cfg=read_json(binding_file)
    regions_doc=read_json(book_dir/'regions.json')
    audio_doc=json.loads((book_dir/'audio_manifest.json').read_text(encoding='utf-8'))
    if cfg.get('format')!='ant-reader-a8s-bindings/1':raise ValueError('Invalid binding format')
    bid=book_id(cfg.get('book_id'))
    if book_dir.name!=bid:raise ValueError('book_dir and binding book_id differ')
    areas=regions_doc.get('regions')
    if not isinstance(areas,list) or not areas or not isinstance(audio_doc,list):
        raise ValueError('Missing prepared regions/audio manifest')
    ids=[x.get('logical_id') for x in areas]
    if any(not isinstance(x,str) for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Invalid logical IDs')
    binding=cfg.get('regions')
    if not isinstance(binding,dict) or set(binding)!=set(ids):
        raise ValueError('Binding must cover every prepared region')
    if not isinstance(cfg.get('cover'),dict):raise ValueError('Missing cover')
    raws=[oid(cfg['cover'].get('raw_oid'),'cover.raw_oid')]
    raws += [oid(binding[k].get('raw_oid'),f'{k}.raw_oid') for k in ids]
    if len(raws)!=len(set(raws)):raise ValueError('Duplicate raw OID in same book')
    by_audio={x['logical_id']:x for x in audio_doc}
    if set(by_audio)!=set(ids) or len(audio_doc)!=len(ids):raise ValueError('Audio manifest mismatch')
    rows=observations(evidence_file)
    report=analyze(rows)
    if report['mapping_conflicts']:raise ValueError('Contradictory observations; refusing to stage')
    confirmed={}
    for r in rows:
        if r['book_id']==bid and r['confirmed']:
            confirmed[(r['book_id'],r['raw_oid'])]=r['vendor_code']
    missing=[raw for raw in raws if (bid,raw) not in confirmed]
    if missing:raise ValueError('No confirmed vendor-client mapping for raw OID(s): '+str(missing))
    cover_vendor=confirmed[(bid,raws[0])]
    if len(set(confirmed[(bid,raw)] for raw in raws))!=len(raws):
        raise ValueError('Vendor codes collide within this book')
    entries=[]
    for i, logical in enumerate(ids):
        a=by_audio[logical]
        source=safe_audio(book_dir,a.get('path'))
        if a.get('audio_index')!=areas[i].get('audio_index'):
            raise ValueError('Audio index does not match region')
        raw=raws[i+1];vendor=confirmed[(bid,raw)]
        entries.append({'logical_id':logical,'raw_oid':raw,'vendor_code':vendor,
                        'source':source, 'audio_index':a['audio_index'], 'size':source.stat().st_size,
                        'sha256':sha256(source)})
    # All validation completed before creating any output directory.
    target=out/'vendor_client_input'
    target.mkdir(parents=True)
    for e in entries:shutil.copyfile(e['source'],target/f"{e['vendor_code']}.mp3")
    fields=['logical_id','book_id','entry_raw_oid','entry_vendor_code','raw_oid',
            'vendor_code','audio_index','audio_filename','audio_size','audio_sha256']
    with (out/'vendor_import_manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for e in entries:
            writer.writerow({'logical_id':e['logical_id'],'book_id':bid,'entry_raw_oid':raws[0],
                             'entry_vendor_code':cover_vendor,'raw_oid':e['raw_oid'],
                             'vendor_code':e['vendor_code'],'audio_index':e['audio_index'],
                             'audio_filename':f"{e['vendor_code']}.mp3",'audio_size':e['size'],
                             'audio_sha256':e['sha256']})
    manifest={'format':'ant-reader-a8s-vendor-handoff/1','book_id':bid,
              'entry_raw_oid':raws[0], 'entry_vendor_code':cover_vendor,
              'content_count':len(entries),'status':'INPUT_FOR_AUTHORIZED_VENDOR_CLIENT_ONLY',
              'resource_pack_generated':False,'installed_on_a8s':False,
              'a8s_compatible':'UNTESTED',
              'audio':[{'logical_id':e['logical_id'],'raw_oid':e['raw_oid'],
                        'vendor_code':e['vendor_code'],'sha256':e['sha256']} for e in entries]}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'README.txt').write_text(
        'This directory contains input for an authorized Xiaokedou vendor-client workflow.\n'
        'It is NOT an A8S-native NOB/NOD/NOS package and must NOT be installed as one.\n'
        'Verify vendor code semantics, book entrance, client version, and output by testing on your own A8S.\n',encoding='utf-8')
    return manifest


def write_report(out:Path,info:dict):
    if out.exists():raise FileExistsError(out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main(argv=None):
    p=argparse.ArgumentParser(description='A8S vendor code evidence & staged MP3 input; no native pack encoder')
    commands=p.add_subparsers(dest='cmd',required=True)
    m=commands.add_parser('mapping');m.add_argument('--observations',type=Path,required=True)
    m.add_argument('--oidproducer-table',type=Path);m.add_argument('--out',type=Path,required=True)
    s=commands.add_parser('stage');s.add_argument('--book-dir',type=Path,required=True)
    s.add_argument('--binding',type=Path,required=True);s.add_argument('--observations',type=Path,required=True)
    s.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        if a.cmd=='mapping':
            table=None
            if a.oidproducer_table:
                table=read_json(a.oidproducer_table).get('mapping')
            result=analyze(observations(a.observations),table);write_report(a.out,result)
        else:result=stage(a.book_dir,a.binding,a.observations,a.out)
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        p.error(str(e))
    print(json.dumps({'status':result['status'],'a8s_compatible':'UNTESTED'},ensure_ascii=False))

if __name__=='__main__':main()
