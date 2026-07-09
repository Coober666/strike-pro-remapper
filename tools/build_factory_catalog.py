#!/usr/bin/env python3
"""
build_factory_catalog.py — regenerate the baked factory instrument catalog.

Web Viewer v1 is a pure-browser, read-only app with zero filesystem access — it can't
scan a mounted SD card or `library/instruments/` the way the desktop app does. Since the
Strike's factory instrument library is read-only and byte-identical on every module, we
can bake a static catalog of every factory .sin instrument (name, group, and sample-zone
mappings) ONCE here and commit it as ``factory_catalog.json`` at the repo root — the exact
same trick already used for ``factory_fingerprints.json`` ("More like this" similarity).
The viewer inlines this JSON directly into its single-file HTML so it can browse/search
the whole library with no server.

Run this (with the factory library mounted) whenever the catalog needs a refresh, e.g.
a new factory content revision ships, or the output schema changes (bump ``_schema``).

Output schema (factory_catalog.json):
    {
      "_schema": 1,
      "instruments": {
        "<sin_rel>": {
          "name": "<display name, .sin stripped>",
          "group": <int 0-19, INST payload byte [1]>,
          "group_name": "<SIN_GROUPS[group]>",
          "cycle": 0 | 1,                 # 0=round-robin, 1=random (msmp payload byte [0])
          "size": <int, .sin file size in bytes>,
          "mappings": [
            {"wav_rel": "<path from str table>", "vmin": n, "vmax": n, "rr": n}, ...
          ]
        }, ...
      }
    }

``<sin_rel>`` uses the identical forward-slash-relative-path format as
``scan_instruments()`` / ``factory_fingerprints.json`` keys (e.g. "Snares/BJ DWMaple
Center.sin"), so the two baked files can be cross-referenced by key.

Kept lean on purpose (this ships inlined in a single HTML file): no redundant per-mapping
fields (hi-hat pedal range, raw command byte, etc.) beyond what a browsable catalog needs.

Usage:
    python tools/build_factory_catalog.py                  # auto-detect mounted library
    python tools/build_factory_catalog.py --library F:\\STORAGE
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr

_SCHEMA = 1
OUT = Path(__file__).resolve().parent.parent / 'factory_catalog.json'


def _instrument_entry(sin_rel: str, abs_path: Path) -> dict:
    data = abs_path.read_bytes()
    parsed = sr.parse_sin(data)
    params = parsed['params']
    group = params.get('group', 0)
    name = sin_rel.rsplit('/', 1)[-1].removesuffix('.sin').removesuffix('.SIN')
    mappings = [
        {'wav_rel': m['sample'], 'vmin': m['vmin'], 'vmax': m['vmax'], 'rr': m['rr']}
        for m in parsed['mappings']
    ]
    return {
        'name': name,
        'group': group,
        'group_name': sr.SIN_GROUPS.get(group, f'Group {group}'),
        'cycle': parsed['cycle_random'],
        'size': len(data),
        'mappings': mappings,
    }


def _spot_check(rels, n=3):
    """Re-parse n random entries directly from disk and diff against the built catalog."""
    sample = random.sample(rels, min(n, len(rels)))
    results = []
    for rel in sample:
        abs_path = sr.state['avail'][rel]
        fresh = _instrument_entry(rel, Path(abs_path))
        results.append((rel, fresh))
    return results


def main():
    args = sys.argv[1:]
    library_override = None
    if '--library' in args:
        i = args.index('--library')
        library_override = Path(args[i + 1])
        args = args[:i] + args[i + 2:]

    if library_override:
        roots = [library_override / 'Instruments'] if (library_override / 'Instruments').is_dir() \
            else [library_override]
        sr.state['avail'] = sr.scan_instruments(roots)
    else:
        sr.refresh_available()

    rels = sorted(sr.state['avail'].keys())
    if not rels:
        print('No instruments found. Mount the factory SD card / library (or pass '
              '--library <path>) so the scan can see Instruments/, then re-run.')
        sys.exit(1)

    out = {}
    failed = []
    t0 = time.time()
    for i, rel in enumerate(rels):
        if i % 200 == 0:
            print(f'  {i}/{len(rels)}', flush=True)
        abs_path = Path(sr.state['avail'][rel])
        try:
            out[rel] = _instrument_entry(rel, abs_path)
        except Exception as e:
            failed.append((rel, str(e)))

    catalog = {'_schema': _SCHEMA, 'instruments': out}
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=0, sort_keys=False), 'utf-8')
    kb = OUT.stat().st_size / 1024
    print(f'\nwrote {len(out)} instruments to {OUT.name} ({kb:.0f} KB) in {time.time()-t0:.0f}s')

    if failed:
        print(f'\n{len(failed)} .sin file(s) failed to parse:')
        for rel, err in failed:
            print(f'  {rel}: {err}')

    # Cross-check against factory_fingerprints.json key count (same library, same scan).
    fp_path = sr.FACTORY_FP_PATH
    if fp_path.exists():
        try:
            fp_keys = json.loads(fp_path.read_text('utf-8'))
            fp_count = len(fp_keys)
            diff = abs(fp_count - len(out))
            print(f'\nfactory_fingerprints.json has {fp_count} keys (catalog has {len(out)}, '
                  f'diff={diff})')
            if diff > 5:
                print(f'  WARNING: instrument count differs from fingerprints file by {diff} '
                       '(> 5) — investigate before committing.')
        except Exception as e:
            print(f'  (could not read {fp_path.name} for comparison: {e})')
    else:
        print(f'\n{fp_path.name} not found — skipping count cross-check.')

    # Spot-check: re-parse a few random entries straight from disk, compare to catalog.
    print('\nspot-checking 3 random entries...')
    for rel, fresh in _spot_check(rels, 3):
        baked = out.get(rel)
        match = baked == fresh
        print(f'  {rel}: {"OK" if match else "MISMATCH"}')
        if not match:
            print(f'    baked: {baked}')
            print(f'    fresh: {fresh}')


if __name__ == '__main__':
    main()
