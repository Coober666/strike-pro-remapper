"""Synthetic Python/Swift inspector parity fixtures; no library or device reads."""
import base64
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.formats import PAD_ORDER, build_skt, parse_skt

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / 'native/StrikeCompanioniOS/Tests/KitCases.json'
DEMO = ROOT / 'native/StrikeCompanioniOS/Resources/Demo.skt'


def fixtures():
    pads = []
    for i, pad in enumerate(PAD_ORDER):
        raw = bytearray(range(64))  # Nonzero reserved bytes must survive inspection.
        raw[:4] = (pad + ' ').encode('ascii')
        raw[6], raw[7], raw[8], raw[11], raw[12] = 100, 206, 99, 244, 251
        raw[13], raw[14], raw[21] = 80, 1, 0
        raw[19], raw[20], raw[26], raw[27], raw[39], raw[40] = 1, 127, 80, 50, 64, 127
        raw[28], raw[31], raw[32], raw[33], raw[34], raw[41] = 70, 7, 3, 70, 0, 0
        raw[44], raw[45], raw[46], raw[48], raw[49], raw[50], raw[53], raw[54], raw[61] = 20, 30, 1, 1, 0, 0, 255, 1, 10
        raw[51], raw[52] = 9, 38
        instrument = {'K': 0, 'S': 1, 'T': 3, 'H': 4, 'C': 5, 'R': 6}[pad[0]]
        pads.append(dict(id=pad, payload=raw, layer_a=instrument, layer_b=2 if pad == 'S1H' else 65535))
    header = b'KIT ' + struct.pack('<I', 44) + bytes(range(44))
    demo = build_skt(header, pads, ['Synthetic/Kick.sin', 'Synthetic/Snare.sin', 'Synthetic/Brush Snare.sin',
                                       'Synthetic/Tom.sin', 'Synthetic/Hi-Hat.sin', 'Synthetic/Crash.sin', 'Synthetic/Ride.sin'], b'\x00\xffopaque tail')
    unknown = build_skt(header, [dict(id='ZZZ', payload=bytearray(b'ZZZ ' + bytes(60)), layer_a=42, layer_b=65535)], ['../../reference-only.sin'])
    empty = build_skt(header, [], [], b'')
    cases = []
    for name, data in [('complete', demo), ('unknown-zone-unresolved-reference', unknown), ('empty', empty)]:
        kit, parsed, refs, tail = parse_skt(data)
        expected = dict(header=kit.hex(), tail=tail.hex(), instruments=refs,
                        pads=[dict(id=p['id'], a=p['layer_a'], b=p['layer_b'], payload=p['payload'].hex(),
                                   level=p['payload'][6], pan=struct.unpack_from('b', p['payload'], 7)[0],
                                   pitch=struct.unpack_from('b', p['payload'], 11)[0]) for p in parsed])
        cases.append(dict(name=name, data=base64.b64encode(data).decode(), expected=expected))
    invalid = [('empty-file', b''), ('wrong-magic', b'NOPE' + demo[4:]), ('truncated-header', demo[:6]),
               ('overflow-size', b'KIT \xff\xff\xff\xff'), ('short-kit', b'KIT \x00\x00\x00\x00'),
               ('missing-strings', header), ('short-pad', header + b'inst\x04\x00\x00\x00K1H '),
               ('unterminated-reference', header + b'str \x01\x00\x00\x00x'),
               ('truncated-strings', header + b'str \xff\xff\xff\xff'),
               ('non-ascii-reference', header + b'str \x02\x00\x00\x00\xff\x00')]
    raw_pad = demo[len(header):len(header) + 72]
    invalid.extend([
        ('too-many-pads', header + raw_pad * 129 + b'str \x00\x00\x00\x00'),
        ('too-many-references', header + b'str ' + struct.pack('<I', 8194) + b'x\x00' * 4097),
        ('long-reference', header + b'str ' + struct.pack('<I', 242) + b'x' * 241 + b'\x00'),
        ('control-in-pad-id', header + raw_pad[:8] + b'K1H\x01' + raw_pad[12:] + b'str \x00\x00\x00\x00'),
    ])
    for name, data in invalid:
        cases.append(dict(name=name, data=base64.b64encode(data).decode(), expected=None))
    return cases, demo


def main():
    cases, demo = fixtures()
    encoded = json.dumps(cases, indent=2) + '\n'
    if sys.argv[1:] == ['--write']:
        CASES.write_text(encoded)
        DEMO.parent.mkdir(exist_ok=True)
        DEMO.write_bytes(demo)
    else:
        assert not sys.argv[1:]
        assert CASES.read_text() == encoded, 'Regenerate with tools/test_kit_inspector_format.py --write'
        assert DEMO.read_bytes() == demo
    print(f'{len(cases)} synthetic kit-inspector format cases match Python; no private assets read.')


if __name__ == '__main__':
    main()
