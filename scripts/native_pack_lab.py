#!/usr/bin/env python3
"""Conservative read-only triage of legitimately obtained reading-pen packages.

Reports structural evidence; it does NOT decode, decrypt or produce A8S packages.
No raw media payload is copied to the report. Suitable for personal-use samples.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import sys

SCHEMA = "ant-reader-native-pack-lab/1"
MIB = 1024 * 1024
MAX_SIZE = 1024 * MIB  # limit accidental analysis of unrelated drive images
SAMPLE_BYTES = 4096
MAX_WINDOWS = 32
DIFF_BLOCK = 65536


def checked_file(value: str | Path) -> Path:
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected a regular, non-symlink local file")
    n = path.stat().st_size
    if not 0 < n <= MAX_SIZE:
        raise ValueError("File size outside accepted 1 byte..1 GiB range")
    return path


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(MIB), b""):
            h.update(chunk)
    return h.hexdigest()


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    count = Counter(data)
    length = len(data)
    return round(-sum((v/length)*math.log2(v/length) for v in count.values()), 4)


def signature(head: bytes) -> str:
    """Format evidence based on magic only; extension never establishes format."""
    magic = [
        (b"PK\x03\x04", "ZIP-local-header"),
        (b"PK\x05\x06", "ZIP-empty-archive"),
        (b"\x1f\x8b", "gzip"),
        (b"RIFF", "RIFF-container"),
        (b"OggS", "Ogg-container"),
        (b"ID3", "MP3-ID3-tag"),
        (b"fLaC", "FLAC"),
        (b"MThd", "MIDI"),
        (b"%PDF-", "PDF"),
        (b"\x7fELF", "ELF-executable"),
        (b"MZ", "DOS-PE-possible"),
    ]
    for start, label in magic:
        if head.startswith(start):
            return label
    return "unknown-signature"


def sample_offsets(n: int, length: int = SAMPLE_BYTES, count: int = MAX_WINDOWS) -> list[int]:
    if n <= length:
        return [0]
    max_offset = n - length
    return sorted({int(i * max_offset / (count - 1)) for i in range(count)})


def inspect(path: Path) -> dict:
    path = checked_file(path)
    n = path.stat().st_size
    samples = []
    with path.open("rb") as f:
        first = f.read(32)
        for offset in sample_offsets(n):
            f.seek(offset)
            block = f.read(SAMPLE_BYTES)
            samples.append({"offset": offset, "read_bytes": len(block), "entropy_bits_per_byte": entropy(block),
                            "zero_fraction": round(block.count(0) / len(block), 5)})
    entropies = [x["entropy_bits_per_byte"] for x in samples]
    return {
        "schema": SCHEMA, "kind": "inspect", "file_name": path.name,
        "extension": path.suffix.lower(), "size_bytes": n, "sha256": file_sha256(path),
        "header_hex_32": first.hex(), "magic_evidence": signature(first),
        "window_bytes": SAMPLE_BYTES, "window_count": len(samples),
        "mean_sample_entropy_bits_per_byte": round(sum(entropies) / len(entropies), 4),
        "samples": samples,
        "interpretation": "The magic and entropy are only clues. Unknown/high entropy does not prove encryption or compatibility.",
        "a8s_supported": "UNKNOWN", "decoded_oids": None, "format_specification": "NOT_DETERMINED",
    }


def common_prefix(a: Path, b: Path, limit: int) -> int:
    total = 0
    with a.open("rb") as fa, b.open("rb") as fb:
        while total < limit:
            take = min(MIB, limit - total)
            x, y = fa.read(take), fb.read(take)
            if x == y:
                total += len(x)
                continue
            for i, (ca, cb) in enumerate(zip(x, y)):
                if ca != cb:
                    return total + i
            return total + min(len(x), len(y))
    return total


def common_suffix(a: Path, b: Path, limit: int) -> int:
    total = 0
    na, nb = a.stat().st_size, b.stat().st_size
    with a.open("rb") as fa, b.open("rb") as fb:
        while total < limit:
            take = min(MIB, limit - total)
            fa.seek(na - total - take)
            fb.seek(nb - total - take)
            x, y = fa.read(take), fb.read(take)
            if x == y:
                total += take
                continue
            for i, (ca, cb) in enumerate(zip(reversed(x), reversed(y))):
                if ca != cb:
                    return total + i
            return total + take
    return total


def compare(a: Path, b: Path, *, block_size: int = DIFF_BLOCK) -> dict:
    a, b = checked_file(a), checked_file(b)
    if a.resolve() == b.resolve():
        raise ValueError("Choose two different files to compare")
    if not 1024 <= block_size <= MIB:
        raise ValueError("block size must be 1024..1 MiB")
    na, nb = a.stat().st_size, b.stat().st_size
    common = min(na, nb)
    prefix = common_prefix(a, b, common)
    suffix = common_suffix(a, b, common - prefix)
    changed = []
    aligned_equal = 0
    aligned_checked = 0
    with a.open("rb") as fa, b.open("rb") as fb:
        for start in range(0, common, block_size):
            x, y = fa.read(block_size), fb.read(block_size)
            aligned_checked += 1
            if x == y:
                aligned_equal += 1
            else:
                if len(changed) < 128:
                    changed.append({"offset": start, "length": min(block_size, common - start)})
    return {
        "schema": SCHEMA, "kind": "compare", "a": {"file_name": a.name, "size_bytes": na, "sha256": file_sha256(a)},
        "b": {"file_name": b.name, "size_bytes": nb, "sha256": file_sha256(b)},
        "common_prefix_bytes": prefix, "common_suffix_bytes_nonoverlapping": suffix,
        "aligned_block_bytes": block_size, "aligned_blocks_equal": aligned_equal,
        "aligned_blocks_checked": aligned_checked, "changed_aligned_block_samples": changed,
        "changed_blocks_truncated_at": 128,
        "interpretation": "Comparing distinct packages does not reveal OID mapping by itself. File offsets may shift, and compression obscures boundaries.",
        "decoded_oids": None, "a8s_supported": "UNKNOWN",
    }


def save_report(path: Path, report: dict) -> None:
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing evidence report")
    path.parent.mkdir(parents=True, exist_ok=True)
    # keep path out of raw sample and out of a public repository by default
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only native pen package structural triage; NOT a format decoder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect", help="Record signatures, entropy and hash without copying package data")
    i.add_argument("--file", type=Path, required=True)
    i.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare", help="Compare two known lawful resource files")
    c.add_argument("--a", type=Path, required=True)
    c.add_argument("--b", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--block-size", type=int, default=DIFF_BLOCK)
    options = parser.parse_args(argv)
    try:
        result = inspect(options.file) if options.cmd == "inspect" else compare(options.a, options.b, block_size=options.block_size)
        save_report(options.out, result)
    except (ValueError, OSError, FileExistsError) as e:
        parser.error(str(e))
    print(json.dumps({"kind": result["kind"], "saved": str(options.out), "a8s_supported": "UNKNOWN"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())