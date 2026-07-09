#!/usr/bin/env python3
"""
build_factory_fingerprints.py — regenerate the baked factory fingerprint set.

The Strike's factory content is read-only and byte-identical on every module, so its
audio fingerprints are the same for everyone. We compute them ONCE here (against a
mounted factory card / synced library) and commit the result as
``factory_fingerprints.json`` at the repo root, so the "More like this" similarity
search works out of the box with **no first-run batch and no multi-GB sample sync** —
only a user's own imported samples need fingerprinting from then on.

Run this (with the factory library available) whenever FP_SCHEMA or the feature vector
changes. Entries are marked ``factory`` and carry ``size`` but not ``mtime`` (mtimes
differ between cards/copies; the app validates factory entries on size only).

Usage:
    python tools/build_factory_fingerprints.py            # incremental (reuse matching sizes)
    python tools/build_factory_fingerprints.py --force    # recompute everything
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr

OUT = sr.FACTORY_FP_PATH


def main():
    force = '--force' in sys.argv[1:]

    sr.refresh_available()
    rels = sorted(sr.state['avail'].keys())
    if not rels:
        print('No instruments found. Mount the factory SD card (or sync the library) '
              'so the one-level-deep scan can see Instruments/, then re-run.')
        sys.exit(1)

    prev = {}
    if OUT.exists() and not force:
        try:
            prev = json.loads(OUT.read_text('utf-8'))
        except Exception:
            prev = {}

    out = {}
    computed = reused = skipped = 0
    t0 = time.time()
    for i, rel in enumerate(rels):
        if i % 100 == 0:
            print(f'  {i}/{len(rels)}  ({computed} computed, {reused} reused, {skipped} skipped)',
                  flush=True)
        wav_path, wav_rel = sr._representative_wav_for_sin(rel)
        if wav_path is None:
            skipped += 1
            continue
        try:
            size = wav_path.stat().st_size
        except OSError:
            skipped += 1
            continue
        # Reuse a prior entry when the schema and representative-WAV size both match.
        old = prev.get(rel)
        if (old and old.get('v') == sr.FP_SCHEMA and old.get('feats')
                and old.get('size') == size):
            entry = dict(old)
            entry['factory'] = True
            entry.pop('mtime', None)
            out[rel] = entry
            reused += 1
            continue
        feats = sr.extract_fingerprint(wav_path)
        if feats is None:
            skipped += 1
            continue
        out[rel] = {'v': sr.FP_SCHEMA, 'factory': True,
                    'wav_rel': wav_rel, 'size': size, 'feats': feats}
        computed += 1

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), 'utf-8')
    kb = OUT.stat().st_size / 1024
    print(f'\nwrote {len(out)} factory fingerprints to {OUT.name} ({kb:.0f} KB) '
          f'in {time.time()-t0:.0f}s')
    print(f'  {computed} computed, {reused} reused, {skipped} skipped '
          f'(no representative WAV / broken)')


if __name__ == '__main__':
    main()
