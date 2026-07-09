#!/usr/bin/env python3
"""
full_byte_scan.py - scan every byte in pad payloads across all kits.

Looks for pitch semitones: would show mode=0 (no shift), small range,
possibly signed (values near 0 AND near 255 if stored as int8).

Usage:
    python tools/full_byte_scan.py F:\STORAGE\Kits
"""
import struct
import sys
from pathlib import Path
from collections import Counter


KNOWN = {
    0: 'pad_id[0]', 1: 'pad_id[1]', 2: 'pad_id[2]', 3: 'pad_id[3]',
    4: 'la_idx_lo', 5: 'la_idx_hi',
    6: 'la_level',
    7: 'la_PAN(confirmed)',
    8: 'la_?08',
    13: 'la_?13',
    18: 'la_?18',
    20: 'la_maxv(127)',
    24: 'lb_idx_lo', 25: 'lb_idx_hi',
    26: 'lb_level',
    27: 'lb_PAN(confirmed)',
    28: 'lb_?28',
    33: 'lb_?33',
    38: 'lb_?38',
    40: 'lb_maxv(127)',
    44: 'xfade_v',
    46: 'active_l',
    52: 'midi_note',
    56: 'choke[0]', 57: 'choke[1]', 58: 'choke[2]', 59: 'choke[3]', 60: 'choke[4]',
}

SKIP = {0, 1, 2, 3, 52}  # pad ID and MIDI note - not useful here


def parse_skt(data: bytes):
    if data[:4] != b'KIT ':
        return []
    kit_size = struct.unpack_from('<I', data, 4)[0]
    pos = 8 + kit_size
    pads = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == b'inst':
        blk_size = struct.unpack_from('<I', data, pos + 4)[0]
        payload = bytes(data[pos + 8: pos + 8 + blk_size])
        pad_id = payload[:4].decode('ascii', errors='replace').rstrip('\x00').strip()
        pads.append((pad_id, payload))
        pos += 8 + blk_size
    return pads


def pitch_score(counter: Counter, total: int) -> float:
    """
    Score how 'pitch-semitone-like' a byte is.
    Pitch semitones (int8, center 0) stored as uint8:
      - 0x00 = 0 semitones (most common → high count at 0)
      - 0x01-0x0C = +1 to +12
      - 0xF4-0xFF = -12 to -1
      - Middle range (0x0D-0xF3) should be sparse
    Score = (count[0] + count[244-255]) / total - count(middle 13-243)/total
    """
    low_count = sum(counter[v] for v in range(0, 13))   # 0 to +12
    high_count = sum(counter[v] for v in range(244, 256))  # -12 to -1
    mid_count = sum(counter[v] for v in range(13, 244))
    return (low_count + high_count - mid_count) / total


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    root = Path(sys.argv[1])
    kits = list(root.rglob('*.skt'))
    print(f"Scanning {len(kits)} kits...\n")

    max_off = 72
    counters = [Counter() for _ in range(max_off)]
    total_pads = 0

    for kit_path in kits:
        data = kit_path.read_bytes()
        pads = parse_skt(data)
        for pad_id, payload in pads:
            total_pads += 1
            for off in range(min(len(payload), max_off)):
                counters[off][payload[off]] += 1

    print(f"Total pads: {total_pads}\n")
    print(f"{'Off':>4}  {'Known name':<26}  {'Unique':>6}  {'Range':>12}  {'Mode':>6}  {'Mode%':>6}  {'PitchScore':>10}")
    print('-' * 90)

    scores = []
    for off in range(max_off):
        if off in SKIP:
            continue
        c = counters[off]
        if not c:
            continue
        total = sum(c.values())
        vals = sorted(c.keys())
        mode_v, mode_cnt = c.most_common(1)[0]
        mode_pct = mode_cnt / total * 100
        val_range = f"{min(vals)}-{max(vals)}"
        name = KNOWN.get(off, '')
        ps = pitch_score(c, total)
        scores.append((off, ps, name, len(vals), val_range, mode_v, mode_pct))

    # Sort by pitch score descending
    scores.sort(key=lambda x: -x[1])

    for off, ps, name, uniq, rng, mode_v, mode_pct in scores:
        print(f"{off:>4}  {name:<26}  {uniq:>6}  {rng:>12}  {mode_v:>6}  {mode_pct:>5.1f}%  {ps:>10.3f}")

    # Also print Layer A unknowns (off 9-12, 14-17, 19, 21-23) separately
    print("\n--- Layer A unknown bytes (4-23), full value breakdown ---")
    for off in range(4, 24):
        if off in SKIP or off in KNOWN:
            continue
        c = counters[off]
        total = sum(c.values())
        vals = sorted(c.keys())
        non_zero = {v: c[v] for v in vals if v != 0}
        print(f"  off {off:2d}: unique={len(vals)}, range={min(vals)}-{max(vals)}, "
              f"zeros={c[0]}({c[0]/total*100:.0f}%), "
              f"non-zero vals: {dict(list(non_zero.items())[:15])}")


if __name__ == '__main__':
    main()
