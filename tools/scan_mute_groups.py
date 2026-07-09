#!/usr/bin/env python3
"""
scan_mute_groups.py - find any preset kits that actually use mute/choke groups.

Checks bytes 56-60 across all pads in all kits. All-0xFF = no group.
Any other pattern = group assignment (reveals the encoding).

Usage:
    python tools/scan_mute_groups.py F:\STORAGE\Kits
"""
import struct, sys
from pathlib import Path
from collections import Counter

def parse_skt(data):
    if data[:4] != b'KIT ': return []
    kit_size = struct.unpack_from('<I', data, 4)[0]
    pos = 8 + kit_size
    pads = []
    while pos + 8 <= len(data) and data[pos:pos+4] == b'inst':
        blk = struct.unpack_from('<I', data, pos+4)[0]
        payload = data[pos+8:pos+8+blk]
        pad_id = payload[:4].decode('ascii', errors='replace').rstrip('\x00').strip()
        pads.append((pad_id, payload))
        pos += 8 + blk
    return pads

root = Path(sys.argv[1])
hits = []
byte56_counter = Counter()

for kit_path in root.rglob('*.skt'):
    for pad_id, payload in parse_skt(kit_path.read_bytes()):
        if len(payload) < 61: continue
        chunk = payload[56:61]
        byte56_counter[chunk[0]] += 1
        if chunk != b'\xff\xff\xff\xff\xff':
            hits.append((kit_path.name, pad_id, chunk.hex(' ')))

print(f"Scanned {root} — byte 56 value distribution:")
for v, cnt in sorted(byte56_counter.items()):
    label = 'no group (0xFF)' if v == 0xFF else f'GROUP {v}'
    print(f"  {v:#04x} = {v:3d}  {cnt:5d}x  {label}")

if hits:
    print(f"\nPads with non-0xFF choke group ({len(hits)} found):")
    for kit, pad, raw in hits:
        print(f"  {kit:<40} {pad:<6} bytes[56-60] = {raw}")
else:
    print("\nNo mute groups used in any preset kit — all pads are 0xFF.")
