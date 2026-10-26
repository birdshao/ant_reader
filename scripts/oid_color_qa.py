#!/usr/bin/env python3
"""Experimental color/background OID2 QA on bounded RGB tiles.

Uses black-hat *local ink contrast* alongside original grayscale decoding.
This is an image-analysis experiment only; neither A8S compatibility nor real
paper recognition is established by this software. No original is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

try:
    from scripts import oid_large_page as large
    from scripts import oid_page_locator as locator
except ModuleNotFoundError:
    import oid_large_page as large
    import oid_page_locator as locator

SCHEMA = 'ant-reader-oid2-color-qa/1'
MODES = ('auto', 'gray', 'ink')


def grayscale(rgb: np.ndarray) -> np.ndarray:
    """Input is RGB or grayscale, always uint8. TIFF/PNG use RGB convention."""
    if rgb.dtype != np.uint8 or rgb.ndim not in (2, 3):
        raise ValueError('Expected uint8 grayscale or RGB image')
    if rgb.ndim == 2:
        return np.ascontiguousarray(rgb)
    if rgb.shape[-1] == 3:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if rgb.shape[-1] == 4:
        return cv2.cvtColor(rgb, cv2.COLOR_RGBA2GRAY)
    raise ValueError('Expected one, three, or four channels')


def enhance_ink(patch: np.ndarray, pitch_px: float) -> np.ndarray:
    """Estimate narrow dark microdots over locally varying color background.

    Black-hat morphology suppresses broad flat/dark backgrounds. For RGB,
    use the median of independent channel responses so an almost-zero color
    channel does not hide black ink; 4x contrast is a *lab heuristic*.
    """
    if not 6 <= pitch_px <= 48:
        raise ValueError('approx_pitch_px must be 6..48')
    gray = grayscale(patch)
    # Kernel spans a dot (1-2 source px) but should not span grid interval.
    size = max(5, int(round(pitch_px * .55)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    if patch.ndim == 2:
        residual = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    else:
        color = patch[:, :, :3]
        residuals = [cv2.morphologyEx(color[:, :, ch], cv2.MORPH_BLACKHAT, kernel)
                     for ch in range(3)]
        residual = np.median(np.stack(residuals, axis=2), axis=2).astype(np.uint8)
    # Saturated ink becomes black; flat colored background becomes white.
    return np.uint8(255 - np.minimum(residual.astype(np.uint16) * 4, 255))


def optical_metrics(patch: np.ndarray, pitch_px: float) -> dict:
    gray = grayscale(patch)
    if gray.size == 0:
        return {'valid': False}
    residual = enhance_ink(patch, pitch_px)
    # This is a background/ink texture *diagnostic*, not an optical MTF.
    dark = 255-residual
    return {'valid': True, 'mean_luma': round(float(gray.mean()), 2),
            'luma_std': round(float(gray.std()), 2),
            'dark_microtexture_fraction': round(float(np.mean(dark >= 80)), 5),
            'ink_contrast_p90': round(float(np.percentile(dark, 90)), 2)}


def analyze_page(page: np.ndarray, *, approx_pitch_px: float = 16.0,
                 tile_size: int = 1600, overlap: int = 720,
                 mode: str = 'auto', max_regions: int = 256,
                 per_tile_regions: int = 12) -> dict:
    w, h = large.ensure_shape(page)
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    if not 6 <= approx_pitch_px <= 48:
        raise ValueError('approx_pitch_px must be 6..48')
    if type(tile_size) is not int or not 400 <= tile_size <= 2000:
        raise ValueError('tile_size must be 400..2000')
    if type(overlap) is not int or not 160 <= overlap < tile_size or tile_size-overlap < 160:
        raise ValueError('overlap/step invalid: overlap>=160 and step>=160 required')
    if type(max_regions) is not int or not 1 <= max_regions <= large.MAX_FINAL_REGIONS:
        raise ValueError('max_regions must be 1..256')
    if type(per_tile_regions) is not int or not 1 <= per_tile_regions <= locator.MAX_REGIONS:
        raise ValueError('per_tile_regions must be 1..12')
    xs, ys = large.starts(w, tile_size, overlap), large.starts(h, tile_size, overlap)
    if len(xs)*len(ys) > large.MAX_TOTAL_TILES:
        raise ValueError('Too many tiles; increase tile size/step')
    detections = []
    skipped = 0
    truncated = 0
    mode_counts = {'gray': 0, 'ink': 0}
    processing_passes = 0
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            part = np.ascontiguousarray(page[y:min(h,y+tile_size), x:min(w,x+tile_size)])
            tile_idx = iy*len(xs)+ix
            # In auto mode enhanced ink evidence gets first refusal. Grayscale
            # is attempted ONLY when local-contrast mode found nothing, rather
            # than producing contradictory claims from the same image zone.
            modes = (('ink','gray') if mode=='auto' else (mode,))
            for name in modes:
                prepared = (grayscale(part) if name=='gray' else enhance_ink(part,approx_pitch_px))
                result = locator.analyze(prepared,approx_pitch_px=approx_pitch_px,max_regions=per_tile_regions)
                processing_passes += 1
                truncated += int(bool(result['locator_diagnostics']['truncated']))
                valid_in_pass = 0
                for hit in result['candidates']:
                    if hit['status'] != 'DECODED_RESEARCH_ONLY':
                        skipped += 1
                        continue
                    u,v,ww,hh = hit['bbox_px']
                    detections.append({**hit,'bbox_px':[u+x,v+y,ww,hh],
                                       'source_tile_index':tile_idx,'processing_mode':name})
                    mode_counts[name] += 1
                    valid_in_pass += 1
                if mode=='auto' and valid_in_pass:
                    break
    merged, merge_diag = large.merge_regions(detections, max_regions=max_regions)
    # The merge routine keeps conflicting IDs separate. Here *quarantine* any
    # overlapping different IDs instead of presenting incompatible positives.
    ambiguous=set()
    for i,a in enumerate(merged):
        for j in range(i+1,len(merged)):
            b=merged[j]
            if a['raw_oid']!=b['raw_oid'] and large.overlap_score(a,b)>=.2:
                ambiguous.update((i,j))
    results=[]
    for i,entry in enumerate(merged):
        if i in ambiguous:
            entry={**entry,'status':'AMBIGUOUS_OVERLAPPING_IDS','raw_oid':None,
                   'candidate_raw_oid':entry['raw_oid']}
        x,y,ww,hh=entry['bbox_px']
        roi=np.asarray(page[y:y+hh,x:x+ww])
        details=entry['best_decode_details']
        vote_fraction=details.get('majority_fraction') or 0
        coverage=details.get('coverage_fraction') or 0
        # Heuristic quality category with no implied calibrated failure rate.
        evidence=('HIGH_DIGITAL' if entry['raw_oid'] is not None and vote_fraction >= .95 and coverage >= .55
                  else 'MODERATE_DIGITAL' if entry['raw_oid'] is not None else 'UNCONFIRMED')
        results.append({**entry, 'optical_metrics':optical_metrics(roi,approx_pitch_px),
                        'evidence_grade':evidence})
    return {'schema': SCHEMA, 'kind':'color_tiled_page_qa','a8s_compatible':'UNTESTED',
            'source_size_px':[w,h],'mode':mode,'approx_pitch_px':approx_pitch_px,
            'tiling':{'tile_size_px':tile_size,'overlap_px':overlap,
                      'total_tiles':len(xs)*len(ys),'tiles_x':len(xs),'tiles_y':len(ys),
                      'processing_passes':processing_passes},
            'decoded_count':sum(r['raw_oid'] is not None for r in results),
            'rejected_candidates':skipped,'truncated_per_pass':truncated,
            'ambiguous_regions':len(ambiguous), 'mode_detection_counts':mode_counts,
            'regions':results, 'merge_diagnostics':merge_diag,
            'warning':'Synthetic/image-only QA; print outcome and Xiaokedou A8S compatibility NOT verified.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Color-background OID2 page QA; no A8S hardware validation')
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--mode',choices=MODES,default='auto')
    parser.add_argument('--approx-pitch-px',type=float,default=16.)
    parser.add_argument('--tile-size',type=int,default=1600)
    parser.add_argument('--overlap',type=int,default=720)
    parser.add_argument('--max-regions',type=int,default=large.MAX_FINAL_REGIONS)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--preview',type=Path)
    args=parser.parse_args(argv)
    if args.out.exists() or (args.preview and args.preview.exists()):
        parser.error('Refusing to overwrite report/preview')
    if args.preview and args.preview.resolve()==args.image.resolve():
        parser.error('Refusing to overwrite input')
    try:
        with large.open_page(args.image,preserve_color=True) as (page,reader):
            report=analyze_page(page,approx_pitch_px=args.approx_pitch_px,
                                tile_size=args.tile_size,overlap=args.overlap,
                                mode=args.mode,max_regions=args.max_regions)
            report['reader_mode']=reader
            report['source_file']=args.image.name
            report['source_sha256']=large.sha256_file(args.image)
            preview=large.preview_page(page,report) if args.preview else None
    except (ValueError,OSError,cv2.error) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.preview:
        args.preview.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(args.preview),preview):
            raise OSError('Cannot write preview image')
    print(json.dumps({'decoded':report['decoded_count'],'ambiguous':report['ambiguous_regions'],
                      'tiles':report['tiling']['total_tiles'],'a8s_compatible':'UNTESTED'},ensure_ascii=False))


if __name__=='__main__':
    main()
