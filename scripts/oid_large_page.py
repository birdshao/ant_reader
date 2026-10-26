#!/usr/bin/env python3
"""Tiled multi-region OID2 scanning for large grayscale / RGB scanned pages.

Large pages MUST use contiguous, uncompressed 8-bit TIFF: tifffile.memmap avoids
loading the entire page. PNG/JPEG input is allowed only through a size-capped
in-memory decoder. The local OID2 scanner is a RESEARCH tool, not A8S proof.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
import tifffile

try:
    from scripts import oid_page_locator as locator
except ModuleNotFoundError:
    import oid_page_locator as locator

SCHEMA = 'ant-reader-oid2-large-page/1'
MAX_IN_MEMORY_PIXELS = 30_000_000
MAX_PAGE_PIXELS = 400_000_000
MAX_TOTAL_TILES = 600
MAX_FINAL_REGIONS = 256


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_shape(data: np.ndarray) -> tuple[int, int]:
    if data.dtype != np.uint8 or data.ndim not in (2, 3):
        raise ValueError('Page must be 8-bit grayscale or RGB/RGBA')
    if data.ndim == 3 and data.shape[2] not in (3, 4):
        raise ValueError('Page must have 1, 3, or 4 color channels')
    height, width = data.shape[:2]
    if min(height, width) < 160 or height * width > MAX_PAGE_PIXELS:
        raise ValueError('Page dimensions outside supported range (up to 400 MP)')
    return width, height


@contextmanager
def open_page(path: Path) -> Iterator[tuple[np.ndarray, str]]:
    """Read-only view; big TIFF is memory-mapped, never decoded at full size."""
    if not path.is_file() or path.is_symlink():
        raise ValueError('Input must be an existing non-symlink regular file')
    if path.suffix.lower() in ('.tif', '.tiff'):
        try:
            with tifffile.TiffFile(path) as handle:
                if len(handle.pages) != 1:
                    raise ValueError('Use a single-page TIFF; split multipage documents first')
                page = handle.pages[0]
                if page.dtype != np.dtype('uint8'):
                    raise ValueError('Only 8-bit TIFF scans supported')
                if page.photometric not in (tifffile.PHOTOMETRIC.MINISBLACK, tifffile.PHOTOMETRIC.RGB):
                    raise ValueError('Only standard grayscale (MINISBLACK) or RGB TIFF supported')
                if not page.is_memmappable:
                    raise ValueError('TIFF is compressed or non-contiguous; export uncompressed contiguous TIFF for bounded-memory scans')
            raw = tifffile.memmap(path, page=0, mode='r')
        except (OSError, tifffile.TiffFileError) as exc:
            raise ValueError(f'Invalid TIFF: {exc}') from exc
        ensure_shape(raw)
        try:
            yield raw, 'TIFF_READ_ONLY_MEMMAP'
        finally:
            # No changes are possible (mode='r'); release the mapping.
            del raw
    else:
        # An OpenCV imread would silently decode huge PNGs into RAM. Check
        # the dimensions via PIL headers before permitting full decode.
        from PIL import Image
        with Image.open(path) as img:
            width, height = img.size
            if width * height > MAX_IN_MEMORY_PIXELS:
                raise ValueError('PNG/JPEG exceeds 30 MP: convert to uncompressed 8-bit TIFF for memory-mapped analysis')
        raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise ValueError('OpenCV could not decode image')
        ensure_shape(raw)
        yield raw, 'IN_MEMORY_IMAGE'


def gray_tile(page: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
    crop = np.asarray(page[y:y+height, x:x+width])
    if crop.ndim == 2:
        return np.ascontiguousarray(crop)
    if crop.shape[2] == 3:
        # tifffile convention is RGB; OpenCV in-memory images are loaded as
        # grayscale before reaching here.
        return cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    return cv2.cvtColor(crop, cv2.COLOR_RGBA2GRAY)


def starts(length: int, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    step = tile_size - overlap
    positions = list(range(0, length - tile_size + 1, step))
    last = length - tile_size
    if positions[-1] != last:
        positions.append(last)
    return positions


def overlap_score(a: dict, b: dict) -> float:
    ax, ay, aw, ah = a['bbox_px']
    bx, by, bw, bh = b['bbox_px']
    x = max(0, min(ax+aw, bx+bw)-max(ax,bx))
    y = max(0, min(ay+ah, by+bh)-max(ay,by))
    small = min(aw*ah, bw*bh)
    return (x*y)/small if small else 0.0


def merge_regions(candidates: list[dict], *, max_regions: int = MAX_FINAL_REGIONS) -> tuple[list[dict], dict]:
    """Deduplicate tile-overlap discoveries ONLY for the SAME decoded OID.

    Different OIDs in overlapping boxes remain separate; conflicts are audited
    rather than silently choosing whichever had more votes.
    """
    if type(max_regions) is not int or not 1 <= max_regions <= MAX_FINAL_REGIONS:
        raise ValueError('max_regions must be 1..256')
    candidates = [c for c in candidates if c.get('status') == 'DECODED_RESEARCH_ONLY'
                  and type(c.get('raw_oid')) is int]
    parent = list(range(len(candidates)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    conflicts = []
    for i, a in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            b = candidates[j]
            share = overlap_score(a, b)
            if share < .20:
                continue
            if a['raw_oid'] != b['raw_oid']:
                if len(conflicts) < 30:
                    conflicts.append({'raw_oids': sorted([a['raw_oid'], b['raw_oid']]),
                                      'overlap_fraction_of_smaller': round(share, 4)})
                continue
            parent[find(j)] = find(i)
    grouped = {}
    for i, item in enumerate(candidates):
        grouped.setdefault(find(i), []).append(item)
    result = []
    for group in grouped.values():
        oid = group[0]['raw_oid']
        x0 = min(q['bbox_px'][0] for q in group)
        y0 = min(q['bbox_px'][1] for q in group)
        x1 = max(q['bbox_px'][0] + q['bbox_px'][2] for q in group)
        y1 = max(q['bbox_px'][1] + q['bbox_px'][3] for q in group)
        top = max(group, key=lambda q: (q.get('decode_details', {}).get('tiles_majority') or 0,
                                         q.get('decode_details', {}).get('coverage_fraction') or 0))
        result.append({'raw_oid': oid, 'status': 'DECODED_RESEARCH_ONLY',
                       'bbox_px': [x0, y0, x1-x0, y1-y0],
                       'observations': len(group),
                       'best_decode_details': top.get('decode_details', {}),
                       'source_tile_indices': sorted(set(g['source_tile_index'] for g in group if 'source_tile_index' in g))})
    result.sort(key=lambda z: (z['bbox_px'][1],z['bbox_px'][0],z['raw_oid']))
    truncated = len(result) > max_regions
    return result[:max_regions], {'raw_valid_candidates': len(candidates),
                                   'merged_decoded_regions': len(result),
                                   'truncated': truncated,
                                   'conflicting_overlaps': conflicts,
                                   'conflict_count_capped': len(conflicts) == 30}


def analyze_page(page: np.ndarray, *, approx_pitch_px: float = 16.0,
                 tile_size: int = 1600, overlap: int = 720,
                 max_regions: int = MAX_FINAL_REGIONS,
                 per_tile_regions: int = 12) -> dict:
    width, height = ensure_shape(page)
    if not 6 <= approx_pitch_px <= 48:
        raise ValueError('approx_pitch_px must be 6..48')
    if type(tile_size) is not int or not 400 <= tile_size <= 2000:
        raise ValueError('tile_size must be integer 400..2000')
    if type(overlap) is not int or not 160 <= overlap < tile_size:
        raise ValueError('overlap must be integer from 160 up to tile_size-1')
    if tile_size-overlap < 160:
        raise ValueError('Tile step must be at least 160 px to limit duplicate work')
    if type(per_tile_regions) is not int or not 1 <= per_tile_regions <= locator.MAX_REGIONS:
        raise ValueError('per_tile_regions must be 1..12')
    if type(max_regions) is not int or not 1 <= max_regions <= MAX_FINAL_REGIONS:
        raise ValueError('max_regions must be 1..256')

    xs = starts(width, tile_size, overlap)
    ys = starts(height, tile_size, overlap)
    if len(xs)*len(ys) > MAX_TOTAL_TILES:
        raise ValueError(f'Too many tiles ({len(xs)*len(ys)}); choose larger tile/step or smaller page')
    found=[]
    rejected=0
    incomplete=0
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            tw=min(tile_size,width-x)
            th=min(tile_size,height-y)
            part=gray_tile(page,x,y,tw,th)
            report=locator.analyze(part,approx_pitch_px=approx_pitch_px,max_regions=per_tile_regions)
            if report['locator_diagnostics']['truncated']:
                incomplete+=1
            for hit in report['candidates']:
                if hit['status']!='DECODED_RESEARCH_ONLY':
                    rejected+=1
                    continue
                u,v,w,h=hit['bbox_px']
                found.append({**hit, 'bbox_px': [u+x,v+y,w,h],
                              'source_tile_index':iy*len(xs)+ix})
            del part
    merged, merge_info=merge_regions(found,max_regions=max_regions)
    return {'schema': SCHEMA, 'kind': 'tiled_page_scan', 'a8s_compatible': 'UNTESTED',
            'source_size_px': [width,height], 'approx_pitch_px': approx_pitch_px,
            'tiling': {'tile_size_px': tile_size, 'overlap_px': overlap,
                       'tiles_x':len(xs),'tiles_y':len(ys),'total_tiles':len(xs)*len(ys),
                       'per_tile_candidates_rejected':rejected,
                       'tiles_with_candidate_truncation':incomplete},
            'candidate_count':merge_info['raw_valid_candidates'],
            'decoded_count':len(merged), 'regions':merged,
            'merge_diagnostics':merge_info,
            'warning': 'Research-only printed OID2 texture. No A8S optical/firmware or audio-package compatibility confirmed.'}


def preview_page(page: np.ndarray, report: dict, *, max_side: int = 1800) -> np.ndarray:
    if type(max_side) is not int or not 300 <= max_side <= 3000:
        raise ValueError('preview max_side must be 300..3000')
    w,h=ensure_shape(page)
    stride=max(1, math.ceil(max(w,h)/max_side))
    # Strided access on memmap touches only sparse source pages. No giant BGR
    # allocation; preview is a separate small image.
    sample=np.asarray(page[::stride, ::stride])
    if sample.ndim==2:
        thumb=cv2.cvtColor(np.ascontiguousarray(sample),cv2.COLOR_GRAY2BGR)
    elif sample.shape[2]==3:
        thumb=cv2.cvtColor(np.ascontiguousarray(sample),cv2.COLOR_RGB2BGR)
    else:
        thumb=cv2.cvtColor(np.ascontiguousarray(sample),cv2.COLOR_RGBA2BGR)
    for r in report['regions']:
        x,y,ww,hh=r['bbox_px']
        cv2.rectangle(thumb,(x//stride,y//stride),((x+ww)//stride,(y+hh)//stride),(0,150,0),2)
        cv2.putText(thumb,str(r['raw_oid']), (x//stride,max(18,y//stride-6)),
                    cv2.FONT_HERSHEY_SIMPLEX,.5,(0,110,0),1)
    return thumb


def main(argv=None):
    ap=argparse.ArgumentParser(description='Tiled large TIFF/PNG OID2 QA (A8S unverified)')
    ap.add_argument('--image',type=Path,required=True)
    ap.add_argument('--approx-pitch-px',type=float,default=16.)
    ap.add_argument('--tile-size',type=int,default=1600)
    ap.add_argument('--overlap',type=int,default=720)
    ap.add_argument('--max-regions',type=int,default=MAX_FINAL_REGIONS)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--preview',type=Path)
    args=ap.parse_args(argv)
    if args.out.exists() or (args.preview and args.preview.exists()):
        ap.error('Refusing to overwrite existing report or preview')
    try:
        with open_page(args.image) as (page, reader):
            report=analyze_page(page,approx_pitch_px=args.approx_pitch_px,
                                tile_size=args.tile_size,overlap=args.overlap,
                                max_regions=args.max_regions)
            report['reader_mode']=reader
            report['source_file']=args.image.name
            report['source_sha256']=sha256_file(args.image)
            preview=preview_page(page,report) if args.preview else None
    except (ValueError, OSError, cv2.error) as exc:
        ap.error(str(exc))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.preview:
        args.preview.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(args.preview),preview):
            raise OSError('Failed to save preview')
    print(json.dumps({'decoded_count':report['decoded_count'],
                      'tiles':report['tiling']['total_tiles'],'a8s_compatible':'UNTESTED'},ensure_ascii=False))


if __name__=='__main__':main()
