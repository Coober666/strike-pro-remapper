#!/usr/bin/env python3
"""
analyze_offsets.py - scan all .skt files and report value distributions
for specific offsets to help identify their meaning.

Usage:
    python tools/analyze_offsets.py F:\STORAGE\Kits

Focuses on off 7 (pan), off 8 (?), off 18 (?) to disambiguate pitch vs decay.
"""
import struct
import sys
from pathlib import Path
from collections import Counter


OFFSETS_OF_INTEREST = [7, 8, 18]

# Decode as int8 (signed) or uint8?
SIGNED = {7: True, 8: False, 18: False}


def parse_skt(data: bytes):
    """Return list of (pad_id, payload_bytes) for each inst block."""
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
    print(f"Found {len(kits)} .skt files under {root}")

    counters = {off: Counter() for off in OFFSETS_OF_INTEREST}
    pad_samples = {off: [] for off in OFFSETS_OF_INTEREST}  # (kit, pad, value) samples
    total_pads = 0

    for kit_path in kits:
        data = kit_path.read_bytes()
        pads = parse_skt(data)
        for pad_id, payload in pads:
            total_pads += 1
            for off in OFFSETS_OF_INTEREST:
                if off < len(payload):
                    raw = payload[off]
                    if SIGNED[off]:
                        v = raw if raw < 128 else raw - 256
                    else:
                        v = raw
                    counters[off][v] += 1
                    if len(pad_samples[off]) < 10:
                        pad_samples[off].append((kit_path.name, pad_id, v))

    print(f"Total pads analyzed: {total_pads}\n")

    for off in OFFSETS_OF_INTEREST:
        c = counters[off]
        vals = sorted(c.keys())
        total = sum(c.values())
        signed_note = "(as int8/signed)" if SIGNED[off] else "(as uint8/unsigned)"
        print(f"{'='*60}")
        print(f"  Off {off}  {signed_note}")
        print(f"  Unique values: {len(vals)}    Range: {min(vals)} – {max(vals)}")
        print(f"  Top 20 most common values:")
        for v, cnt in c.most_common(20):
            pct = cnt / total * 100
            bar = '#' * int(pct / 2)
            print(f"    {v:5d}  {cnt:5d}x  ({pct:5.1f}%)  {bar}")
        if len(vals) <= 30:
            print(f"  All values: {vals}")
        # Show spread: how many pads have non-default (non-mode) value
        mode_val = c.most_common(1)[0][0]
        non_default = total - c[mode_val]
        print(f"  Mode: {mode_val}  ({c[mode_val]}x, {c[mode_val]/total*100:.1f}%)  "
              f"|  Non-mode: {non_default} pads ({non_default/total*100:.1f}%)")
        print(f"  Samples: {pad_samples[off][:5]}")
        print()


if __name__ == '__main__':
    main()
