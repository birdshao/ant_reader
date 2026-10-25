#!/usr/bin/env python3
"""A8S optical-code printing lab. Does NOT generate/prove native A8S OIDs.

All code artwork is imported from an explicitly identified external source.
The PDF embeds PNG pixels at their *native physical size*, never resampling.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

A4_W_MM, A4_H_MM = 210.0, 297.0
MM = 72.0 / 25.4
LOG_FIELDS = ("utc", "id", "raw_oid", "printer", "dpi", "paper", "mode", "expected", "observed", "attempts", "correct", "wrong_audio", "notes")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_source(base: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError("image must be a non-empty relative path without '..'")
    base = base.resolve()
    target = (base / value).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError(f"Missing or unsafe OID image: {value}")
    return target


def load_candidates(manifest: Path):
    from PIL import Image
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("candidates"), list) or not raw["candidates"]:
        raise ValueError("candidates JSON must contain non-empty candidates list")
    if len(raw["candidates"]) > 200:
        raise ValueError("Too many candidates (max 200)")
    result, seen = [], set()
    for item in raw["candidates"]:
        if not isinstance(item, dict):
            raise ValueError("candidate must be object")
        name, oid, dpi = item.get("id"), item.get("raw_oid"), item.get("source_dpi")
        if not isinstance(name,str) or not name or len(name) > 48 or not name.replace('-','').replace('_','').isalnum():
            raise ValueError("candidate id must be a short alphanumeric label")
        if name in seen:
            raise ValueError(f"duplicate candidate id: {name}")
        seen.add(name)
        if type(oid) is not int or not 0 <= oid <= 0xFFFFFFFF:
            raise ValueError(f"{name}: raw_oid must be a non-negative integer")
        if type(dpi) is not int or not 300 <= dpi <= 2400:
            raise ValueError(f"{name}: source_dpi must be 300..2400")
        if not isinstance(item.get("source"),str) or len(item["source"]) < 4:
            raise ValueError(f"{name}: source is required for traceability")
        src = safe_source(manifest.parent, item.get("image"))
        with Image.open(src) as im:
            if im.format != 'PNG':
                raise ValueError(f"{name}: use PNG, not other formats")
            width_px, height_px = im.size
            if min(width_px,height_px) < 10:
                raise ValueError(f"{name}: source image too small")
            # Some encoders export opaque white, others RGBA. Either can be calibrated on white.
            if im.mode not in ('RGB','RGBA','L','1'):
                raise ValueError(f"{name}: unexpected PNG mode {im.mode}")
        size_mm = (width_px*25.4/dpi, height_px*25.4/dpi)
        if max(size_mm) > 63:
            raise ValueError(f"{name}: code tile {size_mm} exceeds 63mm lab cell; no downscaling allowed")
        result.append({**item, "_path":src, "_width_px":width_px, "_height_px":height_px,
                       "_size_mm":size_mm, "_sha256":file_hash(src)})
    return result


def draw_ruler(c, x, y, span=100):
    c.setStrokeColorRGB(.22,.30,.42)
    c.setFont('Helvetica', 7)
    for i in range(span+1):
        xi=x+i*MM
        length=5 if i%10==0 else (3 if i%5==0 else 1.5)
        c.line(xi,y,xi,y+length*MM)
        if i%20==0:
            c.drawCentredString(xi,y-4*MM,str(i))
    c.line(x,y,x+span*MM,y)


def make_template(out: Path):
    """Blank check sheet, explicitly no optical codes; useful before A8S/encoder arrive."""
    from reportlab.pdfgen import canvas
    c=canvas.Canvas(str(out), pagesize=(210*MM,297*MM))
    c.setTitle("A8S OID Test Layout - BLANK, NO CODES")
    c.setFont('Helvetica-Bold',16)
    c.drawString(12*MM,278*MM,"A8S Optical Print Lab / Blank Test Sheet")
    c.setFont('Helvetica',9)
    c.drawString(12*MM,270*MM,"NO OID is printed on this sheet. Supply authenticated PNG patterns for candidate-sheet.")
    for idx in range(6):
        col,row=idx%2,idx//2
        x=(12+col*96)*MM; y=(193-row*71)*MM
        c.setLineWidth(.8);c.roundRect(x,y,90*MM,64*MM,4*MM,stroke=1,fill=0)
        c.setFont('Helvetica-Bold',10);c.drawString(x+4*MM,y+56*MM,f"Candidate {idx+1} / EMPTY")
        c.setFont('Helvetica',8);c.drawString(x+4*MM,y+48*MM,"Source: ______________  Raw OID: _______")
        c.setDash(2,2);c.rect(x+8*MM,y+6*MM,45*MM,37*MM,stroke=1,fill=0);c.setDash()
        c.drawString(x+56*MM,y+26*MM,"Code PNG")
        c.drawString(x+56*MM,y+21*MM,"goes here")
    c.setFont('Helvetica-Bold',9);c.drawString(12*MM,31*MM,"Print at ACTUAL SIZE (100%) / no Fit-to-page")
    c.setFont('Helvetica',8);c.drawString(12*MM,25*MM,"Measure 100 mm below; if length differs, fix print driver scaling before OID tests.")
    draw_ruler(c,14*MM,13*MM)
    c.save()
    return out


def make_candidate_sheet(manifest: Path, out: Path):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.colors import HexColor
    items=load_candidates(manifest)
    audit=[]
    c=canvas.Canvas(str(out),pagesize=(210*MM,297*MM),pageCompression=1)
    c.setTitle("A8S External OID Candidates - EXPERIMENTAL")
    for idx,item in enumerate(items):
        if idx%6==0:
            if idx:
                c.showPage()
            c.setFont('Helvetica-Bold',15);c.setFillColor(HexColor('#26364E'))
            c.drawString(12*MM,283*MM,"A8S - OID CODE EXPERIMENT (UNVERIFIED)")
            c.setFont('Helvetica',8);c.drawString(12*MM,275*MM,"External code sources only. Requires matching pen resource pack and physical scan validation.")
        col,row=(idx%6)%2,(idx%6)//2
        x,y=(12+col*96)*MM,(199-row*72)*MM
        c.setStrokeColor(HexColor('#B7C4D2'));c.setFillColor(HexColor('#FFFFFF'))
        c.roundRect(x,y,90*MM,68*MM,2*MM,fill=0,stroke=1)
        c.setFillColor(HexColor('#24364B'));c.setFont('Helvetica-Bold',9)
        c.drawString(x+3*MM,y+61*MM,item['id'][:26])
        c.setFont('Helvetica',7)
        c.drawString(x+3*MM,y+55*MM,f"OID {item['raw_oid']} | source {item['source_dpi']} dpi")
        iw,ih=item['_size_mm']
        # The lower left of the code image is *exactly* specified by physical source DPI.
        # Absolutely no target-cell fitting or pixel interpolation occurs.
        px=x+((90-iw)/2)*MM; py=y+(6+(46-ih)/2)*MM
        c.drawImage(ImageReader(str(item['_path'])),px,py,width=iw*MM,height=ih*MM,mask='auto')
        c.setFont('Helvetica',6.2)
        c.drawString(x+3*MM,y+2.5*MM,f"{iw:.2f}x{ih:.2f}mm | {item['_sha256'][:12]} | DO NOT ASSUME A8S COMPATIBILITY")
        audit.append({"id":item['id'],"raw_oid":item['raw_oid'],"source":item['source'],
                      "image":item['image'],"source_dpi":item['source_dpi'],
                      "pixels":[item['_width_px'],item['_height_px']],
                      "printed_mm":[round(iw,5),round(ih,5)],"sha256":item['_sha256'],
                      "device_status":"UNVERIFIED"})
        if idx%6==5 or idx==len(items)-1:
            c.setFont('Helvetica',8)
            c.drawString(12*MM,31*MM,"Printer  _________  DPI ______  Paper _______  Firmware ________  Date ________")
            c.drawString(12*MM,24*MM,"Measure ruler below, print at 100%; no auto contrast enhancement or image scaling.")
            draw_ruler(c,14*MM,12*MM)
    c.save()
    audit_file=out.with_suffix('.audit.json')
    audit_file.write_text(json.dumps({"format":"ant-reader-oid-lab/1", "status":"UNVERIFIED",
                                     "candidates":audit},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out,audit_file


def record(path: Path, *, cid: str, raw_oid: int, expected: str, observed: str,
           attempts: int, correct: int, wrong_audio: int = 0,
           printer: str='', dpi: str='', paper: str='', mode: str='', notes: str=''):
    if not cid or attempts <= 0 or not (0 <= correct <= attempts) or not (0 <= wrong_audio <= attempts-correct):
        raise ValueError("Invalid test counts or candidate")
    if type(raw_oid) is not int or raw_oid < 0:
        raise ValueError("Invalid raw_oid")
    path.parent.mkdir(parents=True,exist_ok=True)
    exists=path.exists()
    with path.open('a',newline='',encoding='utf-8-sig' if not exists else 'utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({"utc":datetime.now(timezone.utc).isoformat(),"id":cid,"raw_oid":raw_oid,
                         "printer":printer,"dpi":dpi,"paper":paper,"mode":mode,
                         "expected":expected,"observed":observed,"attempts":attempts,
                         "correct":correct,"wrong_audio":wrong_audio,"notes":notes})


def summarize(path: Path):
    values={}
    with path.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            k=(row['id'],row['raw_oid']); entry=values.setdefault(k,{'attempts':0,'correct':0,'wrong_audio':0})
            for field in ('attempts','correct','wrong_audio'):
                entry[field]+=int(row[field])
    report=[]
    for (cid,oid),counters in sorted(values.items()):
        n=counters['attempts']; rate=counters['correct']/n if n else 0
        # Lab threshold is an engineering acceptance target, not a manufacturer's claim.
        status='PASS_LAB_THRESHOLD' if n>=100 and rate>=.99 and counters['wrong_audio']==0 else 'NOT_CERTIFIED'
        report.append({"id":cid,"raw_oid":int(oid),**counters,"accuracy":round(rate,5),"lab_status":status})
    return report


def main():
    p=argparse.ArgumentParser(description="A8S optical pattern print lab (no built-in OID encoder)")
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('blank-sheet');a.add_argument('--out',required=True)
    a=sub.add_parser('candidate-sheet');a.add_argument('--manifest',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('record');a.add_argument('--log',required=True);a.add_argument('--id',required=True)
    a.add_argument('--raw-oid',type=int,required=True);a.add_argument('--expected',required=True)
    a.add_argument('--observed',required=True);a.add_argument('--attempts',type=int,required=True)
    a.add_argument('--correct',type=int,required=True);a.add_argument('--wrong-audio',type=int,default=0)
    for opt in ('printer','dpi','paper','mode','notes'):
        a.add_argument('--'+opt,default='')
    a=sub.add_parser('report');a.add_argument('--log',required=True);a.add_argument('--out')
    args=p.parse_args()
    if args.cmd=='blank-sheet':
        print(make_template(Path(args.out)))
    elif args.cmd=='candidate-sheet':
        print(*make_candidate_sheet(Path(args.manifest),Path(args.out)),sep='\n')
    elif args.cmd=='record':
        record(Path(args.log),cid=args.id,raw_oid=args.raw_oid,expected=args.expected,
               observed=args.observed,attempts=args.attempts,correct=args.correct,
               wrong_audio=args.wrong_audio,printer=args.printer,dpi=args.dpi,
               paper=args.paper,mode=args.mode,notes=args.notes)
        print('Scan result recorded; this does NOT certify a native A8S encoder.')
    elif args.cmd=='report':
        result=summarize(Path(args.log)); data=json.dumps(result,ensure_ascii=False,indent=2)
        if args.out:
            Path(args.out).write_text(data+'\n',encoding='utf-8')
        print(data)

if __name__=='__main__':
    try:
        main()
    except Exception as e:
        pfx=type(e).__name__
        raise SystemExit(f"[ERROR] {pfx}: {e}")