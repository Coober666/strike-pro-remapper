#!/usr/bin/env python3
"""
off18_correlation.py - investigate why off 18 has two modes (99 and 83).

Hypothesis: the mode split correlates with single-layer vs dual-layer pads,
or with specific instrument categories (kick, snare, cymbal, etc.).

Usage:
    python tools/off18_correlation.py F:\STORAGE\Kits
"""
import struct
import sys
from pathlib import Path
from collections import Counter, defaultdict

GM_DRUMS = {
    35: 'Bass Drum 2', 36: 'Bass Drum 1', 37: 'Side Stick',
    38: 'Snare 1',     39: 'Hand Clap',   40: 'Snare 2',
    41: 'Lo Floor Tom', 42: 'Closed HH',  43: 'Hi Floor Tom',
    44: 'Pedal HH',    45: 'Lo Tom',      46: 'Open HH',
    47: 'Lo-Mid Tom',  48: 'Hi-Mid Tom',  49: 'Crash 1',
    50: 'Hi Tom',      51: 'Ride 1',      52: 'Chinese',
    53: 'Ride Bell',   54: 'Tambourine',  55: 'Splash',
    56: 'Cowbell',     57: 'Crash 2',     58: 'Vibraslap',
    59: 'Ride 2',
}


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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    root = Path(sys.argv[1])
    kits = list(root.rglob('*.skt'))

    # off 18 by single vs dual layer
    off8_by_layer = {1: Counter(), 2: Counter()}
    off18_by_layer = {1: Counter(), 2: Counter()}

    # off 18 by instrument category (via MIDI note)
    off8_by_midi = defaultdict(Counter)
    off18_by_midi = defaultdict(Counter)

    # off 8 vs off 18 co-occurrence (correlation table)
    co_counter = Counter()

    total = 0
    for kit_path in kits:
        data = kit_path.read_bytes()
        pads = parse_skt(data)
        for pad_id, payload in pads:
            if len(payload) < 52:
                continue
            la_idx = struct.unpack_from('<H', payload, 4)[0]
            lb_idx = struct.unpack_from('<H', payload, 24)[0]
            if la_idx == 0xFFFF:
                continue  # no layer A instrument — skip empty pads
            layers = 1 if lb_idx == 0xFFFF else 2

            off8_val = payload[8]
            off18_val = payload[18]
            midi = payload[52]
            total += 1

            off8_by_layer[layers][off8_val] += 1
            off18_by_layer[layers][off18_val] += 1
            off8_by_midi[midi][off8_val] += 1
            off18_by_midi[midi][off18_val] += 1
            co_counter[(off8_val, off18_val)] += 1

    print(f"Analyzed {total} pads with instruments\n")

    print("=== Off 18 distribution: single-layer vs dual-layer pads ===")
    for layers in (1, 2):
        c = off18_by_layer[layers]
        tot = sum(c.values())
        print(f"\n  Layer count = {layers}  ({tot} pads)")
        for v, cnt in c.most_common(10):
            print(f"    {v:3d}  {cnt:5d}x  ({cnt/tot*100:5.1f}%)")

    print("\n=== Off 8 distribution: single-layer vs dual-layer pads ===")
    for layers in (1, 2):
        c = off8_by_layer[layers]
        tot = sum(c.values())
        print(f"\n  Layer count = {layers}  ({tot} pads)")
        for v, cnt in c.most_common(10):
            print(f"    {v:3d}  {cnt:5d}x  ({cnt/tot*100:5.1f}%)")

    print("\n=== Off 18 by MIDI note (drum type) — top value per drum ===")
    drum_rows = []
    for midi, c in sorted(off8_by_midi.items()):
        if sum(c.values()) < 5:
            continue
        c18 = off18_by_midi[midi]
        gm = GM_DRUMS.get(midi, f'MIDI {midi}')
        top8 = c.most_common(1)[0][0]
        top18 = c18.most_common(1)[0][0]
        n = sum(c.values())
        drum_rows.append((midi, gm, n, top8, top18))
    print(f"  {'MIDI':>5}  {'Name':<20}  {'N':>5}  {'Mode off8':>9}  {'Mode off18':>10}")
    for midi, gm, n, top8, top18 in drum_rows:
        print(f"  {midi:>5}  {gm:<20}  {n:>5}  {top8:>9}  {top18:>10}")

    print("\n=== Off 8 vs Off 18 co-occurrence (top 20 pairs) ===")
    print(f"  {'off8':>5}  {'off18':>6}  {'count':>6}")
    for (o8, o18), cnt in co_counter.most_common(20):
        print(f"  {o8:>5}  {o18:>6}  {cnt:>6}")


if __name__ == '__main__':
    main()
