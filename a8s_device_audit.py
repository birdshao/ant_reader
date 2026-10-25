#!/usr/bin/env python3
"""Read-only A8S USB storage/file package audit and before/after comparison.

No pen data is written, no binaries are copied, and NO A8S package decoder is
claimed. Output contains filenames, sizes, limited hashes and optional header
bytes explicitly requested by the operator. No credentials or raw MP3 contents.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "ant-reader-a8s-device-audit/1"
PACK_EXT = frozenset({".nod", ".nob", ".nos", ".dab", ".bnf"})
MEDIA_EXT = frozenset({".mp3", ".wav", ".wma", ".ogg"})
BOOK_DIR_NAMES = frozenset({"book", "books", "diy book", "diybook", "diy_book", "diy-book", "diandushu", "pointread"})
RESTRICTED_SEGMENTS = frozenset({"system volume information", "$recycle.bin", ".trash", ".trashes", "private", "secrets"})
RESTRICTED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".db", ".sqlite"})
MAX_FILES = 50000


def sha256_stream(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def relevant(parts: tuple[str, ...], suffix: str) -> bool:
    # File extensions alone are strong hints; other files only inside likely
    # point-reading book directories (but hidden/private files excluded).
    return suffix in PACK_EXT or any(p.casefold() in BOOK_DIR_NAMES for p in parts[:-1])


def visible(relative: Path) -> bool:
    # Do not reveal potentially sensitive hidden/system paths even in names.
    for segment in relative.parts:
        low = segment.casefold()
        if low.startswith(".") or low in RESTRICTED_SEGMENTS or segment.startswith("$"):
            return False
    if relative.suffix.casefold() in RESTRICTED_SUFFIXES:
        return False
    return True


def file_records(root: Path, *, max_depth: int = 8, max_hash_mb: int = 64) -> list[dict]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("--root must be an existing directory, not a symlink")
    if not 1 <= max_depth <= 32 or not 0 <= max_hash_mb <= 1024:
        raise ValueError("max-depth must be 1..32; max-hash-mb must be 0..1024")
    records = []
    # Explicit directory walk: do not follow symlinks/junction-like links.
    todo = [(root, 0)]
    while todo:
        folder, depth = todo.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        except (OSError, PermissionError):
            continue
        for child in children:
            rel = child.relative_to(root)
            if not visible(rel) or child.is_symlink():
                continue
            try:
                if child.is_dir():
                    if depth + 1 < max_depth:
                        todo.append((child, depth + 1))
                elif child.is_file() and relevant(rel.parts, child.suffix.casefold()):
                    stat = child.stat()
                    n = stat.st_size
                    ext = child.suffix.casefold()
                    if n <= max_hash_mb * 1024 * 1024:
                        try:
                            digest = sha256_stream(child)
                        except OSError:
                            digest = None
                        integrity = "sha256" if digest else "unreadable"
                    else:
                        digest, integrity = None, "size_only_too_large"
                    records.append({"path": rel.as_posix(), "size": n,
                                    "sha256": digest, "integrity": integrity,
                                    "type": "package_candidate" if ext in PACK_EXT else (
                                        "audio" if ext in MEDIA_EXT else "book_directory_file")})
                    if len(records) > MAX_FILES:
                        raise ValueError(f"Exceeded scan limit of {MAX_FILES} files")
            except (OSError, PermissionError):
                continue
    return sorted(records, key=lambda r: r["path"].casefold())


def snapshot(root: Path, *, max_depth: int = 8, max_hash_mb: int = 64) -> dict:
    entries = file_records(root, max_depth=max_depth, max_hash_mb=max_hash_mb)
    return {"schema": SCHEMA, "kind": "snapshot", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "recognized package extensions and likely book folders only",
            "root_absolute_path_recorded": False, "read_only": True,
            "limits": {"max_depth": max_depth, "hash_up_to_mb": max_hash_mb},
            "summary": {"files": len(entries), "candidate_packages": sum(x["type"] == "package_candidate" for x in entries),
                        "extensions": dict(sorted(Counter(Path(x["path"]).suffix.lower() or "<none>" for x in entries).items()))},
            "files": entries,
            "warning": "File extension is not proof of format or A8S compatibility; OID values cannot be inferred."}


def load_snapshot(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or data.get("kind") != "snapshot":
        raise ValueError(f"Not an {SCHEMA} snapshot: {path}")
    if not isinstance(data.get("files"), list):
        raise ValueError("Malformed snapshot: files must be a list")
    names = [x["path"] for x in data["files"]]
    if len(set(names)) != len(names):
        raise ValueError("Malformed snapshot: duplicate filenames")
    return data


def difference(before: dict, after: dict) -> dict:
    a = {x["path"]: x for x in before["files"]}
    b = {x["path"]: x for x in after["files"]}
    changed = []
    for path in sorted(a.keys() & b.keys()):
        prev, cur = a[path], b[path]
        if prev["size"] != cur["size"] or (prev.get("sha256") is not None and cur.get("sha256") is not None and prev["sha256"] != cur["sha256"]):
            changed.append({"path": path, "before": prev, "after": cur})
    uncertain = [path for path in sorted(a.keys() & b.keys())
                 if path not in {c["path"] for c in changed} and
                 (a[path].get("sha256") is None or b[path].get("sha256") is None)]
    return {"schema": SCHEMA, "kind": "diff", "added": [b[k] for k in sorted(b.keys() - a.keys())],
            "removed": [a[k] for k in sorted(a.keys() - b.keys())], "changed": changed,
            "same_size_unverified": uncertain,
            "warning": "Only file-level differences. Does not decode package contents, identify OID values or certify book install."}


def inspect_header(file: Path, *, count: int = 64) -> dict:
    if not file.is_file() or file.is_symlink():
        raise ValueError("--file must be an existing regular file")
    if not 1 <= count <= 256:
        raise ValueError("--bytes must be between 1 and 256")
    size = file.stat().st_size
    with file.open("rb") as f:
        head = f.read(count)
    return {"schema": SCHEMA, "kind": "package_header", "filename": file.name,
            "file_size": size, "sha256": sha256_stream(file),
            "header_hex": head.hex(" "),
            "header_ascii": "".join(chr(c) if 32 <= c < 127 else "." for c in head),
            "read_bytes": len(head),
            "extension_guess_only": file.suffix.lower(),
            "warning": "Header bytes are not a decoded proprietary package or an OID mapping."}


def write_json(out: Path, data: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {out}")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="Read-only A8S USB storage and resource-package evidence audit")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot", help="Read-only inventory of book files; do not mount through this tool")
    s.add_argument("--root", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--max-depth", type=int, default=8)
    s.add_argument("--max-hash-mb", type=int, default=64)
    d = sub.add_parser("diff", help="Compare inventories before/after official point-reading book install")
    d.add_argument("--before", type=Path, required=True)
    d.add_argument("--after", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    h = sub.add_parser("header", help="Read at most 256 initial bytes and SHA-256 of a known package file")
    h.add_argument("--file", type=Path, required=True)
    h.add_argument("--out", type=Path, required=True)
    h.add_argument("--bytes", type=int, default=64)
    opts = p.parse_args(argv)
    try:
        if opts.command == "snapshot":
            result = snapshot(opts.root, max_depth=opts.max_depth, max_hash_mb=opts.max_hash_mb)
        elif opts.command == "diff":
            result = difference(load_snapshot(opts.before), load_snapshot(opts.after))
        else:
            result = inspect_header(opts.file, count=opts.bytes)
        write_json(opts.out, result)
        print(json.dumps({"saved": str(opts.out), "kind": result["kind"],
                          "files": result.get("summary", {}).get("files"),
                          "added": len(result.get("added", [])), "changed": len(result.get("changed", []))}, ensure_ascii=False))
    except (ValueError, OSError, json.JSONDecodeError, KeyError) as exc:
        p.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
