#!/usr/bin/env python3
"""Compare one aligned OID2 crop with its *known* expected dot lattice.

Research-only: designed for original-size, roughly upright, single-code crops
with the scan DPI supplied by the operator. This does not certify optical
readability on any pen or infer true physical DPI from pixel metadata.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from scripts import sonix_oid2
except ModuleNotFoundError:
    import sonix_oid2

SCHEMA = 'ant-reader-oid2-print-geometry/1'
MAX_PIXELS = 4_000_000


def expected_centers(raw_oid: int, dpi: int, width: int, height: int) -> np.ndarray:
    if dpi not in (600, 1200):
        raise ValueError('Source DPI must be 600 or 1200')
    if type(raw_oid) is not int or not 0 <= raw_oid <= 65535:
        raise ValueError('raw OID must be uint16')
    scale = dpi // 600
    period = 32 * scale
    margin = max(3, scale * 2)
    coords = []
    for ty in range(0, height, period):
        for tx in range(0, width, period):
            for x, y in sonix_oid2.tile_dots(raw_oid):
                cx = tx + x * scale + (scale - 1) / 2
                cy = ty + y * scale + (scale - 1) / 2
                if margin <= cx < width - margin and margin <= cy < height - margin:
                    coords.append((cx,cy))
    return np.array(coords, dtype=np.float32).reshape(-1,2)


def extract_components(gray: np.ndarray, *, source_dpi: int) -> tuple[np.ndarray, np.ndarray, dict]:
    """Detect bounded small ink components; reject text and large background marks."""
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError('Expected uint8 grayscale')
    # Only central grayscale black ink on pale backgrounds is supported here;
    # color-image background separation belongs to oid_color_qa.py.
    _, black = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV|cv2.THRESH_OTSU)
    count, labels, stats, cents = cv2.connectedComponentsWithStats(black,8)
    del labels
    scale = source_dpi // 600
    max_side = 4 * scale + 2
    max_area = 18 * scale * scale
    rows = stats[1:]
    valid = ((rows[:,cv2.CC_STAT_AREA]>=1) &
             (rows[:,cv2.CC_STAT_AREA]<=max_area) &
             (rows[:,cv2.CC_STAT_WIDTH]<=max_side) &
             (rows[:,cv2.CC_STAT_HEIGHT]<=max_side))
    points = np.asarray(cents[1:][valid],dtype=np.float32).reshape(-1,2)
    diameters = np.array([2*math.sqrt(area/math.pi) for area in rows[valid,cv2.CC_STAT_AREA]],dtype=np.float32)
    return points,diameters,{'threshold':int(cv2.threshold(gray,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)[0]),
                              'components_total':int(count-1),'dot_like_components':int(valid.sum())}


def match_points(expected: np.ndarray, actual: np.ndarray, *, transform: np.ndarray, radius: float):
    """One-to-one nearest matching using small spatial bins, not quadratic search."""
    if len(expected)==0 or len(actual)==0:
        return [],set()
    transformed = cv2.transform(expected[None,:,:],transform)[0]
    cell=max(2.,radius)
    lookup=defaultdict(list)
    for idx,(x,y) in enumerate(actual):
        lookup[(int(math.floor(x/cell)),int(math.floor(y/cell)))].append(idx)
    pairs=[]; assigned=set()
    # Match closest reference first to avoid accidental double-counting.
    options=[]
    for i,(x,y) in enumerate(transformed):
        ix,iy=int(math.floor(x/cell)),int(math.floor(y/cell))
        for py in (iy-1,iy,iy+1):
            for px in (ix-1,ix,ix+1):
                for j in lookup.get((px,py),()):
                    d2=float((actual[j,0]-x)**2+(actual[j,1]-y)**2)
                    if d2<=radius*radius:options.append((d2,i,j))
    options.sort(key=lambda z:z[0])
    used_reference=set()
    for d2,i,j in options:
        if i in used_reference or j in assigned:continue
        pairs.append((i,j,d2))
        used_reference.add(i);assigned.add(j)
    return pairs, assigned



def sync_centers(dpi: int, width: int, height: int) -> np.ndarray:
    """Only invariant frame dots; safe to use even when OID data differs."""
    scale=dpi//600
    period=32*scale
    margin=max(3,scale*2)
    result=[]
    for ty in range(0,height,period):
        for tx in range(0,width,period):
            for x,y in sonix_oid2.FRAME_DOTS:
                cx=tx+x*scale+(scale-1)/2
                cy=ty+y*scale+(scale-1)/2
                if margin<=cx<width-margin and margin<=cy<height-margin:
                    result.append((cx,cy))
    return np.asarray(result,dtype=np.float32).reshape(-1,2)


def refine_translation_on_sync(scanned: np.ndarray, initial: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Improve weak FFT registration by scoring *invariant* synchronization dots.

    Periodic optical texture can give a mediocre phase-correlation peak when the
    image is slightly rescaled. Probe only translations within +-8 scan pixels;
    this is not an arbitrary image registration algorithm.
    """
    predicted=cv2.transform(frame[None,:,:],initial)[0]
    # Bound amount of work even on the largest accepted single crop.
    if len(predicted)>800:
        predicted=predicted[np.linspace(0,len(predicted)-1,800,dtype=int)]
    h,w=scanned.shape
    best=(-float('inf'),0,0)
    for dy in range(-8,9):
        for dx in range(-8,9):
            pos=predicted+np.float32((dx,dy))
            selected=(pos[:,0]>=2)&(pos[:,0]<w-2)&(pos[:,1]>=2)&(pos[:,1]<h-2)
            if int(selected.sum())<60:continue
            pts=pos[selected]
            vx=pts[:,0].reshape(1,-1)
            vy=pts[:,1].reshape(1,-1)
            values=cv2.remap(scanned,vx,vy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
            ink=255-values.astype(np.float32)
            score=float(np.mean(ink))
            if score>best[0]:best=(score,dx,dy)
    fit=initial.copy()
    fit[0,2]+=best[1];fit[1,2]+=best[2]
    return fit


def register(reference: np.ndarray, scanned: np.ndarray, expected: np.ndarray,
             actual: np.ndarray, *, source_dpi: int) -> tuple[np.ndarray,dict]:
    """Bounded ~4% isotropic-scale search + translation, then robust affine fit.

    This deliberately refuses wide rotations/perspective: source and scan crops
    must already be oriented and approximately physically aligned.
    """
    height,width=reference.shape
    if scanned.shape!=reference.shape:
        raise ValueError('Scan and reference crops must have exactly the same pixel dimensions')
    source=cv2.GaussianBlur((255-reference).astype(np.float32),(0,0),.75)
    center=(width/2.,height/2.)
    trials=[]
    for s in np.linspace(.96,1.04,21):
        M=cv2.getRotationMatrix2D(center,0,1/float(s))
        normalized=cv2.warpAffine(scanned,M,(width,height),borderValue=255)
        target=cv2.GaussianBlur((255-normalized).astype(np.float32),(0,0),.75)
        (dx,dy),response=cv2.phaseCorrelate(source,target)
        if math.isfinite(response):trials.append((response,s,dx,dy))
    if not trials:raise ValueError('Registration failed: no valid phase correlation')
    response,s,dx,dy=max(trials)
    # Image coordinates are measured in scanned pixels. Recovered phase is in
    # the normalized (reference-resolution) coordinate system.
    init=np.float32([[s,0,center[0]*(1-s)+s*dx],
                     [0,s,center[1]*(1-s)+s*dy]])
    radius=max(2.5, source_dpi/600*1.9)
    init=refine_translation_on_sync(scanned,init,sync_centers(source_dpi,width,height))
    matches,_=match_points(expected,actual,transform=init,radius=radius)
    fitted=init
    if len(matches)>=30:
        ii=np.array([i for i,_,_ in matches],dtype=np.int32)
        jj=np.array([j for _,j,_ in matches],dtype=np.int32)
        refined,inliers=cv2.estimateAffinePartial2D(expected[ii],actual[jj],method=cv2.RANSAC,
                                                     ransacReprojThreshold=radius,maxIters=2000,
                                                     confidence=.99,refineIters=10)
        if refined is not None:
            a,b=float(refined[0,0]),float(refined[1,0])
            measured_scale=math.hypot(a,b)
            theta=math.degrees(math.atan2(b,a))
            if .94<=measured_scale<=1.06 and abs(theta)<=3.0 and int(inliers.sum())>=max(30,.65*len(matches)):
                fitted=np.asarray(refined,dtype=np.float32)
    scale_px=math.hypot(float(fitted[0,0]),float(fitted[1,0]))
    angle=math.degrees(math.atan2(float(fitted[1,0]),float(fitted[0,0])))
    return fitted,{'correlation_response':round(float(response),5),
                   'candidate_scale':round(float(s),5),
                   'affine_scale':round(scale_px,6),'affine_angle_deg':round(angle,4),
                   'affine_2x3':np.around(fitted,5).tolist()}



def decode_data_cells(actual: np.ndarray, fit: np.ndarray, *, dpi: int, size_px: tuple[int,int], expected_oid: int) -> dict:
    """Decode every fully visible primitive tile from *measured* dot centers.

    A high nearby-dot fraction is NOT sufficient: neighboring raw IDs can have
    almost the same pattern. We require observed displacement symbols and the
    real 2-bit checksum to reconstruct the printed raw OID per tile.
    """
    width,height=size_px
    scale=dpi//600
    period=32*scale
    margin=3*scale
    span=max(1.4,scale*.85)
    cell=max(2.,span)
    buckets=defaultdict(list)
    for idx,(x,y) in enumerate(actual):
        buckets[(int(math.floor(x/cell)),int(math.floor(y/cell)))].append(idx)

    def nearby(p):
        x,y=p
        ix=int(math.floor(x/cell));iy=int(math.floor(y/cell))
        best=None
        for yy in (iy-1,iy,iy+1):
            for xx in (ix-1,ix,ix+1):
                for j in buckets.get((xx,yy),()):
                    d=float(np.hypot(actual[j,0]-x,actual[j,1]-y))
                    if d<=span and (best is None or d<best[0]):best=(d,j)
        return best

    directions=((1,1),(-1,1),(-1,-1),(1,-1))
    counts=defaultdict(int)
    total=0;checksum_rejected=0;missing=0
    for y0 in range(0,height-26*scale-margin+1,period):
        for x0 in range(0,width-26*scale-margin+1,period):
            total+=1
            probe=[]
            for row in range(1,4):
                for col in range(1,4):
                    for dx,dy in directions:
                        probe.append((x0+(8*col+dx)*scale+(scale-1)/2,
                                      y0+(8*row+dy)*scale+(scale-1)/2))
            transformed=cv2.transform(np.asarray(probe,dtype=np.float32)[None,:,:],fit)[0]
            symbols=[]
            for start in range(0,36,4):
                matches=[nearby(p) for p in transformed[start:start+4]]
                possibles=[(dist_idx[0],k,dist_idx[1]) for k,dist_idx in enumerate(matches) if dist_idx is not None]
                if len(possibles)!=1:
                    symbols=[];break
                symbols.append(possibles[0][1])
            if len(symbols)!=9:
                missing+=1;continue
            try:
                decoded=sonix_oid2.decode_symbols(symbols)
            except ValueError:
                checksum_rejected+=1;continue
            counts[decoded]+=1
    valid=sum(counts.values())
    lead=sorted(counts.items(),key=lambda p:(-p[1],p[0]))
    return {'tiles_inspected':total,'tiles_checksum_valid':valid,
            'tiles_expected_oid':counts.get(expected_oid,0),
            'tiles_other_oid':valid-counts.get(expected_oid,0),
            'tiles_data_incomplete_or_ambiguous':missing,
            'tiles_checksum_rejected':checksum_rejected,
            'leading_decoded_oid':lead[0][0] if lead else None,
            'leading_decoded_votes':lead[0][1] if lead else 0,
            'decoded_oid_histogram':{str(k):v for k,v in lead[:8]}}


def analyze(scan: np.ndarray, *, raw_oid: int, source_dpi: int=1200,
            scan_dpi: float|None=None) -> tuple[dict,np.ndarray]:
    if source_dpi not in (600,1200):raise ValueError('source_dpi must be 600 or 1200')
    if scan_dpi is None:scan_dpi=float(source_dpi)
    if not 300<=scan_dpi<=4800 or not math.isfinite(scan_dpi):
        raise ValueError('scan_dpi must be 300..4800')
    if scan.ndim!=2 or scan.dtype!=np.uint8 or scan.size>MAX_PIXELS or min(scan.shape)<160:
        raise ValueError('Require uint8 grayscale, min dimension 160 and max 4 million pixels')
    h,w=scan.shape
    # An explicitly paired rectangle: same nominal physical dimensions and
    # initial orientation. Geometry is meaningless if scan is wrong-cropped.
    width_mm=w*25.4/source_dpi
    height_mm=h*25.4/source_dpi
    if not 1<=width_mm<=100 or not 1<=height_mm<=100:
        raise ValueError('Unsupported physical crop dimensions')
    rgba=sonix_oid2.render(raw_oid,dpi=source_dpi,width_mm=width_mm,height_mm=height_mm)
    ref=255-np.asarray(rgba.getchannel('A'))
    if ref.shape!=scan.shape:raise ValueError('Internal reference raster mismatch')
    expected=expected_centers(raw_oid,source_dpi,w,h)
    actual,diameters,component_audit=extract_components(scan,source_dpi=source_dpi)
    output={'schema':SCHEMA,'kind':'paired_crop_geometry','raw_oid_expected':raw_oid,
            'a8s_compatible':'UNTESTED','real_print_verified':False,
            'source_dpi':source_dpi,'scan_dpi_assumed':scan_dpi,
            'crop_px':[w,h],'expected_dots':len(expected),
            'observed_dotlike_components':len(actual),'component_detection':component_audit,
            'warning':'Physical units depend on accurate scan DPI and cropping; this is NOT A8S recognition certification.'}
    overlay=cv2.cvtColor(scan,cv2.COLOR_GRAY2BGR)
    if len(actual)<30:
        output.update({'status':'INSUFFICIENT_DOTS','matched_dots':0,'missing_dots':len(expected),
                       'extra_components':len(actual),'estimated_pitch_mm':None})
        return output,overlay
    fit,reg=register(ref,scan,expected,actual,source_dpi=source_dpi)
    radius=max(2.4,source_dpi/600*1.6)
    pairs,used=match_points(expected,actual,transform=fit,radius=radius)
    matched=len(pairs);coverage=matched/max(1,len(expected))
    avg_error=math.sqrt(sum(d2 for _,_,d2 in pairs)/matched) if matched else None
    measured_diameter=float(np.median(diameters[[j for _,j,_ in pairs]])) if matched else None
    # 32 logical source pixels between repeated primitive tiles and eight source
    # pixels between sync-grid dots. The physical unit depends on scan DPI.
    measured_pitch_px=32*(source_dpi//600)*reg['affine_scale']
    effective_mm=measured_pitch_px*25.4/scan_dpi
    nominal_mm=32*25.4/600.
    missing=len(expected)-matched
    # Ignore edge components excluded from the reference comparison window.
    margin=max(3,source_dpi//600*2)
    inverse=cv2.invertAffineTransform(fit)
    source_coordinates=cv2.transform(actual[None,:,:],inverse)[0]
    interior=(source_coordinates[:,0]>=margin)&(source_coordinates[:,0]<w-margin)&(source_coordinates[:,1]>=margin)&(source_coordinates[:,1]<h-margin)
    extra=sum(bool(interior[j]) for j in range(len(actual)) if j not in used)
    tile_checks=decode_data_cells(actual,fit,dpi=source_dpi,size_px=(w,h),expected_oid=raw_oid)
    # A mismatch in OID is especially dangerous because 7/16 sync points remain
    # identical. Never mark poor match as 'pass'.
    count=tile_checks['tiles_expected_oid']
    valid=tile_checks['tiles_checksum_valid']
    total=tile_checks['tiles_inspected']
    majority=(count/max(1,valid))
    if valid>=6 and tile_checks['leading_decoded_oid']!=raw_oid and tile_checks['leading_decoded_votes']/valid>=.75:
        status='MISMATCH_EXPECTED_CODE'
    elif (coverage>=.85 and reg['correlation_response']>=.15 and avg_error is not None
          and avg_error<=radius*.7 and count>=6 and majority>=.8 and count>=.4*max(1,total)):
        status='GEOMETRY_DIGITAL_MATCH'
    else:
        status='INSUFFICIENT_GEOMETRIC_MATCH' 
    output.update({'status':status,'matched_dots':matched,'missing_dots':missing,
                   'extra_components':extra,'matched_fraction':round(coverage,5),
                   'root_mean_square_centroid_error_px':round(avg_error,4) if avg_error is not None else None,
                   'median_dot_diameter_px':round(measured_diameter,4) if measured_diameter else None,
                   'median_dot_diameter_mm_assumed':round(measured_diameter*25.4/scan_dpi,5) if measured_diameter else None,
                   'estimated_pitch_mm':round(effective_mm,5),'nominal_pitch_mm':round(nominal_mm,5),
                   'pitch_deviation_percent':round(100*(effective_mm/nominal_mm-1),3),
                   'registration':reg,'data_symbol_checks':tile_checks})
    projected=cv2.transform(expected[None,:,:],fit)[0]
    matched_ref={i for i,_,_ in pairs}
    for i,(x,y) in enumerate(projected):
        if not (0<=x<w and 0<=y<h):continue
        cv2.circle(overlay,(int(round(x)),int(round(y))),2,(0,170,0) if i in matched_ref else (0,0,255),1)
    return output,overlay


def main(argv=None):
    p=argparse.ArgumentParser(description='Pair known OID2 reference crop against aligned scan; A8S unverified')
    p.add_argument('--image',type=Path,required=True,help='8-bit grayscale crop, near-upright, known printed code')
    p.add_argument('--raw-oid',type=int,required=True)
    p.add_argument('--source-dpi',type=int,choices=(600,1200),default=1200)
    p.add_argument('--scan-dpi',type=float,default=None)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--overlay',type=Path)
    a=p.parse_args(argv)
    if a.out.exists() or (a.overlay and a.overlay.exists()):p.error('Refusing to overwrite existing output')
    if a.overlay and a.overlay.resolve()==a.image.resolve():p.error('Refusing to overwrite source image')
    if not a.image.is_file() or a.image.is_symlink():p.error('Require a local nonsymlink image')
    # Inspect dimensions before letting OpenCV decode potentially huge PNG/JPG.
    try:
        with Image.open(a.image) as header:
            iw,ih=header.size
            if iw*ih>MAX_PIXELS or min(iw,ih)<160:
                p.error('Image crop outside supported dimensions (160px minimum, 4 MP maximum)')
    except (OSError,ValueError) as exc:
        p.error(f'Cannot inspect image header: {exc}')
    scan=cv2.imread(str(a.image),cv2.IMREAD_GRAYSCALE)
    if scan is None:p.error('Cannot decode scan image')
    try:report,overlay=analyze(scan,raw_oid=a.raw_oid,source_dpi=a.source_dpi,scan_dpi=a.scan_dpi)
    except (ValueError,cv2.error) as exc:p.error(str(exc))
    report['source_file']=a.image.name
    report['source_sha256']=hashlib.sha256(a.image.read_bytes()).hexdigest()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.overlay:
        a.overlay.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(a.overlay),overlay):raise OSError('Overlay PNG write failed')
    print(json.dumps({'status':report['status'],'matched_fraction':report.get('matched_fraction'),
                      'a8s_compatible':'UNTESTED'},ensure_ascii=False))


if __name__=='__main__':main()
