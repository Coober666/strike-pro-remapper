"""Pure parsers and writers for Strike kit and instrument formats."""

import struct


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
