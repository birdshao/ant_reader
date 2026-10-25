#!/usr/bin/env python3
"""Assemble *experimental* A8S OID print pages and a vendor-neutral audio handoff.

Requires external verified provenance OID PNG assets; DOES NOT encode native A8S OIDs,
make NOB/NOD/NOS/DAB files, or claim hardware compatibility. OID tiles are repeated
without resizing; borders remain blank rather than emitting partial/warped codes.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

import fitz
from PIL import Image
from oid_lab import safe_source

MM = 72 / 25.4
MAX_TILES_PER_REGION = 400


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def read_pattern(book_binding: Path, obj: dict):
    if not isinstance(obj, dict):
        raise ValueError('Each OID binding must be an object')
    raw_oid = obj.get('raw_oid')
    if type(raw_oid) is not int or not 0 <= raw_oid <= 0xffffffff:
        raise ValueError('raw_oid must be a non-negative integer (not a bool)')
    if not isinstance(obj.get('source'), str) or len(obj['source'].strip()) < 4:
        raise ValueError('OID source must identify upstream/tool/version')
    dpi = obj.get('source_dpi')
    if type(dpi) is not int or dpi < 300 or dpi > 2400:
        raise ValueError('source_dpi must be an integer in 300..2400')
    png = safe_source(book_binding.parent, obj.get('image'))
    with Image.open(png) as img:
        if img.format != 'PNG' or img.mode != 'RGBA':
            raise ValueError(f'{png.name}: tiled overlays require RGBA transparent PNG')
        w, h = img.size
        if min(w, h) < 32:
            raise ValueError('OID PNG too small to be credible experiment tile')
        a_min, a_max = img.getchannel('A').getextrema()
        if a_min != 0 or a_max < 200:
            raise ValueError('OID tile must contain transparent and opaque pixels')
    width = w * 25.4 / dpi
    height = h * 25.4 / dpi
    if max(width, height) > 50:
        raise ValueError('OID tile larger than 50 mm; generate a smaller tile at source')
    return { 'raw_oid':raw_oid, 'source':obj['source'], 'source_dpi':dpi,
             'image':obj['image'], 'png':png, 'sha256':digest(png),
             'pixels':[w,h], 'tile_mm':[width,height], 'tested_on_a8s':obj.get('tested_on_a8s') is True }


def tile_positions(bounds: fitz.Rect, tile_mm, margin_mm=1.0):
    """Only full tiles, with no interpolation, padding or image clipping."""
    if not (0 <= margin_mm <= 5.0):
        raise ValueError('margin_mm must be 0..5')
    tw,th=(v*MM for v in tile_mm)
    avail_w,avail_h=bounds.width-2*margin_mm*MM,bounds.height-2*margin_mm*MM
    nx=math.floor((avail_w+1e-5)/tw)
    ny=math.floor((avail_h+1e-5)/th)
    if nx<1 or ny<1:
        raise ValueError(f'No full OID tile fits region {bounds}; tile {tile_mm}mm. Export a smaller tile.')
    if nx*ny>MAX_TILES_PER_REGION:
        raise ValueError('Too many repeated tiles; check PNG source_dpi and area')
    ox=bounds.x0+(bounds.width-nx*tw)/2
    oy=bounds.y0+(bounds.height-ny*th)/2
    return [fitz.Rect(ox+i*tw,oy+j*th,ox+(i+1)*tw,oy+(j+1)*th) for j in range(ny) for i in range(nx)]


def validate_binding(binding_path: Path, book_dir: Path):
    cfg=load_json(binding_path)
    regions=load_json(book_dir/'regions.json')['regions']
    audio=load_json(book_dir/'audio_manifest.json')
    if cfg.get('format')!='ant-reader-a8s-bindings/1':
        raise ValueError('Unsupported binding format')
    if cfg.get('book_id')!=book_dir.name:
        raise ValueError('Binding book_id does not match prepared book directory')
    expected={a['logical_id'] for a in regions}
    given=cfg.get('regions')
    if not isinstance(given, dict) or set(given)!=expected:
        raise ValueError(f'Bindings must cover every logical region exactly; missing={sorted(expected-set(given or {}))}, extra={sorted(set(given or {})-expected)}')
    cover=read_pattern(binding_path,cfg.get('cover'))
    binding_regions={k:read_pattern(binding_path,v) for k,v in given.items()}
    all_oids=[cover['raw_oid']]+[p['raw_oid'] for p in binding_regions.values()]
    if len(all_oids)!=len(set(all_oids)):
        raise ValueError('Duplicate optical raw_oid between cover and content regions')
    if len(audio)!=len(regions) or {a['logical_id'] for a in audio}!=expected:
        raise ValueError('Audio manifest incomplete or out of sync with regions')
    if any(a.get('audio_index')!=r.get('audio_index') for a in audio for r in regions if a['logical_id']==r['logical_id']):
        raise ValueError('Audio and PDF region logical indices differ')
    return cover,binding_regions,regions,audio


def compose(book_dir: Path,binding_path: Path,out_dir: Path,*,allow_missing_audio=False, margin_mm=1.0):
    cover,bindings,regions,audio=validate_binding(binding_path,book_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f'Refusing to overwrite nonempty handoff directory: {out_dir}')
    missing=[]
    for a in audio:
        rel=Path(a.get('path',''))
        if not rel.parts or rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'Unsafe audio manifest path for {a["logical_id"]}')
        src=(book_dir/rel).resolve()
        if not src.is_relative_to(book_dir.resolve()):
            raise ValueError('Audio file outside bookdir')
        if not src.is_file() or src.stat().st_size < 300:
            missing.append(a['logical_id'])
    if missing and not allow_missing_audio:
        raise ValueError('Missing audio: '+', '.join(missing)+'; prepare with --tts edge or supply originals, or --allow-missing-audio for draft')
    # Preflight ALL geometry before touching output files.
    with fitz.open(book_dir/'artwork.pdf') as base:
        geom={}
        for r in regions:
            if type(r.get('page')) is not int or not 1<=r['page']<=len(base):
                raise ValueError('Invalid region page number')
            x,y,w,h=(r[k] for k in ('x_mm','y_mm','width_mm','height_mm'))
            if min(w,h)<=0 or min(x,y)<0:
                raise ValueError('Invalid region bounding box')
            rect=fitz.Rect(x*MM,y*MM,(x+w)*MM,(y+h)*MM)
            if not base[r['page']-1].rect.contains(rect):
                raise ValueError('Point region outside art page')
            geom[r['logical_id']]=tile_positions(rect,bindings[r['logical_id']]['tile_mm'],margin_mm)
        cover_rect=fitz.Rect(60*MM,91*MM,150*MM,181*MM)
        entrance_tiles=tile_positions(cover_rect,cover['tile_mm'],margin_mm)

    out_dir.mkdir(parents=True,exist_ok=True)
    packaged=out_dir/'handoff_mp3_by_raw_oid'
    packaged.mkdir(exist_ok=True)
    report={'format':'ant-reader-a8s-experiment/1','book_id':book_dir.name,
            'status':'EXPERIMENTAL_NOT_A8S_VERIFIED',
            'WARNING':'Third-party codes do not imply A8S decoding. Resource pack is NOT generated.',
            'cover':{k:v for k,v in cover.items() if k!='png'},
            'regions':[], 'missing_audio':missing, 'resource_pack_status':'NOT_GENERATED',
            'print_instructions':'Print 100% actual size; do not fit-to-page; real device tests required'}
    pdf=fitz.open()
    entrance=pdf.new_page(width=210*MM,height=297*MM)
    entrance.draw_rect(entrance.rect,fill=(.985,.98,.963),color=None)
    entrance.insert_text((19*MM,26*MM),'A8S OID EXPERIMENT - BOOK ENTRANCE',fontsize=15)
    entrance.insert_text((19*MM,37*MM),'This page is NOT known to activate the Xiaokedou A8S.',fontsize=10,color=(.72,.15,.13))
    entrance.insert_text((19*MM,50*MM),f'Book: {book_dir.name}   Entrance OID: {cover["raw_oid"]}',fontsize=10)
    entrance.insert_text((19*MM,205*MM),'Read this entrance before trying content pages only after a matching book pack is installed.',fontsize=8)
    # Transparently repeat native PNG pixels; every tile retains its physical source pixel grid.
    for tile in entrance_tiles:
        entrance.insert_image(tile,filename=str(cover['png']),overlay=True,keep_proportion=False)
    report['cover']['tile_count']=len(entrance_tiles)
    with fitz.open(book_dir/'artwork.pdf') as art:
        pdf.insert_pdf(art)
    for i in range(1,len(pdf)):
        page=pdf[i]
        # Cover footer rendered in prepared art is no longer applicable; replace it truthfully.
        page.draw_rect(fitz.Rect(8*MM,page.rect.height-16*MM,page.rect.width-8*MM,page.rect.height-2*MM),
                       color=None,fill=(.984,.980,.965),overlay=True)
        page.insert_text((12*MM,page.rect.height-8*MM),
                         'EXPERIMENT: external printed codes; A8S recognition and audio mapping UNVERIFIED',
                         fontsize=7,color=(.7,.13,.12),overlay=True)
    aud_by_id={a['logical_id']:a for a in audio}
    with (out_dir/'vendor_handoff.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fieldnames=['book_id','entrance_raw_oid','region_id','content_raw_oid','audio_filename','audio_sha256','tile_count','source','pattern_sha256','a8s_status']
        writer=csv.DictWriter(f,fieldnames=fieldnames)
        writer.writeheader()
        for r in regions:
            key=r['logical_id']; b=bindings[key]; a=aud_by_id[key]
            src=book_dir/a['path']
            filename=f'{b["raw_oid"]}.mp3'
            if src.exists() and src.stat().st_size>=300:
                shutil.copyfile(src,packaged/filename)
                sha=digest(packaged/filename)
            else:
                filename='MISSING_'+filename
                sha=''
            tiles=geom[key]
            for rect in tiles:
                pdf[r['page']].insert_image(rect,filename=str(b['png']),overlay=True,keep_proportion=False)
            writer.writerow({'book_id':book_dir.name,'entrance_raw_oid':cover['raw_oid'],'region_id':key,
                             'content_raw_oid':b['raw_oid'],'audio_filename':filename,'audio_sha256':sha,
                             'tile_count':len(tiles),'source':b['source'],'pattern_sha256':b['sha256'],
                             'a8s_status':'UNVERIFIED'})
            report['regions'].append({'logical_id':key,'page_in_final_pdf':r['page']+1,'raw_oid':b['raw_oid'],
                                      'audio_filename':filename,'audio_sha256':sha,'tile_count':len(tiles),
                                      'tile_size_mm':[round(v,5) for v in b['tile_mm']],
                                      'pattern_sha256':b['sha256'],'source':b['source']})
    pdf.set_metadata({'title':f'{book_dir.name} - EXPERIMENTAL A8S OID TILE PRINT',
                      'subject':'Unverified A8S compatibility; no usable NOD/NOB/DAB generated'})
    output_pdf=out_dir/'EXPERIMENTAL_print_book.pdf'
    pdf.save(output_pdf,garbage=4,deflate=True)
    pdf.close()
    report['pdf_sha256']=digest(output_pdf)
    (out_dir/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    (out_dir/'README.txt').write_text(
        'EXPERIMENT ONLY. NOT a native A8S book pack.\n'
        'The PDF repeats supplied external optical code tiles without resampling.\n'
        'Audio files named by raw OID for manual/authorized vendor pack tools.\n'
        'DO NOT copy the ZIP to A8S expecting it to play. The audio-to-OID vendor pack must still be created.\n'
        'Printed OID values may be incompatible with A8S. Use real pen to validate.\n',encoding='utf-8')
    archive=out_dir/'vendor_handoff_NOT_PLAYABLE.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for entry in sorted(out_dir.rglob('*')):
            if entry.is_file() and entry!=archive and entry!=output_pdf:
                z.write(entry,entry.relative_to(out_dir))
    return report


def main():
    p=argparse.ArgumentParser(description='Assemble unverified A8S optical experiment and nonplayable vendor handoff')
    p.add_argument('--book-dir',type=Path,required=True)
    p.add_argument('--binding',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--margin-mm',type=float,default=1.0)
    p.add_argument('--allow-missing-audio',action='store_true',help='Creates incomplete draft handoff, clearly marks missing files')
    args=p.parse_args()
    try:
        info=compose(args.book_dir,args.binding,args.out,margin_mm=args.margin_mm,allow_missing_audio=args.allow_missing_audio)
        print(json.dumps({'status':info['status'],'pdf':str(args.out/'EXPERIMENTAL_print_book.pdf'),
                          'missing_audio':info['missing_audio'],'regions':len(info['regions'])},ensure_ascii=False))
    except (ValueError,FileNotFoundError,FileExistsError,KeyError) as e:
        p.exit(2,f'ERROR: {e}\n')

if __name__=='__main__':main()
