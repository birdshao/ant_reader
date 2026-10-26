#!/usr/bin/env python3
"""Locate multiple Sonix-style OID2 zones on one image, then decode each crop.

Research tool, not Xiaokedou A8S compatibility proof. Primarily for separated
black-on-white printed OID2 regions with sufficient microscopic resolution.
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
    from scripts import oid_markerless
except ModuleNotFoundError:
    import oid_markerless

SCHEMA = 'ant-reader-oid2-page-locator/1'
MAX_IMAGE_PIXELS = 30_000_000
MAX_REGIONS = 12


def dots_map(gray: np.ndarray, pitch_px: float):
    """Find small dark connected components, accumulating dot density on a grid."""
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError('Expected uint8 grayscale image')
    if not 6 <= pitch_px <= 48:
        raise ValueError('approx-pitch-px must be 6..48')
    h, w = gray.shape
    if h*w > MAX_IMAGE_PIXELS:
        raise ValueError('Image exceeds 30 MP limit; use crop/tiled scans')
    if min(h,w)<160:
        raise ValueError('Input image too small')
    threshold=int(np.clip(np.percentile(gray,7),55,175))
    dark=np.uint8(gray<threshold)
    n,labels,stats,centroids=cv2.connectedComponentsWithStats(dark,8,cv2.CV_32S)
    del labels
    max_d=max(3,int(math.ceil(pitch_px*0.33)))
    max_area=max(4,int(math.ceil((pitch_px/8.0)**2*7)))
    cell=max(24,int(round(pitch_px*2.0)))
    gw=(w+cell-1)//cell; gh=(h+cell-1)//cell
    grid=np.zeros((gh,gw),dtype=np.int32)
    st=stats[1:]
    min_area=2 if pitch_px>=12 else 1
    eligible=(st[:,cv2.CC_STAT_AREA]>=min_area)&(st[:,cv2.CC_STAT_AREA]<=max_area)&(st[:,cv2.CC_STAT_WIDTH]<=max_d)&(st[:,cv2.CC_STAT_HEIGHT]<=max_d)
    pos=centroids[1:][eligible]
    if len(pos):
        cx=np.minimum((pos[:,0]//cell).astype(np.int32),gw-1)
        cy=np.minimum((pos[:,1]//cell).astype(np.int32),gh-1)
        np.add.at(grid,(cy,cx),1)
    active=np.uint8(grid>=3)
    return active,grid,cell,{'dark_threshold':threshold,'small_components':int(eligible.sum()),'grid_cell_px':cell}


def locate_candidates(gray:np.ndarray,*,approx_pitch_px:float=16.0,max_regions:int=MAX_REGIONS):
    if type(max_regions) is not int or not 1<=max_regions<=MAX_REGIONS:
        raise ValueError('max_regions must be 1..12')
    active,counts,cell,params=dots_map(gray,approx_pitch_px)
    connected=cv2.morphologyEx(active,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(connected,8)
    found=[]
    h,w=gray.shape
    for label in range(1,n):
        x,y,gw,gh,area=(int(v) for v in stats[label])
        if min(gw,gh)<3 or area<12:
            continue
        occupied=int(np.count_nonzero(active[y:y+gh,x:x+gw]))
        if occupied<10 or occupied/(gw*gh)<0.60:
            continue
        x0=max(0,(x-1)*cell);y0=max(0,(y-1)*cell)
        x1=min(w,(x+gw+1)*cell);y1=min(h,(y+gh+1)*cell)
        if min(x1-x0,y1-y0)<200:
            continue
        if max(x1-x0,y1-y0)>1600 or (x1-x0)*(y1-y0)>2_000_000:
            continue
        found.append({'bbox_px':[x0,y0,x1-x0,y1-y0],
                      'dot_grid_cells':occupied,'density_fraction':round(occupied/(gw*gh),4)})
    found.sort(key=lambda z:(z['bbox_px'][1],z['bbox_px'][0]))
    return found[:max_regions],dict(params,segmented_candidates=len(found),truncated=len(found)>max_regions)


def analyze(gray:np.ndarray,*,approx_pitch_px:float=16.,max_regions:int=MAX_REGIONS):
    candidates,diagnostics=locate_candidates(gray,approx_pitch_px=approx_pitch_px,max_regions=max_regions)
    result=[]
    for item in candidates:
        x,y,w,h=item['bbox_px']
        item={**item,'decode_crop_px':[x,y,w,h]}
        try:
            decode,_=oid_markerless.decode_markerless(gray[y:y+h,x:x+w],approx_pitch_px=approx_pitch_px)
            item['status']=decode['status']
            item['raw_oid']=decode['raw_oid']
            item['decode_details']={k:decode.get(k) for k in ('tiles_majority','tiles_valid','tiles_total','majority_fraction','coverage_fraction','estimated_grid_pitch_px','angle_deg')}
        except (ValueError, cv2.error, MemoryError) as exc:
            item['status']='INSUFFICIENT_EVIDENCE'
            item['raw_oid']=None
            item['rejected_reason']=str(exc)[:150]
        result.append(item)
    return {'schema':SCHEMA,'kind':'page_scan','a8s_compatible':'UNTESTED',
            'source_size_px':[gray.shape[1],gray.shape[0]],
            'approx_pitch_px':approx_pitch_px,'candidate_count':len(result),
            'decoded_count':sum(r['status']=='DECODED_RESEARCH_ONLY' for r in result),
            'candidates':result,'locator_diagnostics':diagnostics,
            'warning':'Only digital OID2 optical texture; does NOT prove Xiaokedou A8S recognition. No physical scan verified.'}


def visualize(gray:np.ndarray,report:dict):
    canvas=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    for i,r in enumerate(report['candidates'],1):
        x,y,w,h=r['bbox_px'];success=r['raw_oid'] is not None
        color=(0,155,0) if success else (0,100,210)
        cv2.rectangle(canvas,(x,y),(x+w,y+h),color,3)
        cv2.putText(canvas,f'{i}:OID {r["raw_oid"]}' if success else f'{i}: unverified',(x,max(25,y-12)),cv2.FONT_HERSHEY_SIMPLEX,.7,color,2)
    return canvas


def main(argv=None):
    ap=argparse.ArgumentParser(description='Full-image candidate OID2 region locator; A8S unverified')
    ap.add_argument('--image',type=Path,required=True)
    ap.add_argument('--approx-pitch-px',type=float,default=16.)
    ap.add_argument('--max-regions',type=int,default=MAX_REGIONS)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--annotated',type=Path)
    a=ap.parse_args(argv)
    if a.out.exists() or (a.annotated and a.annotated.exists()):ap.error('Refusing to overwrite existing output')
    gray=cv2.imread(str(a.image),cv2.IMREAD_GRAYSCALE)
    if gray is None:ap.error('Cannot read input image')
    try:report=analyze(gray,approx_pitch_px=a.approx_pitch_px,max_regions=a.max_regions)
    except ValueError as e:ap.error(str(e))
    report['source_file']=a.image.name
    report['source_sha256']=hashlib.sha256(a.image.read_bytes()).hexdigest()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if a.annotated:
        a.annotated.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(a.annotated),visualize(gray,report)):raise OSError('Could not save annotated image')
    print(json.dumps({'candidates':report['candidate_count'],'decoded':report['decoded_count'],'a8s_compatible':'UNTESTED'},ensure_ascii=False))


if __name__=='__main__':main()
