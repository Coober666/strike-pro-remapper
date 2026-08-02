"""Pure parsers and writers for Strike kit and instrument formats."""

import struct


# .skt pad identities and payload layout.
PAD_LABEL = {
    "K1H": "Kick 1 Head",      "K2H": "Kick 2 Head",
    "S1H": "Snare Head",       "S1R": "Snare Rim",
    "T1H": "Tom 1 Head",       "T1R": "Tom 1 Rim",
    "T2H": "Tom 2 Head",       "T2R": "Tom 2 Rim",
    "T3H": "Tom 3 Head",       "T3R": "Tom 3 Rim",
    "T4H": "Tom 4 Head",       "T4R": "Tom 4 Rim",
    "H1B": "Hi-Hat Bow",       "H1E": "Hi-Hat Edge",  "H1F": "Hi-Hat Foot",
    "C1B": "Cymbal 1 Bow",     "C1E": "Cymbal 1 Edge",
    "C2B": "Cymbal 2 Bow",     "C2E": "Cymbal 2 Edge",
    "C3B": "Cymbal 3 Bow",     "C3E": "Cymbal 3 Edge",
    "R1D": "Ride Bell",        "R1B": "Ride Bow",     "R1E": "Ride Edge",
}

PAD_INPUT = {
    "K1H": "KICK",              "K2H": "KICK (2nd)",
    "S1H": "SNARE · tip",       "S1R": "SNARE · ring",
    "T1H": "TOM 1 · tip",       "T1R": "TOM 1 · ring",
    "T2H": "TOM 2 · tip",       "T2R": "TOM 2 · ring",
    "T3H": "TOM 3 · tip",       "T3R": "TOM 3 · ring",
    "T4H": "TOM 4 · tip",       "T4R": "TOM 4 · ring",
    "H1B": "HI-HAT · tip",      "H1E": "HI-HAT · ring",  "H1F": "HH CONTROL",
    "C1B": "CRASH 1 · tip",     "C1E": "CRASH 1 · ring",
    "C2B": "CRASH 2 · tip",     "C2E": "CRASH 2 · ring",
    "C3B": "CRASH 3 · tip",     "C3E": "CRASH 3 · ring",
    "R1B": "RIDE 1 · tip",      "R1E": "RIDE 1 · ring",
    "R1D": "RIDE 2",
}

PAD_ORDER = [
    'K1H', 'K2H',
    'S1H', 'S1R',
    'T1H', 'T1R', 'T2H', 'T2R', 'T3H', 'T3R', 'T4H', 'T4R',
    'H1B', 'H1E', 'H1F',
    'C1B', 'C1E', 'C2B', 'C2E', 'C3B', 'C3E',
    'R1D', 'R1B', 'R1E',
]

DEFAULT_MIDI_NOTE = {
    'K1H': 36, 'K2H': 36,
    'S1H': 38, 'S1R': 37,
    'T1H': 48, 'T1R': 37, 'T2H': 47, 'T2R': 37,
    'T3H': 45, 'T3R': 37, 'T4H': 43, 'T4R': 37,
    'H1B': 42, 'H1E': 46, 'H1F': 44,
    'C1B': 49, 'C1E': 49, 'C2B': 57, 'C2E': 57, 'C3B': 55, 'C3E': 55,
    'R1D': 53, 'R1B': 51, 'R1E': 59,
}

LAYER_A_IDX_OFF = 4   # uint16 LE offset within payload for Layer A str index
LAYER_B_IDX_OFF = 24  # uint16 LE offset within payload for Layer B str index
NO_INSTRUMENT = 0xFFFF

