#!/usr/bin/env python3
"""Printed-OID-first book pipeline for Xiaokedou A8S.

No OID encoder or proprietary resource packer is embedded. Supply externally
encoded and independently validated PNG patterns for final composition.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MM = 72 / 25.4


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(f"Invalid ASCII identifier: {value!r}")
    return value


def validate_book(book):
    if not isinstance(book, dict) or not isinstance(book.get("items"), list) or not book["items"]:
        raise ValueError("A book must contain at least one item")
    slug(book.get("book_id"))
    seen = set()
    for item in book["items"]:
        key = slug(item.get("key"))
        if key in seen:
            raise ValueError(f"Duplicate item key: {key}")
        seen.add(key)
        for field in ("english", "chinese", "sentence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{key} is missing {field}")
    return book


def assign_ids(registry, book):
    """Stable logical audio indexes, NOT optical OID code values."""
    ids = registry.setdefault("ids", {})
    if len(ids.values()) != len(set(ids.values())):
        raise ValueError("Duplicate logical index in registry")
    nxt = max(ids.values(), default=0) + 1
    for item in book["items"]:
        for kind in ("word", "sentence"):
            logical = f"{book['book_id']}:{item['key']}:{kind}"
            if logical not in ids:
                ids[logical] = nxt
                nxt += 1
    return ids


def choose_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    choices = [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
        ("C:/Windows/Fonts/msyh.ttc", 0),
        ("C:/Windows/Fonts/simhei.ttf", 0),
        ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    ]
    if "a8s_cjk" in pdfmetrics.getRegisteredFontNames():
        return "a8s_cjk"
    for filename, subfont in choices:
        if Path(filename).exists():
            try:
                pdfmetrics.registerFont(TTFont("a8s_cjk", filename, subfontIndex=subfont))
                return "a8s_cjk"
            except Exception:
                pass
    raise RuntimeError("Install a CJK font (Noto Sans CJK or Microsoft YaHei)")


def make_layout(book, ids, pdf_path: Path):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    font = choose_font()
    W, H = A4
    c = Canvas(str(pdf_path), pagesize=A4)
    c.setTitle(book.get("title", book["book_id"]) + " — OID artwork (not encoded)")
    margin, gap, width, height = 12, 7, 89.5, 105
    areas = []
    for p in range((len(book["items"]) + 3) // 4):
        c.setFillColor(HexColor("#FBFAF6")); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(HexColor("#263C59")); c.roundRect(12*MM, 264*MM, 186*MM, 18*MM, 8*MM, fill=1, stroke=0)
        c.setFillColor(HexColor("#FFFFFF")); c.setFont(font, 16)
        c.drawString(17*MM, 270*MM, book.get("title", book["book_id"]))
        for pos in range(4):
            at = p*4+pos
            if at >= len(book["items"]):
                continue
            item = book["items"][at]
            col, row = pos % 2, pos // 2
            left = (margin + col*(width+gap))*MM
            bottom = (139 - row*(height+8))*MM
            c.setFillColor(HexColor("#FFFFFF")); c.setStrokeColor(HexColor("#D5DDE5"))
            c.roundRect(left, bottom, width*MM, height*MM, 5*MM, stroke=1, fill=1)
            rx, ry, rw, rh = left + 4*MM, bottom + 52*MM, 81.5*MM, 47*MM
            c.setFillColor(HexColor("#EEF4F7")); c.roundRect(rx, ry, rw, rh, 3*MM, stroke=0, fill=1)
            if item.get("image"):
                photo = (Path(book["_source_path"]).parent / item["image"]).resolve()
                if not photo.is_file():
                    raise FileNotFoundError(photo)
                c.drawImage(ImageReader(str(photo)), rx+3*MM, ry+3*MM,
                            width=rw-6*MM, height=rh-6*MM, preserveAspectRatio=True, anchor="c", mask="auto")
            else:
                c.setFont("Helvetica-Bold", 42); c.setFillColor(HexColor("#B0C9D2"))
                c.drawCentredString(rx + rw/2, ry + 17*MM, item["english"][:1].upper())
            c.setFillColor(HexColor("#344054")); c.setFont("Helvetica-Bold", 17)
            c.drawCentredString(left + width*MM/2, bottom + 37*MM, item["english"])
            c.setFont(font, 10); c.drawCentredString(left + width*MM/2, bottom + 29*MM, item["chinese"])
            sx, sy, sw, sh = left + 4*MM, bottom + 6*MM, 81.5*MM, 19*MM
            c.setFillColor(HexColor("#FFF6E6")); c.roundRect(sx, sy, sw, sh, 3*MM, fill=1, stroke=0)
            c.setFillColor(HexColor("#445469")); c.setFont("Helvetica", 9)
            c.drawCentredString(sx + sw/2, sy + 8*MM, item["sentence"])
            for kind, box in (("word", (rx, ry, rw, rh)), ("sentence", (sx, sy, sw, sh))):
                bx, by, bw, bh = box
                logical = f"{book['book_id']}:{item['key']}:{kind}"
                areas.append({"logical_id":logical, "audio_index":ids[logical], "page":p+1,
                              "part":kind, "x_mm":round(bx/MM,3), "y_mm":round((H-by-bh)/MM,3),
                              "width_mm":round(bw/MM,3), "height_mm":round(bh/MM,3),
                              "raw_oid":None, "mapping_status":"UNVERIFIED"})
        c.setFont("Helvetica", 7); c.setFillColor(HexColor("#A24837"))
        c.drawString(12*MM, 8*MM, "ARTWORK ONLY — no readable OID is present; do not use as a finished reading book")
        c.showPage()
    c.save()
    return areas


def make_audio(engine, text, dst: Path, supplied: Path | None):
    if engine == "none":
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if engine == "files":
        if not supplied or not supplied.is_file() or supplied.suffix.lower() != ".mp3":
            raise FileNotFoundError(f"Missing MP3: {supplied}")
        shutil.copyfile(supplied, dst)
    elif engine == "edge":
        cli = shutil.which("edge-tts")
        if not cli:
            raise RuntimeError("Run: pip install edge-tts")
        subprocess.run([cli, "--voice", "en-US-JennyNeural", "--text", text,
                        "--write-media", str(dst)], check=True)
    else:
        raise ValueError(engine)
    if dst.stat().st_size < 300:
        raise ValueError(f"Invalid/empty MP3 {dst}")
    return True


def prepare(args):
    source = Path(args.book).resolve()
    book = validate_book(read_json(source)); book["_source_path"] = str(source)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    registry_file = out / "registry.json"
    ledger = read_json(registry_file) if registry_file.exists() else {"version":1,"ids":{}}
    ids = assign_ids(ledger, book)
    dest = out / "books" / book["book_id"]
    dest.mkdir(parents=True, exist_ok=True)
    regions = make_layout(book, ids, dest / "artwork.pdf")
    manifest = []
    for item in book["items"]:
        for kind in ("word", "sentence"):
            logical = f"{book['book_id']}:{item['key']}:{kind}"
            idx = ids[logical]
            text = item["english"] if kind=="word" else item["sentence"]
            supplied = ((source.parent / item[f"{kind}_audio_file"]).resolve()
                        if item.get(f"{kind}_audio_file") else None)
            target = dest / "audio" / f"{idx:06}.mp3"
            generated = make_audio(args.tts, text, target, supplied)
            manifest.append({"logical_id":logical,"audio_index":idx,"text":text,
                             "path":str(target.relative_to(dest)),"audio_ready":generated})
    save_json(dest / "regions.json", {"status":"UNENCODED", "regions":regions})
    save_json(dest / "audio_manifest.json", manifest)
    with (dest / "mapping_template.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["logical_id","audio_index","raw_oid","pattern_png","tested_on_a8s"])
        writer.writeheader()
        for area in regions:
            writer.writerow({"logical_id":area["logical_id"],"audio_index":area["audio_index"],
                             "raw_oid":"","pattern_png":"","tested_on_a8s":"false"})
    save_json(registry_file, ledger)
    print(f"Prepared {len(regions)} full-area optical zones: {dest}")
    print("OID NOT ENCODED. No printable reading codes have been generated.")


def compose(args):
    """Place externally encoded transparent PNGs at physical (not guessed) DPI."""
    import fitz
    from PIL import Image
    bookdir = Path(args.out).resolve() / "books" / slug(args.book_id)
    manifest = read_json(bookdir / "regions.json")["regions"]
    path = Path(args.mapping).resolve()
    mapping = read_json(path)
    if not isinstance(mapping, dict):
        raise ValueError("mapping JSON must map logical IDs to pattern metadata")
    doc = fitz.open(bookdir / "artwork.pdf")
    seen_oids = {}
    for area in manifest:
        key = area["logical_id"]
        m = mapping.get(key)
        if not isinstance(m, dict):
            raise ValueError(f"Missing pattern for region {key}")
        oid = m.get("raw_oid")
        if not isinstance(oid,int) or oid < 0:
            raise ValueError(f"Invalid optical raw_oid for {key}")
        if oid in seen_oids and seen_oids[oid] != key:
            raise ValueError(f"OID {oid} reused by {key} and {seen_oids[oid]}")
        seen_oids[oid] = key
        if not args.experimental and m.get("tested_on_a8s") is not True:
            raise ValueError(f"Not marked tested_on_a8s: {key}; use --experimental")
        rel = Path(m.get("pattern_png", ""))
        if not str(rel) or rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe/missing pattern path for {key}")
        pattern = path.parent / rel
        if not pattern.is_file():
            raise FileNotFoundError(pattern)
        with Image.open(pattern) as img:
            if img.mode != "RGBA":
                raise ValueError(f"Pattern must be transparent RGBA: {pattern.name}")
            px_w, px_h = img.size
            expected = (area["width_mm"]*args.dpi/25.4, area["height_mm"]*args.dpi/25.4)
            if abs(px_w - expected[0])>1.5 or abs(px_h-expected[1])>1.5:
                raise ValueError(f"DPI mismatch for {key}: {img.size}; need {expected}")
        x = area["x_mm"]*MM; y=area["y_mm"]*MM
        rect = fitz.Rect(x,y,x+area["width_mm"]*MM,y+area["height_mm"]*MM)
        doc[area["page"]-1].insert_image(rect, filename=str(pattern), overlay=True,
                                          keep_proportion=False)
    if args.experimental:
        for page in doc:
            page.insert_text((16*MM, 13*MM), "EXPERIMENTAL OID, NOT VERIFIED ON A8S",
                             fontsize=8, color=(0.75,0.15,0.12), overlay=True)
    target=bookdir / ("experimental_print.pdf" if args.experimental else "print_ready.pdf")
    doc.save(target, garbage=4, deflate=True)
    doc.close()
    print(f"Created {target}; printing and hardware recognition still require testing")


def main():
    p=argparse.ArgumentParser(description="A8S printable OID workflow; does not invent OID codes")
    commands=p.add_subparsers(dest="command",required=True)
    b=commands.add_parser("prepare",help="Generate PDF artwork, audio and microcode region manifests")
    b.add_argument("--book",required=True);b.add_argument("--out",default="output")
    b.add_argument("--tts",choices=["edge","files","none"],default="none")
    b.set_defaults(func=prepare)
    c=commands.add_parser("compose",help="Overlay REAL externally encoded OID PNGs at exact DPI")
    c.add_argument("--out",default="output");c.add_argument("--book-id",required=True)
    c.add_argument("--mapping",required=True);c.add_argument("--dpi",type=int,default=600)
    c.add_argument("--experimental",action="store_true");c.set_defaults(func=compose)
    a=p.parse_args()
    try:a.func(a)
    except Exception as exc:
        print(f"[ERROR] {exc}",file=sys.stderr);sys.exit(1)


if __name__=="__main__":main()
