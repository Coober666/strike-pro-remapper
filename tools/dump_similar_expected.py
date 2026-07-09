#!/usr/bin/env python3
"""
dump_similar_expected.py — dump the Python k-NN similarity ranking (_knn_rank) for a
deterministic spread of query keys over the full factory fingerprint corpus, so the JS
port (web/similar.js) can be checked for exact parity against it.

Produces tests/expected/similar_expected.json:

  { "<query sin_rel>": [["<neighbour sin_rel>", dist], ...], ... }

Queries are picked deterministically (sorted keys, one representative from each SIN
group first so every group is exercised, then an even stride over the rest to round
out to ~25 total) — no library/SD card needed, factory_fingerprints.json is committed.

Run `python tools/dump_similar_expected.py`. Consumed by web/test_similar.mjs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strike_remap as sr

OUT_DIR = ROOT / 'tests' / 'expected'
OUT = OUT_DIR / 'similar_expected.json'

N_QUERIES = 25
N_NEIGHBOURS = 10


def pick_queries(keys):
    """Deterministic spread: one key per SIN group (first alphabetically) so every
    group is represented, then an even stride over the remaining keys to round out
    to N_QUERIES total."""
    keys = sorted(keys)
    seen_groups = set()
    picked = []
    for k in keys:
        g = k.split('/', 1)[0]
        if g not in seen_groups:
            seen_groups.add(g)
            picked.append(k)
    if len(picked) < N_QUERIES:
        remaining = [k for k in keys if k not in set(picked)]
        need = N_QUERIES - len(picked)
        if remaining:
            step = max(1, len(remaining) // need)
            for i in range(0, len(remaining), step):
                if len(picked) >= N_QUERIES:
                    break
                picked.append(remaining[i])
    return sorted(picked)[:max(N_QUERIES, len(seen_groups))]


def main():
    factory = sr.load_factory_fingerprints()
    corpus = [(rel, e['feats']) for rel, e in factory.items() if e.get('feats')]
    corpus_keys = [rel for rel, _ in corpus]

    queries = pick_queries(corpus_keys)

    out = {}
    for q in queries:
        ranked = sr._knn_rank(q, corpus, N_NEIGHBOURS)
        out[q] = [[key, dist] for key, dist, _feats in ranked]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True), encoding='utf-8')
    print(f'wrote {OUT} ({len(out)} queries, corpus size {len(corpus)})')


if __name__ == '__main__':
    main()
