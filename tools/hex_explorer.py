#!/usr/bin/env python3
"""
hex_explorer.py - annotated hex dump of every pad payload in a .skt file.

Usage:
    python tools/hex_explorer.py path/to/kit.skt
    python tools/hex_explorer.py path/to/kit.skt K1H   # single pad only

Confidence legend shown next to each field:
  [v] confirmed - matches semantics across multiple kits (e.g. MIDI note vs GM map)
  [~] likely    - strong pattern evidence across kits, meaning plausible
  [?] uncertain - non-zero, position known, purpose still unclear
"""
import struct
import sys
from pathlib import Path

# Field map
# offset -> (name, byte_width, struct_fmt, description, confidence)
#   struct_fmt: 'B'=uint8  'b'=int8  '<H'=uint16-LE  '4s'/'5s'=raw bytes
FIELDS = {
    # Pad header
    0:  ('pad_id',    4, '4s',  'Pad identifier (ASCII, null-padded)',                          'confirmed'),

    # Layer A  (bytes 4-23)
    4:  ('la_idx',    2, '<H',  'Layer A: instrument index (0xFFFF = none)',                    'confirmed'),
    6:  ('la_level',  1, 'B',   'Layer A: output level 0-127',                                 'likely'),
    7:  ('la_pan',    1, 'b',   'Layer A: pan -50 to +50 (int8; confirmed: hard-left=0xce=-50)','confirmed'),
    8:  ('la_?08',    1, 'B',   'Layer A: unknown (mode=95; range 0-99; uniform across drum types)', 'uncertain'),
    11: ('la_pitch',  1, 'b',   'Layer A: pitch semitones -12 to +12 (int8; mode=0 76%; stat. confirmed)', 'likely'),
    13: ('la_?13',    1, 'B',   'Layer A: likely Filter Cutoff 0-99 (mode=99; SEVEN REC diff evidence)', 'uncertain'),
    14: ('la_filt_f', 1, 'B',   'Layer A: likely Filter Enable/Type flag (0=off, 1=on; lockstep w/ off13)', 'uncertain'),
    18: ('la_?18',    1, 'B',   'Layer A: likely Decay 0-99 (bimodal: 83=kick, 99=snares/toms/cymbals)', 'uncertain'),
    20: ('la_maxv',   1, 'B',   'Layer A: max velocity (always 127 so far)',                   'likely'),

    # Layer B  (bytes 24-43)
    24: ('lb_idx',    2, '<H',  'Layer B: instrument index (0xFFFF = none)',                    'confirmed'),
    26: ('lb_level',  1, 'B',   'Layer B: output level 0-127',                                 'likely'),
    27: ('lb_pan',    1, 'b',   'Layer B: pan -50 to +50 (int8; mirrors la_pan)',              'confirmed'),
    28: ('lb_?28',    1, 'B',   'Layer B: unknown (mirrors la_?08; mode=95 for filled layers)', 'uncertain'),
    31: ('lb_pitch',  1, 'b',   'Layer B: pitch semitones -12 to +12 (int8; mirrors la_pitch)', 'likely'),
    33: ('lb_?33',    1, 'B',   'Layer B: likely Filter Cutoff (mirrors la_?13)',               'uncertain'),
    34: ('lb_filt_f', 1, 'B',   'Layer B: likely Filter Enable/Type flag (mirrors la_filt_f)', 'uncertain'),
    38: ('lb_?38',    1, 'B',   'Layer B: likely Decay (mirrors la_?18)',                      'uncertain'),
    40: ('lb_maxv',   1, 'B',   'Layer B: max velocity (always 127 so far)',                   'likely'),

    # Pad global  (bytes 44-71)
    44: ('xfade_v',   1, 'B',   'Layer B velocity xfade threshold (0=off; 70 on 2-layer pads)','likely'),
    46: ('active_l',  1, 'B',   'Active-layers flag (0=none, 1=A active)',                    'likely'),
    52: ('midi_note', 1, 'B',   'MIDI note - GM drum map: 36=kick, 38=snare, 42=closed-HH',   'confirmed'),
    56: ('choke_grp', 5, '5s',  'Choke group assignment (0xFFx5 = no choke)',                  'likely'),
}

FIELD_RANGES: set = set()
for _off, (_n, _w, *_rest) in FIELDS.items():
    FIELD_RANGES.update(range(_off, _off + _w))

CONF_MARK = {'confirmed': '[v]', 'likely': '[~]', 'uncertain': '[?]'}

GM_DRUMS = {
    35: 'Ac.Bass Drum',  36: 'Bass Drum 1',   37: 'Side Stick',
    38: 'Ac.Snare',      39: 'Hand Clap',      40: 'Elec.Snare',
    41: 'Lo Floor Tom',  42: 'Closed HH',      43: 'Hi Floor Tom',
    44: 'Pedal HH',      45: 'Lo Tom',         46: 'Open HH',
    47: 'Lo-Mid Tom',    48: 'Hi-Mid Tom',      49: 'Crash 1',
    50: 'Hi Tom',        51: 'Ride 1',          52: 'Chinese',
    53: 'Ride Bell',     54: 'Tambourine',      55: 'Splash',
    56: 'Cowbell',       57: 'Crash 2',         58: 'Vibraslap',
    59: 'Ride 2',        60: 'Hi Bongo',        61: 'Lo Bongo',
}

SECTIONS = [
    ('Pad header',         range(0,   4)),
    ('Layer A  (4-23)',    range(4,  24)),
    ('Layer B  (24-43)',   range(24, 44)),
    ('Pad global (44-71)', range(44, 72)),
]