# Additional payload offsets (relative to start of inst block payload).
# NOTE: every offset below is hardware-confirmed as of May 2026 (hex diff against
# official-editor saves) — see FORMAT.md for the authoritative table. The bracketed
# tags record how each one was originally discovered.
MIDI_NOTE_OFF  = 52   # uint8  — GM MIDI note number         [confirmed]
LA_LEVEL_OFF   =  6   # uint8  — Layer A output level 0–127  [confirmed]
LA_PAN_OFF     =  7   # int8   — Layer A pan, -50 to +50     [CONFIRMED: user set hard-left → 0xce=-50]
LA_PITCH_OFF   = 11   # int8   — Layer A pitch, -12 to +12 semitones [CONFIRMED: was statistical
                       #          analysis of 116 preset kits; int8 mode=0, range 1-12 / 244-255]
LA_FCUT_OFF    = 13   # uint8  — Layer A Filter Cutoff 0-99   [CONFIRMED: was SEVEN REC diff + mode=99]
LA_FFLAG_OFF   = 14   # uint8  — Layer A Filter Enable flag    [CONFIRMED: 0=off, 1=on]
LA_DECAY_OFF    =  8   # uint8  — Layer A Decay 0-99            [CONFIRMED: screenshot K1H Decay=99=payload[8]]
LA_VEL_DEC_OFF  = 15   # uint8  — Layer A Velocity→Decay        [CONFIRMED: hex diff]
LA_VEL_PCH_OFF  = 16   # uint8  — Layer A Velocity→Pitch        [CONFIRMED: hex diff]
LA_VEL_FLT_OFF  = 17   # uint8  — Layer A Velocity→Filter       [CONFIRMED: hex diff]
LA_VEL_VOL_OFF  = 18   # uint8  — Layer A Velocity→Volume 0-127 [CONFIRMED: screenshot K1H VelVol=90=payload[18]]
LA_VEL_MIN_OFF  = 19   # uint8  — Layer A velocity range min 0-127 [CONFIRMED: mirrors LB off 39=XFADE_VEL]
LA_VEL_MAX_OFF  = 20   # uint8  — Layer A velocity range max 0-127 [CONFIRMED: mirrors LB off 40=always 127]
LB_LEVEL_OFF    = 26   # uint8  — Layer B output level 0–127  [confirmed]
LB_PAN_OFF      = 27   # int8   — Layer B pan, -50 to +50     [confirmed by symmetry]
LB_PITCH_OFF    = 31   # int8   — Layer B pitch, -12 to +12 semitones [mirrors LA_PITCH_OFF+20]
LB_FCUT_OFF     = 33   # uint8  — Layer B Filter Cutoff 0-99   [mirrors LA_FCUT_OFF+20]
LB_FFLAG_OFF    = 34   # uint8  — Layer B Filter Enable flag    [mirrors LA_FFLAG_OFF+20]
LB_DECAY_OFF    = 28   # uint8  — Layer B Decay 0-99            [CONFIRMED: mirrors LA_DECAY_OFF+20]
LB_VEL_DEC_OFF  = 35   # uint8  — Layer B Velocity→Decay        [CONFIRMED: by symmetry +20]
LB_VEL_PCH_OFF  = 36   # uint8  — Layer B Velocity→Pitch        [CONFIRMED: by symmetry +20]
LB_VEL_FLT_OFF  = 37   # uint8  — Layer B Velocity→Filter       [CONFIRMED: by symmetry +20]
LB_VEL_VOL_OFF  = 38   # uint8  — Layer B Velocity→Volume 0-127 [CONFIRMED: screenshot K1H VelVol=83=payload[38]]
XFADE_VEL_OFF   = 39   # uint8  — Layer B velocity minimum (xfade threshold) [CONFIRMED: hex diff]
EQ_COMP_OFF     = 46   # uint8  — EQ/Comp enable (0=off, 1=on)  [CONFIRMED: hex diff]
REVERB_OFF      = 44   # uint8  — FX Reverb send level 0-99     [CONFIRMED: hex diff — was wrongly XFADE_VEL_OFF]
FX1_OFF         = 45   # uint8  — FX1 send level 0-99           [CONFIRMED: hex diff]
FX2_OFF         = 61   # uint8  — FX2 send level 0-99           [CONFIRMED: hex diff]
PRIORITY_OFF    = 48   # uint8  — Playback priority (0=Low,1=Med,2=High) [CONFIRMED: hex diff]
MUTE_GRP_OFF    = 49   # uint8  — mute/choke group: 0=off, 1–9=groups 1–9 [CONFIRMED: hex diff]
NOTE_OFF_OFF    = 50   # uint8  — Note Off mode (0=SENT,1=NONE,2=ALT)     [CONFIRMED: hex diff]
MIDI_CHAN_OFF   = 51   # uint8  — MIDI channel, 0-indexed (0=ch1…15=ch16) [CONFIRMED: hex diff]
GATE_TIME_OFF   = 53   # uint8  — Gate time: 0–99 = Free (ms), 100–109 = Sync:32…Sync:2T, 255 = OFF
                       #   ✅ FULL LUT CONFIRMED via hex diff; ms semantics per official editor guide p.8
