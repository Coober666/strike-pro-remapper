# web/ — JavaScript parsers (Web Viewer, stage 1)

Read-only JS ports of the `.skt` / `.sin` binary parsers from `strike_remap.py`, for the
planned browser viewer (PLANNED.md § "Web Viewer v1"). **Parsers only — no writers.**
Vanilla JS + standard Web/Node APIs (`DataView`, typed arrays); zero dependencies.

| File | Ports (from `strike_remap.py`) |
|---|---|
| `bytes.js` | shared byte helpers (ascii-replace decode, LE reads) |
| `skt.js` | `parse_skt` + `_pad_view` → `parseSkt(buf)` |
| `sin.js` | `parse_sin`, `parse_sin_all_wavs`, `parse_sin_first_wav`, `_sin_blocks` |
| `similar.js` | `_knn_rank` + `similar_instruments` → `knnRank(queryKey, corpusItems, n)` / `similarInstruments(sinRel, fingerprints, n)` (ranks pre-computed fingerprint vectors; no WAV/FFT extraction, no filesystem-availability filter — caller supplies the corpus) |
| `test_parsers.mjs` | Node parity test vs. the Python parsers |
| `test_similar.mjs` | Node parity test vs. Python's `_knn_rank`, over the full committed `factory_fingerprints.json` corpus |

`parseSkt(buf)` returns `{ kit_raw, pads, instruments, tail }` where `pads` is already the
`_pad_view()` array (drop-in for `renderDrumMap` / `renderPadDetail`) and `kit_raw` / `tail`
are `Uint8Array`s. `parseSin(buf)` returns `{ params, cycle_random, mappings, strings }`,
matching `parse_sin()`.

## Verifying parity

```
python tools/make_fixtures.py            # tests/fixtures/*.skt, *.sin (deterministic, no library)
python tools/dump_parser_expected.py     # tests/fixtures/parsers_expected.json
node web/test_parsers.mjs                # asserts JS == Python, field-exact

python tools/dump_similar_expected.py    # tests/expected/similar_expected.json
node web/test_similar.mjs                # asserts JS knnRank == Python _knn_rank, order + dist
```

CI runs all of these (`.github/workflows/ci.yml`). The parser test deep-compares every
pad-view field, the str tables, `kit_raw`/`tail` (as hex), and the full `parse_sin` result
against the Python output. Any divergence fails with the exact field path. The similarity
test picks ~25 deterministic query keys (one per SIN group, then a stride over the rest)
from the committed `factory_fingerprints.json` (1,748 entries, no library/SD needed) and
asserts neighbour order and distance (rounded to 3 decimals) match exactly.

## Format edge cases that were fiddly to match

- **ASCII decode.** Python uses `bytes.decode('ascii', errors='replace')` → bytes >127 become
  U+FFFD. `TextDecoder('ascii')` does **not** do this — per WHATWG that label is an alias for
  windows-1252, which decodes 0x80–0xFF to Latin-1-ish characters. So `asciiReplace()` is
  hand-rolled: 0–127 → the char, else U+FFFD.
- **Two different NUL-split rules.** `parse_skt`'s str table uses an `index()`/`break` loop that
  **drops a trailing, non-NUL-terminated segment**; `parse_sin`'s str block uses a plain
  `split(b'\x00')` that keeps every non-empty segment. Ported each exactly rather than unifying —
  in practice both writers NUL-terminate every string, so the difference only shows on malformed
  input, but the parsers still had to agree byte-for-byte.
- **`str.strip()` ≠ trim NUL.** Python's argument-less `strip()` removes ASCII whitespace but not
  NUL; pad IDs are space-padded (`pad_id.ljust(4)`), so the trailing space is stripped but a NUL
  would not be. `pyStrip()` matches (whitespace only).
- **`name()` uses `.replace('.sin','')`** which removes **all** occurrences, not just a suffix —
  replicated with `split('.sin').join('')` (and the `.SIN` variant).
- **`midi_chan` is stored 0-indexed** and surfaced as `+1` in the pad view; `mute_grp` is raw.
- **Unsigned u32 sizes.** Block sizes are read little-endian and kept unsigned (`>>> 0` /
  `* 0x1000000`) so a high bit can't turn a length negative.
- **Duplicate chunk magics.** `_sin_blocks` lets a later block with the same magic overwrite an
  earlier one (Python dict semantics); `sinBlocks()` does the same.
- **`similar.js`'s `name` field** mirrors `rel.split('/', 1)[-1].rsplit('.', 1)[0]` — split on
  the *first* slash only (keeps any remaining slashes in a nested rel path), then strip only the
  *last* extension. This is a different rule from `skt.js`'s `name()` (all-`.sin`-occurrences
  strip) — each ported exactly as its own Python function does it, not unified.
- **Python's `round()` is banker's rounding** (round-half-to-even); `similar.js` has a
  `roundHalfEven()` helper for the distance rounding instead of `Math.round()` (round-half-away-
  from-zero). In practice no tie has been observed in the parity corpus (euclidean distances of
  z-scored floats essentially never land exactly on `x.xxx5`), but the helper is there in case
  one ever does.