def hexdump(data: bytes, width: int = 16) -> list:
    lines = []
    for i in range(0, len(data), width):
        chunk     = data[i:i + width]
        hex_part  = ' '.join(f'{b:02x}' for b in chunk)
        hex_part  = f'{hex_part:<{width * 3}}'
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'  {i:04x}  {hex_part}  |{ascii_str}|')
    return lines


def fmt_field(name, width, fmt, desc, conf, off, payload, instruments):
    mark = CONF_MARK[conf]
    raw  = payload[off: off + width]
    if fmt in ('4s', '5s'):
        hex_val = ' '.join(f'{b:02x}' for b in raw)
        val_str = f'[{hex_val}]'
        if all(b == 0xFF for b in raw):
            val_str += '  (all 0xFF)'
    elif fmt == 'b':
        v = struct.unpack_from('b', payload, off)[0]
        val_str = f'{v:+d} semitones'
    elif fmt == 'B':
        v = struct.unpack_from('B', payload, off)[0]
        val_str = f'{v:#04x} = {v}'
        if name == 'midi_note':
            gm = GM_DRUMS.get(v, '?')
            val_str += f'  ({gm})'
        elif name in ('la_idx', 'lb_idx'):
            pass  # handled separately
    elif fmt == '<H':
        v = struct.unpack_from('<H', payload, off)[0]
        val_str = f'{v:#06x} = {v}'
        if v == 0xFFFF:
            val_str += '  -> (none)'
        elif name in ('la_idx', 'lb_idx') and v < len(instruments):
            val_str += f'  -> {instruments[v]}'
        elif name in ('la_idx', 'lb_idx'):
            val_str += '  -> ?'
    else:
        val_str = repr(raw)

    return f'  |  {mark} off {off:3d}  {name:<10}  {val_str}'


def fmt_unknown(off, payload):
    v   = payload[off]
    s8  = v if v < 128 else v - 256
    nxt = payload[off + 1] if off + 1 < len(payload) else None
    u16 = (payload[off] | (nxt << 8)) if nxt is not None else None
    u16_str = f'  u16le={u16:#06x}({u16})' if u16 is not None else ''
    return f'  |  [.] off {off:3d}  ?          {v:#04x}={v:3d}  s8={s8:4d}{u16_str}'


def parse_skt(data: bytes):
    assert data[:4] == b'KIT ', 'Not a KIT file'
    kit_size = struct.unpack_from('<I', data, 4)[0]
    pos = 8 + kit_size

    pads = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == b'inst':
        blk_size = struct.unpack_from('<I', data, pos + 4)[0]
        payload  = bytes(data[pos + 8: pos + 8 + blk_size])
        pad_id   = payload[:4].decode('ascii', errors='replace').rstrip('\x00').strip()
        pads.append((pad_id, payload))
        pos += 8 + blk_size

    instruments = []
    if pos + 8 <= len(data) and data[pos:pos + 4] == b'str ':
        str_size = struct.unpack_from('<I', data, pos + 4)[0]
        str_data = data[pos + 8: pos + 8 + str_size]
        i = 0
        while i < len(str_data):
            try:
                end = str_data.index(b'\x00', i)
            except ValueError:
                break
            s = str_data[i:end].decode('ascii', errors='replace')
            if s:
                instruments.append(s)
            i = end + 1

    return pads, instruments


def dump_pad(pad_id: str, payload: bytes, instruments: list):
    print(f'\n  +-- PAD: {pad_id:<6}  ({len(payload)} bytes)')
    print(f'  |  Confidence: [v]=confirmed  [~]=likely  [?]=uncertain  [.]=truly unknown')

    for sect_name, sect_range in SECTIONS:
        print(f'  |')
        print(f'  |  -- {sect_name} --')

        # Emit known fields in this section
        for off in sorted(FIELDS):
            name, width, fmt, desc, conf = FIELDS[off]
            if off not in sect_range:
                continue
            line = fmt_field(name, width, fmt, desc, conf, off, payload, instruments)
            print(line)
            # Print description indented
            print(f'  |             {desc}')

        # Emit unknown non-zero bytes in this section
        printed_any_unk = False
        for i in sect_range:
            if i < len(payload) and i not in FIELD_RANGES and payload[i] != 0x00:
                if not printed_any_unk:
                    print(f'  |')
                    printed_any_unk = True
                print(fmt_unknown(i, payload))

    # Full hex dump
    print(f'  |')
    print(f'  |  -- full payload hex --')
    for line in hexdump(payload):
        print(f'  |{line}')

    print(f'  +' + '-' * 68)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f'ERROR: file not found: {path}')
        sys.exit(1)

    filter_pad = sys.argv[2].upper() if len(sys.argv) > 2 else None

    data = path.read_bytes()
    pads, instruments = parse_skt(data)

    bar = '=' * 72
    print(f'\n{bar}')
    print(f'  File : {path.name}')
    print(f'  Pads : {len(pads)}    Instruments in str table: {len(instruments)}')
    if filter_pad:
        print(f'  Filter: showing only pad "{filter_pad}"')
    print(bar)

    shown = 0
    for pad_id, payload in pads:
        if filter_pad and pad_id.upper() != filter_pad:
            continue
        dump_pad(pad_id, payload, instruments)
        shown += 1

    if filter_pad and shown == 0:
        print(f'\n  (no pad matched "{filter_pad}")')

    print(f'\n  String table ({len(instruments)} entries):')
    for i, s in enumerate(instruments):
        print(f'    [{i:3d}]  {s}')
    print()


if __name__ == '__main__':
    main()
