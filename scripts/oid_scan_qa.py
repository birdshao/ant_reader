#!/usr/bin/env python3
"""Experimental *print -> scan* OID2 quality lab with ArUco registration.

The four ArUco markers are purely calibration aids outside an OID tile.
This does NOT model the Xiaokedou A8S optical sensor or establish compatibility.
Requires opencv-contrib-python (cv2.aruco), numpy, Pillow and PyMuPDF for PDF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from scripts import sonix_oid2 as oid
except ModuleNotFoundError:
    import sonix_oid2 as oid

SCHEMA = 'ant-reader-oid2-scan-qa/1'
CARD_MM = 70.0
CODE_ORIGIN_MM = 25.0
CODE_SIZE_MM = 20.0
MARKER_MM = 9.0
MARKER_CENTERS_MM = ((11.,11.),(59.,11.),(59.,59.),(11.,59.))
MARKER_IDS = (10, 11, 12, 13)  # TL, TR, BR, BL


def pixel_size(mm: float, dpi: int) -> int:
    return int(mm * dpi / 25.4)


def aruco_dictionary():
    if not hasattr(cv2, 'aruco') or not hasattr(cv2.aruco, 'generateImageMarker'):
        raise RuntimeError('cv2.aruco missing; install opencv-contrib-python')
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def make_target(raw_oid: int, dpi: int = 1200) -> Image.Image:
    if dpi not in (600, 1200):
        raise ValueError('Only 600 or 1200 nominal source DPI is supported')
    tile = oid.render(raw_oid, dpi=dpi, width_mm=CODE_SIZE_MM, height_mm=CODE_SIZE_MM)
    sz = pixel_size(CARD_MM, dpi)
    card = Image.new('RGB',(sz,sz),'white')
    pos = pixel_size(CODE_ORIGIN_MM, dpi)
    card.paste(tile,(pos,pos),tile)
    aruco = aruco_dictionary()
    side = pixel_size(MARKER_MM,dpi)
    for n,mid in enumerate(MARKER_IDS):
        mask = cv2.aruco.generateImageMarker(aruco,mid,side)
        im = Image.fromarray(mask).convert('RGB')
        x,y = MARKER_CENTERS_MM[n]
        card.paste(im,(pixel_size(x,dpi)-side//2,pixel_size(y,dpi)-side//2))
    return card


def write_pdf(card: Image.Image, dpi: int, pdf_file: Path):
    """Physically size the 70-mm card at the center of an A4 page; bitmap retained."""
    import fitz
    import io
    if pdf_file.exists():
        raise FileExistsError(pdf_file)
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=210*72/25.4,height=297*72/25.4)
    mm = 72/25.4
    x0,y0=70*mm,88*mm
    bio=io.BytesIO()
    card.save(bio,'PNG',dpi=(dpi,dpi))
    page.insert_image(fitz.Rect(x0,y0,x0+CARD_MM*mm,y0+CARD_MM*mm),stream=bio.getvalue())
    page.insert_text((50*mm,34*mm),'OID2 PRINT / SCAN QA (A8S UNVERIFIED)',fontsize=12)
    page.insert_text((50*mm,44*mm),'Print at 100% / actual size. Scan at 600 or 1200 dpi.',fontsize=8)
    page.insert_text((50*mm,55*mm),'ArUco registration corners are NOT reading-pen OID data.',fontsize=8)
    page.insert_text((50*mm,188*mm),'Measure the 70 mm target; do not scale or improve image in print driver.',fontsize=8)
    doc.save(pdf_file,garbage=4,deflate=True)
    doc.close()


def detect_markers(img: np.ndarray):
    if img is None or img.ndim != 2:
        raise ValueError('Expected grayscale input')
    # Detect at reduced resolution on very large scans, then use full-res for warp.
    h,w=img.shape
    factor=min(1., 2800./max(w,h))
    probe=cv2.resize(img,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA) if factor<1 else img
    if hasattr(cv2.aruco,'ArucoDetector'):
        corners,ids,_=cv2.aruco.ArucoDetector(aruco_dictionary()).detectMarkers(probe)
    else:
        corners,ids,_=cv2.aruco.detectMarkers(probe,aruco_dictionary())
    if ids is None:
        raise ValueError('No ArUco calibration markers detected; crop around target or improve scan')
    idmap={int(mid):center[0].mean(axis=0)/factor for mid,center in zip(ids.reshape(-1),corners)}
    missing=[i for i in MARKER_IDS if i not in idmap]
    if missing:
        raise ValueError('Missing calibration markers: '+str(missing))
    return np.float32([idmap[i] for i in MARKER_IDS])


def rectify(img: np.ndarray,dpi: int):
    src=detect_markers(img)
    dst=np.float32([(pixel_size(x,dpi),pixel_size(y,dpi)) for x,y in MARKER_CENTERS_MM])
    matrix=cv2.getPerspectiveTransform(src,dst)
    side=pixel_size(CARD_MM,dpi)
    warped=cv2.warpPerspective(img,matrix,(side,side),flags=cv2.INTER_LINEAR,borderValue=255)
    x=pixel_size(CODE_ORIGIN_MM,dpi)
    k=pixel_size(CODE_SIZE_MM,dpi)
    return warped[x:x+k,x:x+k],matrix


def dot_strength(image: np.ndarray, x: int, y: int, sz: int) -> float:
    """Local ink score [0,255], tolerate half-pixel registration/ink spread."""
    h,w=image.shape
    if x<0 or y<0 or x+sz>w or y+sz>h:
        return 0.0
    return float(255.-image[y:y+sz,x:x+sz].mean())


def decode_one_tile(region: np.ndarray, tx:int,ty:int, *,scale:int=2, shift_x:int=0,shift_y:int=0):
    """Decode one known-lattice-position OID2 primitive without knowing its ID."""
    sx=tx*32*scale+shift_x
    sy=ty*32*scale+shift_y
    if sx<0 or sy<0 or sx+32*scale>region.shape[1] or sy+32*scale>region.shape[0]:
        return None
    # Tiny Gaussian denoise does NOT invent missing dots.
    frame=[dot_strength(region,sx+x*scale,sy+y*scale,scale) for x,y in oid.FRAME_DOTS]
    if sum(v>=48 for v in frame)<6:
        return None
    directions=((1,1),(-1,1),(-1,-1),(1,-1))
    symbols=[]
    scores=[]
    for row in range(1,4):
        for col in range(1,4):
            options=[dot_strength(region,sx+(8*col+dx)*scale,sy+(8*row+dy)*scale,scale)
                     for dx,dy in directions]
            ordered=sorted(options,reverse=True)
            if ordered[0] < 45 or ordered[0]-ordered[1] < 15:
                return None
            symbols.append(int(np.argmax(options)))
            scores.append(ordered[0]-ordered[1])
    try:
        value=oid.decode_symbols(symbols)
    except ValueError:
        return None
    return value,float(np.mean(scores))


def decode_repeated(region:np.ndarray, dpi:int):
    if dpi not in (600,1200):
        raise ValueError('Only 600/1200 dpi scan reconstruction supported')
    scale=dpi//600
    # Minor phase compensation makes registration tolerant of scanning/round-off.
    candidates=[]
    for dy in range(-scale,scale+1):
        for dx in range(-scale,scale+1):
            hits=[]
            nx=region.shape[1]//(32*scale)
            ny=region.shape[0]//(32*scale)
            for ty in range(ny):
                for tx in range(nx):
                    decoded=decode_one_tile(region,tx,ty,scale=scale,shift_x=dx,shift_y=dy)
                    if decoded is not None:
                        hits.append(decoded)
            counts=Counter(v for v,score in hits)
            top_val,top_count=counts.most_common(1)[0] if counts else (None,0)
            candidates.append((top_count,len(hits),sum(s for _,s in hits),top_val,(dx,dy),counts))
    best=max(candidates,key=lambda a:(a[0],a[1],a[2]))
    winning,accepted,_,raw,phase,counts=best
    nx=region.shape[1]//(32*scale); ny=region.shape[0]//(32*scale)
    total=nx*ny
    majority=winning/accepted if accepted else 0.0
    coverage=winning/total if total else 0.0
    # Thresholds are engineering decisions for this SOFTWARE experiment only.
    status=('DECODED_RESEARCH_ONLY' if winning>=6 and majority>=0.8 and coverage>=0.12
            else 'INSUFFICIENT_EVIDENCE')
    return {'raw_oid':raw if status.startswith('DECODED') else None,
            'leading_candidate':raw,'status':status,'tiles_total':total,
            'tiles_checksum_valid':accepted,'tiles_majority':winning,
            'majority_fraction':round(majority,4),'coverage_fraction':round(coverage,4),
            'phase_px':list(phase),'histogram':{str(k):v for k,v in counts.most_common(8)}}


def analyze_image(image_path:Path, dpi:int,expected_raw_oid:int|None=None):
    img=cv2.imread(str(image_path),cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(image_path)
    patch,homography=rectify(img,dpi)
    result=decode_repeated(patch,dpi)
    if expected_raw_oid is not None:
        if type(expected_raw_oid) is not int or not 0<=expected_raw_oid<=65535:
            raise ValueError('Expected OID must be unsigned 16-bit')
        result['expected_raw_oid']=expected_raw_oid
        result['matches_expected']=(result['raw_oid']==expected_raw_oid)
    result.update({'schema':SCHEMA,'source_file':image_path.name,
                   'source_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
                   'nominal_dpi':dpi,'registration':'four ArUco markers, homography',
                   'warped_code_pixels':list(patch.shape[::-1]),
                   'homography':np.round(homography,7).tolist(),
                   'a8s_compatible':'UNTESTED','warning':'Digital image analysis is NOT A8S hardware recognition.'})
    return result,patch


def main(argv=None):
    ap=argparse.ArgumentParser(description='Experimental OID2 print/scan calibration QA, not A8S pen decoder')
    sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('make-target');p.add_argument('--raw-oid',type=int,required=True)
    p.add_argument('--dpi',type=int,choices=[600,1200],default=1200)
    p.add_argument('--png',type=Path,required=True);p.add_argument('--pdf',type=Path)
    p=sub.add_parser('scan');p.add_argument('--image',type=Path,required=True)
    p.add_argument('--dpi',type=int,choices=[600,1200],required=True)
    p.add_argument('--expected-raw-oid',type=int);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--rectified',type=Path)
    a=ap.parse_args(argv)
    if a.cmd=='make-target':
        card=make_target(a.raw_oid,a.dpi)
        a.png.parent.mkdir(parents=True,exist_ok=True)
        if a.png.exists() or (a.pdf and a.pdf.exists()):
            ap.error('Refusing to overwrite existing output')
        card.save(a.png,dpi=(a.dpi,a.dpi))
        if a.pdf:write_pdf(card,a.dpi,a.pdf)
        print(json.dumps({'png':str(a.png),'pdf':str(a.pdf) if a.pdf else None,
                          'raw_oid':a.raw_oid,'a8s_compatible':'UNTESTED'}))
    else:
        result,patch=analyze_image(a.image,a.dpi,a.expected_raw_oid)
        if a.out.exists() or (a.rectified and a.rectified.exists()):
            ap.error('Refusing to overwrite existing output')
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if a.rectified:
            a.rectified.parent.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(a.rectified),patch)
        print(json.dumps({'status':result['status'],'raw_oid':result['raw_oid'],
                          'majority':result['tiles_majority'],'total':result['tiles_total'],
                          'a8s_compatible':'UNTESTED'},ensure_ascii=False))

if __name__=='__main__': main()