PLAY_MODE_OFF   = 54   # uint8  — Playback mode (0=Mono, 1=Poly)          [CONFIRMED: hex diff]
LA_FINE_OFF     = 12   # int8   — Layer A fine pitch -50 to +50 cents      [CONFIRMED: hex diff]
LB_FINE_OFF     = 32   # int8   — Layer B fine pitch -50 to +50 cents      [CONFIRMED: mirrors LA_FINE_OFF+20]
LA_LOOP_OFF     = 21   # uint8  — Layer A loop mode (0=OFF, 1=ON)          [CONFIRMED: hex diff]
LB_LOOP_OFF     = 41   # uint8  — Layer B loop mode (0=OFF, 1=ON)          [CONFIRMED: mirrors LA_LOOP_OFF+20]

GM_DRUMS = {
    35: 'Ac.Bass Drum',  36: 'Bass Drum 1',  37: 'Side Stick',
    38: 'Ac.Snare',      39: 'Hand Clap',    40: 'Elec.Snare',
    41: 'Lo Floor Tom',  42: 'Closed HH',    43: 'Hi Floor Tom',
    44: 'Pedal HH',      45: 'Lo Tom',       46: 'Open HH',
    47: 'Lo-Mid Tom',    48: 'Hi-Mid Tom',   49: 'Crash 1',
    50: 'Hi Tom',        51: 'Ride 1',       52: 'Chinese',
    53: 'Ride Bell',     54: 'Tambourine',   55: 'Splash',
    56: 'Cowbell',       57: 'Crash 2',      58: 'Vibraslap',
    59: 'Ride 2',        60: 'Hi Bongo',     61: 'Lo Bongo',
}


def parse_skt(data: bytes):
    """
    Parse a raw .skt file.
    Returns (kit_raw_header, pads, instruments, tail) where:
      kit_raw_header  = raw bytes of the KIT block (header+size+data)
      pads            = list of dicts: {id, label, layer_a, layer_b, payload}
      instruments     = list of str paths in order (the str table)
      tail            = any bytes after the str block (null padding, unknown blocks)
    """
    assert data[:4] == b'KIT ', "Not a KIT file"
    kit_size = struct.unpack_from('<I', data, 4)[0]
    kit_raw = data[:8 + kit_size]
    pos = 8 + kit_size

    pads = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == b'inst':
        block_size = struct.unpack_from('<I', data, pos + 4)[0]
        payload = bytearray(data[pos + 8:pos + 8 + block_size])
        pad_id = bytes(payload[:4]).decode('ascii', errors='replace').strip()
        layer_a = struct.unpack_from('<H', payload, LAYER_A_IDX_OFF)[0]
        layer_b = struct.unpack_from('<H', payload, LAYER_B_IDX_OFF)[0]
        pads.append({
            'id': pad_id,
            'label': PAD_LABEL.get(pad_id, pad_id),
            'layer_a': layer_a,
            'layer_b': layer_b,
            'payload': payload,
        })
        pos += 8 + block_size

    instruments = []
    tail = b''
    if pos + 8 <= len(data) and data[pos:pos + 4] == b'str ':
        str_size = struct.unpack_from('<I', data, pos + 4)[0]
        str_data = data[pos + 8:pos + 8 + str_size]
        index = 0
        while index < len(str_data):
            try:
                end = str_data.index(b'\x00', index)
            except ValueError:
                break
            value = str_data[index:end].decode('ascii', errors='replace')
            if value:
                instruments.append(value)
            index = end + 1
        tail = data[pos + 8 + str_size:]

    return kit_raw, pads, instruments, tail


