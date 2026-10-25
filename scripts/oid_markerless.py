#!/usr/bin/env python3
"""Marker-free, *local-crop* OID2 dot-grid decoder (research only).

The crop must contain mostly one repeated OID2 code, with locally uniform scale
and rotation. Not an arbitrary full-page detector or A8S compatibility claim.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np
try:
    from scripts import oid_scan_qa as qa
except ModuleNotFoundError:
    import oid_scan_qa as qa

SCHEMA='ant-reader-oid2-markerless/1'
MAX_SIDE=2400
PERIOD=64
PITCH=16
FRAME=[(2*x,2*y) for x,y in qa.oid.FRAME_DOTS]


def lattice_estimates(gray:np.ndarray, pitch_px:float, *,count:int=8):
    """Find plausible grid axes from local maxima in Fourier magnitude."""
    if not 6<=pitch_px<=48:raise ValueError('approx-pitch-px must be 6..48')
    if gray.ndim!=2 or min(gray.shape)<160:raise ValueError('Need grayscale OID crop of at least 160 pixels per side')
    h,w=gray.shape
    sample=np.float32(255-gray)
    sample=(sample-sample.mean())*np.outer(np.hanning(h),np.hanning(w)).astype(np.float32)
    spectrum=np.abs(np.fft.fftshift(np.fft.fft2(sample)))
    yy,xx=np.indices(spectrum.shape)
    fx=(xx-w//2)/w; fy=(yy-h//2)/h
    freq=np.hypot(fx,fy)
    mask=(freq>=1/(pitch_px*1.35))&(freq<=1/(pitch_px*.75))&(fx>=0)
    maxima=cv2.dilate(spectrum.astype(np.float32),np.ones((5,5),np.uint8))
    strong=(spectrum>=maxima-1e-5)&mask
    ys,xs=np.where(strong)
    peaks=sorted(zip(ys,xs),key=lambda v:spectrum[v],reverse=True)[:40]
    result=[]
    logs=np.log1p(spectrum)
    def subpixel(y,x,axis):
        if y<=0 or x<=0 or y>=h-1 or x>=w-1:return 0.
        left,mid,right=((logs[y,x-1],logs[y,x],logs[y,x+1]) if axis==1
                         else (logs[y-1,x],logs[y,x],logs[y+1,x]))
        den=float(left-2*mid+right)
        return float(np.clip(.5*(left-right)/den,-.75,.75)) if abs(den)>1e-6 else 0.
    for y,x in peaks:
        vec=((x+subpixel(y,x,1)-w//2)/w,(y+subpixel(y,x,0)-h//2)/h)
        freqval=math.hypot(*vec)
        angle=math.degrees(math.atan2(vec[1],vec[0]))
        if not any(abs((angle-old[0]+45)%90-45)<2.0 and abs(freqval-old[1])/old[1]<0.035 for old in result):
            result.append((angle,freqval,float(spectrum[y,x])))
        if len(result)>=count:break
    return result


def normalize(gray:np.ndarray,angle:float,freq:float):
    """Orient FFT grid candidate and rescale to a two-pixel (1200 dpi) data dot."""
    h,w=gray.shape
    s=PITCH*freq
    if not .4<=s<=3:raise ValueError('Implausible lattice scale')
    center=(w/2.,h/2.)
    M=cv2.getRotationMatrix2D(center,angle,s)
    outw=max(180,int(w*s));outh=max(180,int(h*s))
    M[0,2]+=(outw-w)/2; M[1,2]+=(outh-h)/2
    if outw*outh>8_000_000:raise ValueError('Normalized scan too large')
    return cv2.warpAffine(gray,M,(outw,outh),borderValue=255)


def phase_candidates(gray:np.ndarray, *,top:int=18):
    """Accumulate darkness by primitive modulo; vote for seven sync dot phase."""
    h,w=gray.shape
    cut=min(8,max(0,min(h,w)//40))
    patch=gray[cut:h-cut,cut:w-cut]
    ys,xs=np.indices(patch.shape)
    mod=np.bincount((((ys+cut)%PERIOD)*PERIOD+((xs+cut)%PERIOD)).ravel(),
                    weights=(255-patch).ravel().astype(np.float64),minlength=PERIOD*PERIOD).reshape(PERIOD,PERIOD)
    mod=cv2.GaussianBlur(mod.astype(np.float32),(3,3),.7)
    scores=np.zeros((PERIOD,PERIOD),np.float32)
    for x,y in FRAME:
        scores+=np.roll(mod,(-y,-x),axis=(0,1))
    localmax=cv2.dilate(scores,np.ones((3,3),np.uint8))
    inds=np.where(scores>=localmax-1e-5)
    ranked=sorted(zip(inds[0],inds[1]),key=lambda a:float(scores[a]),reverse=True)
    chosen=[]
    for y,x in ranked:
        if any(min(abs(x-ax),PERIOD-abs(x-ax))<=2 and min(abs(y-ay),PERIOD-abs(y-ay))<=2 for ay,ax in chosen):continue
        chosen.append((int(y),int(x)))
        if len(chosen)>=top:break
    return chosen


def score_phase(gray:np.ndarray,phase:tuple[int,int]):
    y0,x0=phase
    counts=Counter();valid=0;tested=0; strengths=0.
    h,w=gray.shape
    for y in range(y0,h-PERIOD+1,PERIOD):
        for x in range(x0,w-PERIOD+1,PERIOD):
            tested+=1
            # The asymmetrical (1,16) sync pixel breaks 180-degree ambiguity.
            if qa.dot_strength(gray,x+2,y+32,2)<45:
                continue
            val=qa.decode_one_tile(gray[y:y+PERIOD,x:x+PERIOD],0,0,scale=2)
            if val is not None:
                oid,score=val;counts[oid]+=1;strengths+=score;valid+=1
    top,winning=counts.most_common(1)[0] if counts else (None,0)
    return {'raw_oid':top,'votes':winning,'valid':valid,'tested':tested,'strength':strengths,'counts':counts}


def decode_markerless(gray:np.ndarray,*,approx_pitch_px:float=16.,expected_raw_oid:int|None=None):
    """Blind decode single-code OID2 crop; no ArUco and no expected ID required."""
    if expected_raw_oid is not None and (type(expected_raw_oid) is not int or not 0<=expected_raw_oid<=65535):
        raise ValueError('expected raw OID must be uint16')
    if gray is None or gray.ndim!=2 or gray.dtype!=np.uint8:raise ValueError('Expected uint8 grayscale image')
    if max(gray.shape)>MAX_SIDE:raise ValueError(f'Crop too large (max dimension {MAX_SIDE}px); crop local area')
    if min(gray.shape)<160:raise ValueError('Crop too small (<160px)')
    peaks=lattice_estimates(gray,approx_pitch_px)
    best=None
    for angle,freq,power in peaks:
        for quarter in (0,90,180,270):
            try:
                rect=normalize(gray,angle+quarter,freq)
            except ValueError:continue
            for phase in phase_candidates(rect):
                scored=score_phase(rect,phase)
                v=scored['votes'];n=scored['tested']
                if n<6:continue
                majority=v/max(1,scored['valid'])
                coverage=v/n
                quality=(v,majority,coverage,scored['strength'])
                if best is None or quality>best[0]:
                    best=(quality,angle+quarter,freq,phase,scored,rect)
    if best is None:
        out={'schema':SCHEMA,'status':'INSUFFICIENT_EVIDENCE','raw_oid':None,'a8s_compatible':'UNTESTED',
             'warning':'Markerless local-crop software result; no A8S validation.'}
        return out,None
    quality,angle,freq,phase,scored,rect=best
    v=scored['votes'];n=scored['tested'];valid=scored['valid']
    status='DECODED_RESEARCH_ONLY' if v>=6 and v>=0.12*n and v>=0.8*valid else 'INSUFFICIENT_EVIDENCE'
    raw=scored['raw_oid'] if status.startswith('DECODED') else None
    out={'schema':SCHEMA,'status':status,'raw_oid':raw,'leading_candidate':scored['raw_oid'],
         'tiles_majority':v,'tiles_valid':valid,'tiles_total':n,
         'majority_fraction':round(v/max(1,valid),4),'coverage_fraction':round(v/n,4),
         'angle_deg':round(angle,4),'estimated_grid_pitch_px':round(1/freq,4),
         'normalized_phase_px':list(phase),'normalized_size_px':list(rect.shape[::-1]),
         'a8s_compatible':'UNTESTED',
         'warning':'Only a local crop of one repeated OID2 pattern, not arbitrary full-page localization or A8S compatibility.'}
    if expected_raw_oid is not None:
        out['expected_raw_oid']=expected_raw_oid
        out['matches_expected']=(raw==expected_raw_oid)
    return out,rect


def main(argv=None):
    p=argparse.ArgumentParser(description='Markerless local-crop OID2 decoder (A8S unverified)')
    p.add_argument('--image',type=Path,required=True)
    p.add_argument('--approx-pitch-px',type=float,default=16.)
    p.add_argument('--expected-raw-oid',type=int)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--normalized',type=Path)
    args=p.parse_args(argv)
    if args.out.exists() or (args.normalized and args.normalized.exists()):p.error('Refusing to overwrite existing output')
    im=cv2.imread(str(args.image),cv2.IMREAD_GRAYSCALE)
    if im is None:p.error('Could not load input image')
    report,rect=decode_markerless(im,approx_pitch_px=args.approx_pitch_px,expected_raw_oid=args.expected_raw_oid)
    report['source_name']=args.image.name
    report['source_sha256']=hashlib.sha256(args.image.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.normalized and rect is not None:
        args.normalized.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(args.normalized),rect)
    print(json.dumps({'status':report['status'],'raw_oid':report['raw_oid'],
                      'tiles_majority':report.get('tiles_majority',0),'a8s_compatible':'UNTESTED'}))

if __name__=='__main__':main()
