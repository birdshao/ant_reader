#!/usr/bin/env python3
"""Experimental vector-preserving OID book assembly (NOT A8S code generation).

Import externally produced, OID-only PDF crops as native PDF form objects,
not through image rasterization/thresholding. Never assumes that supplied raw
OID values, PDF artwork, or handoff files work on Xiaokedou A8S.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import fitz
from book_assembly import MM, MAX_TILES_PER_REGION, tile_positions

SCHEMA = 'ant-reader-a8s-vector-bindings/1'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def inside(base: Path, value: str, extension: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('Unsafe relative source path')
    root = base.resolve()
    target = (root / value).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.suffix.lower() != extension:
        raise ValueError(f'Missing or unsafe {extension} source: {value}')
    return target


def rect_mm(value) -> fitz.Rect:
    if not isinstance(value, list) or len(value) != 4 or any(type(x) not in (int, float) for x in value):
        raise ValueError('rect_mm must be [x,y,width,height] in mm')
    x, y, w, h = value
    if min(x, y) < 0 or not (0 < w <= 50 and 0 < h <= 50):
        raise ValueError('OID crop must be within a positive 50 mm square')
    return fitz.Rect(x*MM, y*MM, (x+w)*MM, (y+h)*MM)


def load_sources(binding_path: Path, cfg: dict, stack: ExitStack, allow_raster: bool):
    """Validate every OID PDF crop before producing output files."""
    opened = {}
    candidates = [cfg.get('cover')] + list(cfg['regions'].values())
    result = []
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError('OID vector binding must be an object')
        oid = item.get('raw_oid')
        if type(oid) is not int or oid < 0 or oid > 0xffffffff:
            raise ValueError('raw_oid must be a nonnegative 32-bit integer')
        if not isinstance(item.get('source'), str) or len(item['source'].strip()) < 5:
            raise ValueError('source must describe original encoder and version')
        path = inside(binding_path.parent, item.get('pdf'), '.pdf')
        if path not in opened:
            opened[path] = stack.enter_context(fitz.open(path))
        doc = opened[path]
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError('Encrypted/non-PDF source is not supported')
        idx = item.get('page')
        if type(idx) is not int or not 1 <= idx <= len(doc):
            raise ValueError('Invalid 1-based source page')
        crop = rect_mm(item.get('rect_mm'))
        page = doc[idx-1]
        if not page.rect.contains(crop):
            raise ValueError('OID crop outside source PDF page')
        # OID-only crops, not text labels or screenshots; fail safely on ambiguity.
        for block in page.get_text('blocks'):
            if block[6] == 0 and fitz.Rect(block[:4]).intersects(crop):
                raise ValueError('Text intersects OID crop; select code-only area')
        drawings = [d for d in page.get_drawings() if fitz.Rect(d['rect']).intersects(crop)]
        raster = bool(page.get_images(full=True))
        if raster and not allow_raster:
            raise ValueError('Source page contains raster images; use --allow-raster-source only for explicit experiments')
        if not drawings and not raster:
            raise ValueError('No drawable optical marks found in PDF crop')
        # Large painted backgrounds would cover children's underlying artwork.
        for d in drawings:
            box = fitz.Rect(d['rect']) & crop
            if d.get('fill') is not None and box.get_area() > 0.2 * crop.get_area():
                raise ValueError('Opaque/background fill in crop; transparent OID-only source required')
        result.append({'raw_oid': oid, 'source': item['source'], 'pdf': path,
                       'page_index': idx-1, 'crop': crop, 'document': doc,
                       'source_sha256': sha256(path), 'raster_present': raster,
                       'vector_drawings_in_crop': len(drawings),
                       'tile_mm': [crop.width/MM, crop.height/MM]})
    values = [v['raw_oid'] for v in result]
    if len(set(values)) != len(values):
        raise ValueError('Duplicate raw_oid between entrance and content regions')
    return result


def assemble(book_dir: Path, binding_path: Path, out_dir: Path,
             *, allow_missing_audio=False, allow_raster_source=False, margin_mm=1.0):
    book_dir = book_dir.resolve(); binding_path = binding_path.resolve(); out_dir = out_dir.resolve()
    cfg = json.loads(binding_path.read_text(encoding='utf-8'))
    regions = json.loads((book_dir/'regions.json').read_text(encoding='utf-8'))['regions']
    audio = json.loads((book_dir/'audio_manifest.json').read_text(encoding='utf-8'))
    expected = {r['logical_id'] for r in regions}
    if cfg.get('format') != SCHEMA or cfg.get('book_id') != book_dir.name:
        raise ValueError('Binding schema/book_id mismatch')
    if not isinstance(cfg.get('regions'), dict) or set(cfg['regions']) != expected:
        raise ValueError('Every logical region must be bound exactly once')
    if len(audio) != len(regions) or {a['logical_id'] for a in audio} != expected:
        raise ValueError('Audio manifest must match all regions')
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError('Refusing to overwrite nonempty output directory')
    by_audio = {a['logical_id']: a for a in audio}
    missing_audio = []
    for r in regions:
        a = by_audio[r['logical_id']]
        if a['audio_index'] != r['audio_index']:
            raise ValueError('Logical audio index mismatch')
        src = inside(book_dir, a['path'], '.mp3') if (book_dir/a['path']).exists() else None
        if src is None or src.stat().st_size < 300:
            missing_audio.append(r['logical_id'])
    if missing_audio and not allow_missing_audio:
        raise ValueError('Missing audio: '+', '.join(missing_audio))

    with ExitStack() as stack:
        patterns = load_sources(binding_path, cfg, stack, allow_raster_source)
        cover, pattern_regions = patterns[0], dict(zip(cfg['regions'].keys(), patterns[1:]))
        with fitz.open(book_dir/'artwork.pdf') as artwork:
            tiles_by_region = {}
            for r in regions:
                n = r['page']; x,y,w,h = [r[k] for k in ('x_mm','y_mm','width_mm','height_mm')]
                if type(n) is not int or not 1 <= n <= len(artwork) or min(x,y) < 0 or min(w,h) <= 0:
                    raise ValueError('Invalid prepared book page or rectangle')
                bounds = fitz.Rect(x*MM,y*MM,(x+w)*MM,(y+h)*MM)
                if not artwork[n-1].rect.contains(bounds):
                    raise ValueError('Region outside artwork')
                tiles_by_region[r['logical_id']] = tile_positions(bounds,pattern_regions[r['logical_id']]['tile_mm'],margin_mm)
            entrance_bounds = fitz.Rect(60*MM,95*MM,150*MM,185*MM)
            entrance_tiles = tile_positions(entrance_bounds, cover['tile_mm'],margin_mm)
            out_dir.mkdir(parents=True, exist_ok=True)
            pdf = stack.enter_context(fitz.open())
            first = pdf.new_page(width=210*MM,height=297*MM)
            first.insert_text((15*MM,25*MM),'OID VECTOR SOURCE EXPERIMENT - NO A8S VALIDATION',fontsize=13)
            first.insert_text((15*MM,38*MM),f'Entrance raw OID: {cover["raw_oid"]}',fontsize=11)
            first.insert_text((15*MM,205*MM),'No matching A8S resource package was generated.',fontsize=9)
            for tile in entrance_tiles:
                first.show_pdf_page(tile, cover['document'], cover['page_index'],
                                    clip=cover['crop'], keep_proportion=False, overlay=True)
            pdf.insert_pdf(artwork)
            for r in regions:
                pat = pattern_regions[r['logical_id']]
                for tile in tiles_by_region[r['logical_id']]:
                    pdf[r['page']].show_pdf_page(tile, pat['document'], pat['page_index'],
                                                clip=pat['crop'], keep_proportion=False, overlay=True)
            pdf.set_metadata({'title':'EXPERIMENTAL VECTORED OID PRINT - NOT A8S VERIFIED',
                              'subject':'No native A8S point-reading pack generated'})
            target = out_dir/'EXPERIMENTAL_vector_book.pdf'
            pdf.save(target, garbage=4, deflate=True)
        handoff = out_dir/'mp3_by_raw_oid'; handoff.mkdir(exist_ok=True)
        csv_path = out_dir/'vendor_handoff.csv'
        rows = []
        for r in regions:
            pat = pattern_regions[r['logical_id']]; a = by_audio[r['logical_id']]
            audio_rel = a['path']; src = book_dir/audio_rel
            name = f'{pat["raw_oid"]}.mp3' if src.is_file() and src.stat().st_size >= 300 else ''
            if name:
                shutil.copyfile(src, handoff/name)
            rows.append({'logical_id':r['logical_id'], 'entrance_raw_oid':cover['raw_oid'],
                         'content_raw_oid':pat['raw_oid'], 'audio_file':name,
                         'tile_count':len(tiles_by_region[r['logical_id']]),
                         'source_pdf_sha256':pat['source_sha256'],
                         'compatibility':'NOT_TESTED_ON_A8S'})
        with csv_path.open('w',newline='',encoding='utf-8-sig') as file:
            fields = list(rows[0]); writer = csv.DictWriter(file,fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        def audit(pat, count):
            return {'raw_oid':pat['raw_oid'], 'source':pat['source'],
                    'source_pdf':str(pat['pdf'].relative_to(binding_path.parent)),
                    'pdf_sha256':pat['source_sha256'], 'source_page':pat['page_index']+1,
                    'crop_mm':[round(x/MM,5) for x in (pat['crop'].x0,pat['crop'].y0,pat['crop'].width,pat['crop'].height)],
                    'source_has_raster':pat['raster_present'],
                    'vector_drawings_in_crop':pat['vector_drawings_in_crop'],
                    'tile_count':count}
        report = {'format':'ant-reader-vector-experiment/1','status':'UNVERIFIED_A8S',
                  'printed_pdf_sha256':sha256(target), 'resource_pack':'NOT_GENERATED',
                  'entrance':audit(cover,len(entrance_tiles)),
                  'regions':[{'logical_id':r['logical_id'],**audit(pattern_regions[r['logical_id']],len(tiles_by_region[r['logical_id']]))} for r in regions],
                  'missing_audio':missing_audio,
                  'warning':'Vector PDF reuse avoids intermediate PNG rasterization but does NOT ensure print fidelity, raw OID compatibility, or A8S playback.'}
        (out_dir/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (out_dir/'README.txt').write_text('EXPERIMENTAL PDF ONLY. NOT AN A8S RESOURCE PACK.\nDo not install MP3 directory as a point-reading package.\nPrint 100%% at original size and validate with the physical pen.\n',encoding='utf-8')
        return report


def main():
    p=argparse.ArgumentParser(description='Experimental vector PDF OID layer import; not a native A8S encoder')
    p.add_argument('--book-dir', type=Path, required=True)
    p.add_argument('--binding', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--allow-missing-audio', action='store_true')
    p.add_argument('--allow-raster-source', action='store_true')
    p.add_argument('--margin-mm', type=float, default=1.0)
    args=p.parse_args()
    try:
        report=assemble(args.book_dir,args.binding,args.out,
                        allow_missing_audio=args.allow_missing_audio,
                        allow_raster_source=args.allow_raster_source,margin_mm=args.margin_mm)
        print(json.dumps({'status':report['status'], 'pdf':str(args.out/'EXPERIMENTAL_vector_book.pdf'),
                          'regions':len(report['regions'])},ensure_ascii=False))
    except (ValueError, KeyError, FileNotFoundError, FileExistsError) as exc:
        p.exit(2,f'ERROR: {exc}\n')

if __name__=='__main__': main()