def build_skt(kit_raw: bytes, pads: list, instruments: list,
              tail: bytes = b'') -> bytes:
    """Reassemble a .skt from its components."""
    out = bytearray(kit_raw)

    for pad in pads:
        payload = pad['payload']
        struct.pack_into('<H', payload, LAYER_A_IDX_OFF, pad['layer_a'])
        struct.pack_into('<H', payload, LAYER_B_IDX_OFF, pad['layer_b'])
        block_size = len(payload)
        out += b'inst'
        out += struct.pack('<I', block_size)
        out += bytes(payload)

    str_bytes = b''.join(value.encode('ascii') + b'\x00' for value in instruments)
    out += b'str '
    out += struct.pack('<I', len(str_bytes))
    out += str_bytes
    out += tail
    return bytes(out)


# INST block: 24-byte instrument-level params (cloned from 808 Clap.sin,
# group=CLAPS_SFX).
_SIN_INST_BYTES = bytes([
    0x00, 0x12, 0x01, 0x00, 0x00, 0x00, 0x4b, 0x00,
    0x63, 0x00, 0x00, 0x00, 0x00, 0x7f, 0x00, 0x00,
    0x00, 0x00, 0x4f, 0x00, 0x7f, 0x00, 0x00, 0x00,
])


def _build_sin(entries: list) -> bytes:
    """Build a .sin file from (wav path, min velocity, max velocity, RR index)."""
    inst_block = b'INST' + struct.pack('<I', len(_SIN_INST_BYTES)) + _SIN_INST_BYTES

    count = len(entries)
    msmp_payload = bytearray([0x00, 0x00, count & 0xFF, 0x00])
    for i, (wav_rel, min_vel, max_vel, rr_index) in enumerate(entries):
        mapping = bytearray(28)
        struct.pack_into('<H', mapping, 0, i)
        mapping[2] = 0x63
        mapping[3] = min_vel & 0xFF
        mapping[4] = max_vel & 0xFF
        mapping[5] = 0x00
        mapping[6] = 0x7F
        mapping[7] = max(1, rr_index) & 0xFF
        mapping[11] = 0x7F
        mapping[18] = 0x40
        mapping[24] = 0x3C
        msmp_payload += bytes(mapping)
    msmp_block = b'msmp' + struct.pack('<I', len(msmp_payload)) + bytes(msmp_payload)

    wav_bytes = b''.join(wav_rel.encode('ascii') + b'\x00' for wav_rel, *_ in entries)
    str_block = b'str ' + struct.pack('<I', len(wav_bytes)) + wav_bytes
    return inst_block + msmp_block + str_block


def parse_sin_first_wav(data: bytes) -> str | None:
    """Return the first WAV path from a .sin string block, or None."""
    pos = 0
    while pos + 8 <= len(data):
        magic = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        if magic == b'str ':
            str_data = data[pos + 8:pos + 8 + size]
            for raw in str_data.split(b'\x00'):
                value = raw.decode('ascii', errors='replace').strip()
                if value and value.lower().endswith(('.wav', '.wave')):
                    return value
            break
        if pos + 8 + size > len(data):
            break
        pos += 8 + size
    return None


