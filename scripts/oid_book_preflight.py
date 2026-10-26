#!/usr/bin/env python3
"""Preflight the COMPLETE OID print-book binding before any physical print.

Checks binding/geometry/audio and pixel-exact Sonix-style OID2 candidates;
optionally evaluates operator-supplied paired scan crops. Never claims
Xiaokedou A8S recognition, native book-pack creation, or physical certification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import fitz
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import book_assembly as asm
from scripts import sonix_oid2

SCHEMA = 'ant-reader-oid2-book-preflight/1'
SCAN_SCHEMA = 'ant-reader-oid2-scan-manifest/1'
COVER_ID = '__cover__'
MAX_REGIONS = 256


def _safe_file(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or '\\' in rel:
        raise ValueError('Relative file path required')
    path = Path(rel)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Absolute/parent-traversal path rejected')
    result = (root / path).resolve()
    if not result.is_relative_to(root.resolve()) or not result.is_file() or result.is_symlink():
        raise ValueError(f'File missing or outside allowed directory: {rel}')
    return result


def _optical_asset(pattern: dict, *, force_sonix_oid2: bool = False) -> dict:
    """Report exact alpha + ink equivalence, not just an advertised code label."""
    code = pattern['raw_oid']
    uses_sonix = force_sonix_oid2 or pattern['source'].lstrip().lower().startswith('sonix oid2')
    report = {'raw_oid': code, 'source': pattern['source'], 'source_dpi': pattern['source_dpi'],
              'tile_mm': [round(x, 5) for x in pattern['tile_mm']],
              'pixel_dimensions': pattern['pixels'], 'png_sha256': pattern['sha256'],
              'a8s_tested_claim_in_binding': pattern['tested_on_a8s'],
              'codec': 'SONIX_STYLE_OID2' if uses_sonix else 'EXTERNAL_UNKNOWN'}
    if not uses_sonix:
        report['digital_code_status'] = 'EXTERNAL_CODEC_NOT_CHECKED'
        return report
    if code > 65535 or pattern['source_dpi'] not in (600, 1200):
        report['digital_code_status'] = 'CODE_OR_DPI_UNSUPPORTED_FOR_OID2'
        return report
    with Image.open(pattern['png']) as im:
        rgba = np.asarray(im.convert('RGBA'))
    w, h = pattern['pixels']
    reference = sonix_oid2.render(code, dpi=pattern['source_dpi'],
                                   width_mm=pattern['tile_mm'][0],
                                   height_mm=pattern['tile_mm'][1])
    expected = np.asarray(reference.getchannel('A'))
    alpha = rgba[:, :, 3]
    if expected.shape != alpha.shape:
        report['digital_code_status'] = 'PATTERN_DIMENSION_MISMATCH'
        return report
    # Source PNG is allowed arbitrary RGB in transparent pixels; visible ink
    # must be black, and its alpha mask must agree with known raw_oid pattern.
    differences = int(np.count_nonzero(alpha != expected))
    visible = alpha >= 128
    colored = int(np.count_nonzero(np.any(rgba[:, :, :3][visible] > 32, axis=1)))
    report.update({'pixel_alpha_mismatches': differences, 'nonblack_visible_pixels': colored,
                   'pixel_count': w * h,
                   'digital_code_status': ('EXACT_REFERENCE_MATCH' if differences == 0 and colored == 0
                                           else 'MISMATCH_REFERENCE_PATTERN')})
    return report


def _audio_entry(book_dir: Path, audio: dict) -> dict:
    result = {'logical_id': audio['logical_id'], 'audio_index': audio['audio_index'],
              'declared_audio_ready': audio.get('audio_ready') is True}
    try:
        path = _safe_file(book_dir, audio.get('path'))
        n = path.stat().st_size
        if n < 300:
            raise ValueError('Audio file shorter than 300 bytes')
        result.update({'status': 'PRESENT', 'size_bytes': n, 'sha256': asm.digest(path)})
    except (OSError, ValueError, TypeError):
        result['status'] = 'MISSING_OR_INVALID'
    return result


def _load_scans(path: Path | None, book_name: str, available_ids: set[str]):
    if path is None:
        return None, {}, None
    cfg = json.loads(path.read_text(encoding='utf-8'))
    if cfg.get('format') != SCAN_SCHEMA or cfg.get('book_id') != book_name:
        raise ValueError('Scan manifest format/book_id mismatch')
    if cfg.get('capture_kind') not in ('physical_scan', 'synthetic'):
        raise ValueError('Scan manifest capture_kind must be physical_scan or synthetic')
    mapping = cfg.get('regions')
    if not isinstance(mapping, dict) or not set(mapping) <= available_ids:
        raise ValueError('Unexpected scan region ID')
    validated = {}
    for name, item in mapping.items():
        if not isinstance(item, dict):
            raise ValueError('Scan entry must be an object')
        validated[name] = {'path': _safe_file(path.parent, item.get('image')),
                           'scan_dpi': item.get('scan_dpi')}
        if type(item.get('scan_dpi')) not in (float, int) or not math.isfinite(item['scan_dpi']) or not 300 <= item['scan_dpi'] <= 4800:
            raise ValueError('scan_dpi must be 300..4800')
    return cfg['capture_kind'], validated, asm.digest(path)


def _check_scan(entry: dict, pattern: dict, capture_kind: str, *, force_sonix_oid2: bool = False) -> dict:
    """The existing geometry analyzer requires a prealigned, same-size crop."""
    if not entry:
        return {'status': 'NOT_PROVIDED'}
    if not ((force_sonix_oid2 or pattern['source'].lower().lstrip().startswith('sonix oid2')) and
            pattern['raw_oid'] <= 65535 and pattern['source_dpi'] in (600, 1200)):
        return {'status': 'CODEC_NOT_CHECKABLE'}
    from scripts import oid_print_geometry as geometry
    import cv2
    path = entry['path']
    with Image.open(path) as hdr:
        width, height = hdr.size
        if width * height > geometry.MAX_PIXELS or min(width, height) < 160:
            raise ValueError(f'Scan crop for {path.name} outside 160px/4MP bounds')
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError('Cannot decode scan image')
    result, _ = geometry.analyze(img, raw_oid=pattern['raw_oid'],
                                  source_dpi=pattern['source_dpi'], scan_dpi=entry['scan_dpi'])
    return {'status': result['status'], 'scan_name': path.name,
            'scan_sha256': asm.digest(path), 'capture_kind': capture_kind,
            'geometry_status': result['status'],
            'matched_fraction': result.get('matched_fraction'),
            'pitch_deviation_percent': result.get('pitch_deviation_percent'),
            'missing_dots': result.get('missing_dots'),
            'extra_components': result.get('extra_components'),
            'data_symbol_checks': result.get('data_symbol_checks'),
            'physical_scan_a8s_verified': False}


def _validate_assembly_audit(path: Path | None, book_dir: Path, cover: dict,
                             regions: list[dict], patterns: dict, count_by_id: dict):
    if path is None:
        return {'status': 'NOT_PROVIDED'}
    cfg = json.loads(path.read_text(encoding='utf-8'))
    if cfg.get('book_id') != book_dir.name or cfg.get('format') != 'ant-reader-a8s-experiment/1':
        return {'status': 'MISMATCH', 'reason': 'Incorrect assembly audit identity'}
    pdf = path.parent / 'EXPERIMENTAL_print_book.pdf'
    if not pdf.is_file() or asm.digest(pdf) != cfg.get('pdf_sha256'):
        return {'status': 'MISMATCH', 'reason': 'Assembled PDF missing or SHA-256 differs'}
    if cfg.get('cover', {}).get('raw_oid') != cover['raw_oid'] or cfg['cover'].get('sha256') != cover['sha256']:
        return {'status': 'MISMATCH', 'reason': 'Cover code or PNG fingerprint differs'}
    if cfg['cover'].get('tile_count') != count_by_id[COVER_ID]:
        return {'status': 'MISMATCH', 'reason': 'Cover tile count differs'}
    indexed = {r.get('logical_id'): r for r in cfg.get('regions', [])}
    if set(indexed) != {r['logical_id'] for r in regions}:
        return {'status': 'MISMATCH', 'reason': 'Assembled region IDs differ'}
    for r in regions:
        key = r['logical_id']; item = indexed[key]
        if (item.get('raw_oid') != patterns[key]['raw_oid'] or
                item.get('pattern_sha256') != patterns[key]['sha256'] or
                item.get('tile_count') != count_by_id[key]):
            return {'status': 'MISMATCH', 'reason': f'Assembled code/image/tiles differ for {key}'}
    return {'status': 'MATCHED_AUDIT_AND_PDF_HASH', 'pdf_sha256': cfg['pdf_sha256']}


def analyze(book_dir: Path, binding: Path, *, scans: Path | None = None,
            assembly_audit: Path | None = None, margin_mm: float = 1.0,
            force_sonix_oid2: bool = False) -> dict:
    book_dir = Path(book_dir).resolve()
    binding = Path(binding).resolve()
    if not 0 <= margin_mm <= 5:
        raise ValueError('margin_mm must be 0..5')
    cover, patterns, regions, audio = asm.validate_binding(binding, book_dir)
    if not 1 <= len(regions) <= MAX_REGIONS:
        raise ValueError('Prepared book requires 1..256 regions')
    all_patterns = {COVER_ID: cover, **patterns}
    capture_kind, scan_entries, scan_sha = _load_scans(scans, book_dir.name, set(all_patterns))
    # No output files are created until all manifests have been validated.
    counts = {}
    with fitz.open(book_dir / 'artwork.pdf') as doc:
        cover_rect = fitz.Rect(60 * asm.MM, 91 * asm.MM, 150 * asm.MM, 181 * asm.MM)
        counts[COVER_ID] = len(asm.tile_positions(cover_rect, cover['tile_mm'], margin_mm))
        for region in regions:
            key = region['logical_id']
            page = region.get('page')
            if type(page) is not int or not 1 <= page <= len(doc):
                raise ValueError(f'Invalid artwork page: {key}')
            try:
                x, y, w, h = [region[k] for k in ('x_mm','y_mm','width_mm','height_mm')]
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0:
                    raise ValueError('Invalid region box')
            except KeyError as exc:
                raise ValueError('Incomplete region box') from exc
            rect=fitz.Rect(x*asm.MM,y*asm.MM,(x+w)*asm.MM,(y+h)*asm.MM)
            if not doc[page-1].rect.contains(rect):
                raise ValueError(f'Region outside artwork page: {key}')
            counts[key] = len(asm.tile_positions(rect,patterns[key]['tile_mm'],margin_mm))

    audios = {a['logical_id']:_audio_entry(book_dir,a) for a in audio}
    results = []
    for key, pattern in all_patterns.items():
        digital = _optical_asset(pattern,force_sonix_oid2=force_sonix_oid2)
        scan_report = _check_scan(scan_entries.get(key), pattern, capture_kind,force_sonix_oid2=force_sonix_oid2) if scan_entries else {'status':'NOT_PROVIDED'}
        item = {'logical_id': key, 'part': 'cover' if key == COVER_ID else 'content',
                'raw_oid': pattern['raw_oid'], 'full_tiles_in_pdf_region': counts[key],
                'optical_asset': digital, 'scan_qa': scan_report}
        if key != COVER_ID:
            item['audio'] = audios[key]
        results.append(item)
    assembly_check = _validate_assembly_audit(assembly_audit,book_dir,cover,regions,patterns,counts)
    bad_digital = [x['logical_id'] for x in results if x['optical_asset']['digital_code_status'] in
                   ('MISMATCH_REFERENCE_PATTERN','PATTERN_DIMENSION_MISMATCH','CODE_OR_DPI_UNSUPPORTED_FOR_OID2')]
    bad_scan = [x['logical_id'] for x in results if x['scan_qa']['status'] not in
                ('NOT_PROVIDED','CODEC_NOT_CHECKABLE','GEOMETRY_DIGITAL_MATCH')]
    external = [x['logical_id'] for x in results if x['optical_asset']['digital_code_status'] == 'EXTERNAL_CODEC_NOT_CHECKED']
    missing_audio = [k for k,v in audios.items() if v['status'] != 'PRESENT']
    incomplete = bool(external or missing_audio or (scans is not None and len(scan_entries)<len(all_patterns)))
    blocked = bool(bad_digital or bad_scan or assembly_check['status']=='MISMATCH')
    status = ('BLOCKED' if blocked else 'INCOMPLETE' if incomplete else 'READY_FOR_EXPERIMENT_PRINT')
    return {'schema': SCHEMA, 'book_id': book_dir.name,
            'status': status, 'status_scope': 'DIGITAL_PREFLIGHT_ONLY_A8S_UNVERIFIED',
            'a8s_compatible': 'UNTESTED', 'native_nob_generated': False,
            'binding_sha256': asm.digest(binding),
            'source_artwork_sha256': asm.digest(book_dir/'artwork.pdf'),
            'capture_kind': capture_kind, 'scan_manifest_sha256': scan_sha,
            'region_count': len(regions), 'checked_code_assets': len(results),
            'summary': {'blocked_digital_ids': bad_digital,'blocked_scan_ids': bad_scan,
                        'external_codec_unchecked_ids': external,
                        'missing_audio_ids': missing_audio,
                        'scans_supplied':len(scan_entries),'scan_expected':len(all_patterns),
                        'tiles_total':sum(counts.values())},
            'assembly_check': assembly_check,
            'regions':results,
            'warning': ('Preflight proves only inputs, geometric layout and optional paired digital/captured scans. '
                        'It does NOT establish physical printing yield, Xiaokedou A8S recognition, '
                        'or playable NOB/NOD/NOS resources.')}


def save(report: dict, json_path: Path, csv_path: Path | None = None):
    outputs=[json_path]+([csv_path] if csv_path is not None else [])
    for p in outputs:
        if p.exists() or p.is_symlink():
            raise FileExistsError(f'Refusing to overwrite report {p}')
    if len({p.resolve() for p in outputs}) != len(outputs):
        raise ValueError('JSON and CSV output paths must differ')
    for p in outputs: p.parent.mkdir(parents=True,exist_ok=True)
    json_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if csv_path is not None:
        with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
            cols=['logical_id','raw_oid','full_tiles_in_pdf_region','digital_code_status',
                  'pixel_alpha_mismatches','audio_status','scan_status','matched_fraction','pitch_deviation_percent']
            wr=csv.DictWriter(f,fieldnames=cols);wr.writeheader()
            for item in report['regions']:
                wr.writerow({'logical_id':item['logical_id'],'raw_oid':item['raw_oid'],
                             'full_tiles_in_pdf_region':item['full_tiles_in_pdf_region'],
                             'digital_code_status':item['optical_asset']['digital_code_status'],
                             'pixel_alpha_mismatches':item['optical_asset'].get('pixel_alpha_mismatches'),
                             'audio_status':item.get('audio',{}).get('status','COVER_NOT_APPLICABLE'),
                             'scan_status':item['scan_qa']['status'],
                             'matched_fraction':item['scan_qa'].get('matched_fraction'),
                             'pitch_deviation_percent':item['scan_qa'].get('pitch_deviation_percent')})


def main(argv=None):
    p=argparse.ArgumentParser(description='Digital A8S experiment book preflight; A8S compatibility unverified')
    p.add_argument('--book-dir',type=Path,required=True)
    p.add_argument('--binding',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--csv',type=Path)
    p.add_argument('--scans',type=Path,help='Optional manifest of prealigned single-code image crops')
    p.add_argument('--assembly-audit',type=Path)
    p.add_argument('--margin-mm',type=float,default=1.0)
    p.add_argument('--force-sonix-oid2',action='store_true',help='Explicitly interpret all assets as Sonix-style OID2')
    p.add_argument('--fail-on-issues',action='store_true')
    args=p.parse_args(argv)
    protected=[args.book_dir/'regions.json',args.book_dir/'audio_manifest.json',args.binding,
               args.book_dir/'artwork.pdf']+([args.scans] if args.scans else [])+([args.assembly_audit] if args.assembly_audit else [])
    output_paths=[args.out]+([args.csv] if args.csv else [])
    if any(pth.resolve() in {s.resolve() for s in protected} for pth in output_paths):
        p.error('Output path conflicts with input')
    if any(q.exists() or q.is_symlink() for q in output_paths):
        p.error('Refusing to overwrite report')
    try:
        report=analyze(args.book_dir,args.binding,scans=args.scans,
                       assembly_audit=args.assembly_audit,margin_mm=args.margin_mm,
                       force_sonix_oid2=args.force_sonix_oid2)
        save(report,args.out,args.csv)
    except (ValueError, OSError, KeyError, fitz.FileDataError, json.JSONDecodeError) as exc:
        p.error(str(exc))
    print(json.dumps({'status':report['status'],'code_assets':report['checked_code_assets'],
                      'book_id':report['book_id'],'a8s_compatible':'UNTESTED'},ensure_ascii=False))
    return 2 if args.fail_on_issues and report['status'] != 'READY_FOR_EXPERIMENT_PRINT' else 0


if __name__=='__main__':
    sys.exit(main())
