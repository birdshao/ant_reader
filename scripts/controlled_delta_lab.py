#!/usr/bin/env python3
"""Controlled one-variable A8S package comparison (read-only, no proprietary decoder).

Compare locally-owned resource packs with controlled single-parameter differences.
Never claims matching integer bytes prove an OID table; all results are hypotheses.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from scripts.native_pack_lab import checked_file, file_sha256

SCHEMA = 'ant-reader-controlled-delta-spec/1'
REPORT = 'ant-reader-controlled-delta-report/1'
MAX_CASES = 12
MAX_SCAN_MIB = 32
MAX_SPANS = 128


def _local_file(base: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Input files must use nonempty relative POSIX paths')
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts or any(v.startswith('.') for v in rel.parts):
        raise ValueError('Unsafe local sample path')
    candidate = base / rel
    if any(p.is_symlink() for p in (candidate, *candidate.parents) if p != base.parent):
        raise ValueError('Symlink path not permitted')
    if not candidate.resolve().is_relative_to(base.resolve()):
        raise ValueError('Sample escapes manifest directory')
    return checked_file(candidate)


def load_spec(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != SCHEMA:
        raise ValueError(f'Expected {SCHEMA}')
    cases = data.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError(f'Expected 1..{MAX_CASES} controlled cases')
    base = path.resolve().parent
    baseline = _local_file(base, data.get('baseline'))
    ids = set()
    parsed = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('Case must be an object')
        cid = case.get('id')
        if not isinstance(cid, str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,39}', cid) or cid in ids:
            raise ValueError('Case id must be unique and alphanumeric')
        ids.add(cid)
        change = case.get('changed_only')
        if change not in ('raw_oid', 'audio', 'book_entry', 'metadata'):
            raise ValueError('changed_only must describe the single controlled variable')
        variant = _local_file(base, case.get('variant'))
        if variant.resolve() == baseline.resolve():
            raise ValueError('Variant cannot equal baseline')
        before, after = case.get('before_oid'), case.get('after_oid')
        if change == 'raw_oid':
            if type(before) is not int or type(after) is not int or not (0 <= before < 2**32 and 0 <= after < 2**32) or before == after:
                raise ValueError('raw_oid case needs distinct unsigned before_oid/after_oid')
        elif before is not None or after is not None:
            raise ValueError('OID values only allowed on raw_oid cases')
        parsed.append({'id': cid, 'changed_only': change, 'variant': variant,
                       'before_oid': before, 'after_oid': after})
    return baseline, parsed


def _exact_spans(a: Path, b: Path, limit: int, *, max_spans=MAX_SPANS) -> tuple[list[list[int]], bool]:
    """Exact changed-byte spans [start,end) up to limit; fixed offsets only."""
    spans = []
    open_start = None
    offset = 0
    overflow = False
    with a.open('rb') as fa, b.open('rb') as fb:
        while offset < limit:
            n = min(65536, limit - offset)
            aa, bb = fa.read(n), fb.read(n)
            for i, (u, v) in enumerate(zip(aa, bb)):
                pos = offset + i
                if u != v:
                    if open_start is None:
                        open_start = pos
                elif open_start is not None:
                    if len(spans) < max_spans:
                        spans.append([open_start, pos])
                    else:
                        overflow = True
                    open_start = None
            offset += len(aa)
            if not aa:
                break
    if open_start is not None:
        if len(spans) < max_spans:
            spans.append([open_start, offset])
        else:
            overflow = True
    return spans, overflow


def _representations(before: int, after: int):
    for bits in (16, 32):
        if max(before, after) < 2**bits:
            for endian in ('little', 'big'):
                yield f'u{bits}_{endian}', before.to_bytes(bits // 8, endian), after.to_bytes(bits // 8, endian)
    yield 'ascii_decimal', str(before).encode('ascii'), str(after).encode('ascii')


def _numeric_matches(a: Path, b: Path, before: int, after: int, limit: int) -> list[dict]:
    """Find exact same-offset before/after byte substitutions; never parse format."""
    matches = []
    if limit == 0:
        return matches
    with a.open('rb') as fa, b.open('rb') as fb:
        x, y = fa.read(limit), fb.read(limit)
    for label, old, new in _representations(before, after):
        if len(old) != len(new):
            continue
        at = x.find(old)
        while at >= 0:
            if y[at:at+len(new)] == new:
                matches.append({'offset': at, 'encoding_hypothesis': label, 'width': len(old)})
                if len(matches) >= 128:
                    return sorted(matches, key=lambda m: (m['offset'], m['encoding_hypothesis']))
            at = x.find(old, at + 1)
    return sorted(matches, key=lambda m: (m['offset'], m['encoding_hypothesis']))


def analyze(spec_file: Path, *, scan_mib: int = 8) -> dict:
    if type(scan_mib) is not int or not 1 <= scan_mib <= MAX_SCAN_MIB:
        raise ValueError(f'scan_mib must be 1..{MAX_SCAN_MIB}')
    baseline, cases = load_spec(spec_file)
    max_bytes = scan_mib * 1024 * 1024
    result_cases = []
    candidates_by_offset = defaultdict(list)
    for case in cases:
        variant = case['variant']
        same_size = baseline.stat().st_size == variant.stat().st_size
        scanned = min(max_bytes, baseline.stat().st_size, variant.stat().st_size)
        spans, truncated = (_exact_spans(baseline, variant, scanned) if same_size else ([], False))
        matches = (_numeric_matches(baseline, variant, case['before_oid'], case['after_oid'], scanned)
                   if same_size and case['changed_only'] == 'raw_oid' else [])
        for m in matches:
            candidates_by_offset[(m['offset'], m['encoding_hypothesis'])].append(case['id'])
        result_cases.append({
            'id': case['id'], 'changed_only': case['changed_only'],
            'variant_sha256': file_sha256(variant), 'variant_size': variant.stat().st_size,
            'same_size': same_size, 'examined_bytes': scanned if same_size else 0,
            'exact_changed_spans': spans, 'spans_truncated': truncated,
            'numeric_substitution_hypotheses': matches,
            'note': ('Unequal sizes: fixed offsets may shift, so byte comparisons were intentionally skipped.'
                     if not same_size else 'Matching bytes at same offsets are clues, NOT proof of a decoded OID field.'),
        })
    cross = [{'offset': offset, 'encoding_hypothesis': encoding,
              'case_ids': sorted(set(ids)), 'cases': len(set(ids))}
             for (offset, encoding), ids in candidates_by_offset.items() if len(set(ids)) >= 2]
    return {
        'format': REPORT, 'status': 'HYPOTHESES_ONLY_NOT_A8S_DECODER',
        'baseline_sha256': file_sha256(baseline), 'baseline_size': baseline.stat().st_size,
        'scan_limit_mib': scan_mib, 'cases': result_cases,
        'cross_case_same_offset_hypotheses': sorted(cross, key=lambda x: (-x['cases'], x['offset'])),
        'warnings': [
            'Only one controlled variable may change per test; metadata/timestamps/compression may still vary.',
            'A numerical byte match does not demonstrate an A8S optical code or audio mapping.',
            'No sample contents are copied, no decoder, no installer, no NOB/NOD/NOS generator.'
        ]
    }


def main(argv=None):
    p = argparse.ArgumentParser(description='Controlled A8S package byte hypotheses; READ ONLY')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--scan-mib', type=int, default=8)
    args = p.parse_args(argv)
    if args.out.exists():
        p.error('Refusing to overwrite existing report')
    try:
        report = analyze(args.spec, scan_mib=args.scan_mib)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (ValueError, OSError, json.JSONDecodeError, KeyError) as e:
        p.error(str(e))
    print(json.dumps({'saved': str(args.out), 'cases': len(report['cases']),
                      'status': report['status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