def parse_sin_all_wavs(data: bytes) -> list:
    """Return every WAV path listed in a .sin string block."""
    pos = 0
    while pos + 8 <= len(data):
        magic = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        if magic == b'str ':
            str_data = data[pos + 8:pos + 8 + size]
            return [
                raw.decode('ascii', errors='replace').strip()
                for raw in str_data.split(b'\x00')
                if raw and raw.decode('ascii', errors='replace').strip().lower()
                .endswith(('.wav', '.wave'))
            ]
        if pos + 8 + size > len(data):
            break
        pos += 8 + size
    return []


SIN_GROUPS = {
    0: 'Kick', 1: 'Snare', 2: 'Tom', 3: 'Hi-Hat', 4: 'Crash', 5: 'Ride',
    6: 'Group 6', 7: 'E. Kick', 8: 'E. Snare', 9: 'E. Tom', 10: 'Percussion',
    11: 'Perc Ethnic', 12: 'Group 12', 13: 'Perc Orchestral', 14: 'E. Perc',
    15: 'Group 15', 16: 'Group 16', 17: 'Group 17', 18: 'Claps/SFX', 19: 'Melodic',
}

# name: (offset into INST payload, signed, lo, hi)
_SIN_PARAM_MAP = {
    'group': (1, False, 0, 19),
    'level': (6, False, 0, 127),
    'pan': (7, True, -50, 50),
    'decay': (8, False, 0, 127),
    'semi': (11, True, -12, 12),
    'fine': (12, True, -50, 50),
    'cutoff': (13, False, 0, 127),
    'hipass': (14, False, 0, 1),
    'vel_decay': (15, True, -99, 99),
    'vel_pitch': (16, True, -99, 99),
    'vel_filter': (17, True, -99, 99),
    'vel_level': (18, True, -99, 99),
    'loop': (21, False, 0, 1),
}

_SIN_MAPPING_SIZE = 28


def _sin_blocks(data: bytes) -> dict:
    """Walk .sin chunks into {magic: (payload offset, payload size)}."""
    blocks, pos = {}, 0
    while pos + 8 <= len(data):
        magic = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        if pos + 8 + size > len(data):
            break
        blocks[magic] = (pos + 8, size)
        pos += 8 + size
    return blocks


def parse_sin(data: bytes) -> dict:
    """Parse a .sin file into params, cycle mode, mappings, and strings."""
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or blocks[b'INST'][1] < 24:
        raise ValueError('Not a valid .sin file (missing INST block)')
    inst_offset, _ = blocks[b'INST']

    def value_at(offset, signed):
        value = data[inst_offset + offset]
        return value - 256 if signed and value > 127 else value

    params = {
        name: value_at(offset, signed)
        for name, (offset, signed, _, _) in _SIN_PARAM_MAP.items()
    }

    strings = []
    if b'str ' in blocks:
        string_offset, string_size = blocks[b'str ']
        strings = [
            value.decode('ascii', errors='replace')
            for value in data[string_offset:string_offset + string_size].split(b'\x00')
            if value
        ]

    cycle_random, mappings = 0, []
    if b'msmp' in blocks:
        mapping_offset, mapping_size = blocks[b'msmp']
        if mapping_size >= 4:
            cycle_random = data[mapping_offset]
            count = data[mapping_offset + 2]
            for index in range(count):
                offset = mapping_offset + 4 + index * _SIN_MAPPING_SIZE
                if offset + _SIN_MAPPING_SIZE > mapping_offset + mapping_size:
                    break
                string_index = struct.unpack_from('<H', data, offset)[0]
                mappings.append({
                    'sample': strings[string_index]
                    if string_index < len(strings) else f'<str {string_index}>',
                    'vmin': data[offset + 3],
                    'vmax': data[offset + 4],
                    'rr': data[offset + 7],
                    'hh_min': data[offset + 10],
                    'hh_max': data[offset + 11],
                })
    return {
        'params': params,
        'cycle_random': cycle_random,
        'mappings': mappings,
        'strings': strings,
    }


def patch_sin(data: bytes, params: dict = None, cycle_random=None,
              mappings: list = None) -> bytes:
    """Patch known .sin fields in place while preserving unknown bytes."""
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or blocks[b'INST'][1] < 24:
        raise ValueError('Not a valid .sin file (missing INST block)')
    out = bytearray(data)
    inst_offset = blocks[b'INST'][0]

    for name, value in (params or {}).items():
        if name not in _SIN_PARAM_MAP:
            raise ValueError(f'Unknown .sin param: {name}')
        offset, _signed, lo, hi = _SIN_PARAM_MAP[name]
        value = max(lo, min(hi, int(value)))
        out[inst_offset + offset] = value & 0xFF

    if (cycle_random is not None or mappings) and b'msmp' not in blocks:
        raise ValueError('.sin file has no msmp block')
    if b'msmp' in blocks:
        mapping_offset, mapping_size = blocks[b'msmp']
        if cycle_random is not None:
            out[mapping_offset] = 1 if int(cycle_random) else 0
        count = data[mapping_offset + 2] if mapping_size >= 4 else 0
        for mapping in (mappings or []):
            index = int(mapping['index'])
            if not 0 <= index < count:
                raise ValueError(f'Mapping index {index} out of range (count={count})')
            offset = mapping_offset + 4 + index * _SIN_MAPPING_SIZE
            for key, field_offset in (
                ('vmin', 3), ('vmax', 4), ('rr', 7),
                ('hh_min', 10), ('hh_max', 11),
            ):
                if key in mapping and mapping[key] is not None:
                    value = int(mapping[key])
                    if key != 'rr':
                        value = max(0, min(127, value))
                    out[offset + field_offset] = value & 0xFF
    return bytes(out)


def rebuild_sin_zones(data: bytes, zones: list, cycle_random=None) -> bytes:
    """Rebuild .sin mapping and string blocks from a new zone list."""
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or b'msmp' not in blocks or b'str ' not in blocks:
        raise ValueError('Not a rebuildable .sin (missing INST/msmp/str block)')
    if not zones:
        raise ValueError('An instrument needs at least one zone')
    if len(zones) > 255:
        raise ValueError('Too many zones (max 255)')

    old = parse_sin(data)
    old_count = len(old['mappings'])
    mapping_offset, _ = blocks[b'msmp']
    inst_offset, inst_size = blocks[b'INST']

    strings = list(old['strings'])

    def string_index(value):
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    mappings_out = bytearray()
    for zone in zones:
        source = int(zone.get('src', -1))
        if not 0 <= source < old_count:
            raise ValueError(
                f'Zone src index {source} out of range (0-{old_count - 1})'
            )
        offset = mapping_offset + 4 + source * _SIN_MAPPING_SIZE
        block = bytearray(data[offset:offset + _SIN_MAPPING_SIZE])
        original = old['mappings'][source]
        struct.pack_into(
            '<H', block, 0, string_index(zone.get('sample', original['sample']))
        )
        block[3] = max(0, min(127, int(zone['vmin'])))
        block[4] = max(0, min(127, int(zone['vmax'])))
        block[7] = int(zone.get('rr', original['rr'])) & 0xFF
        block[10] = max(0, min(127, int(zone.get('hh_min', original['hh_min']))))
        block[11] = max(0, min(127, int(zone.get('hh_max', original['hh_max']))))
        mappings_out += block

    msmp_header = bytearray(data[mapping_offset:mapping_offset + 4])
    if cycle_random is not None:
        msmp_header[0] = 1 if int(cycle_random) else 0
    msmp_header[2] = len(zones)
    msmp_payload = bytes(msmp_header) + bytes(mappings_out)
    str_payload = b''.join(
        value.encode('ascii', errors='replace') + b'\x00' for value in strings
    )

    out = (
        data[:inst_offset + inst_size]
        + b'msmp' + struct.pack('<I', len(msmp_payload)) + msmp_payload
        + b'str ' + struct.pack('<I', len(str_payload)) + str_payload
    )
    out += b'\x00' * (-len(out) % 4)
    return bytes(out)
