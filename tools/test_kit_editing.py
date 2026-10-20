"""Synthetic Swift editing oracle from the Python editor's confirmed map/writer; no library reads."""
import ast
import base64
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper import formats
from test_kit_inspector_format import fixtures

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'native/StrikeCompanioniOS/Tests/KitEditingCases.json'


def cases():
    # Read only the literal map, without importing server startup or mutable library state.
    tree = ast.parse((ROOT / 'strike_remap.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == '_PARAM_MAP' for t in n.targets))
    param_map = eval(compile(ast.Expression(node.value), '<confirmed-param-map>', 'eval'),
                     {'__builtins__': {}}, vars(formats))
    names = {
        'Level': 'level', 'Pan': 'pan', 'Decay': 'decay', 'Pitch': 'pitch', 'Fine': 'fine',
        'Cutoff': 'fcut', 'Filter': 'fflag', 'VelocityDecay': 'vel_dec', 'VelocityPitch': 'vel_pch',
        'VelocityFilter': 'vel_flt', 'VelocityVolume': 'vel_vol', 'VelocityMinimum': 'vel_min',
        'VelocityMaximum': 'vel_max', 'Loop': 'loop',
    }
    mapping = {side + swift: ('l' + side + '_' + python)
               for side in ('a', 'b') for swift, python in names.items()
               if (side, swift) != ('b', 'VelocityMaximum')}
    mapping['bVelocityMinimum'] = 'xfade_vel'
    mapping.update(reverb='reverb', fx1='fx1', fx2='fx2', eqComp='eq_comp', priority='priority',
                   noteOff='note_off', midiChannel='midi_chan', midiNote='midi_note', playback='play_mode')
    assert set(mapping.values()) == set(param_map)
    specs = {swift: param_map[python] for swift, python in mapping.items()}
    specs.update(muteGroup=(formats.MUTE_GRP_OFF, 'B', 0, 9),
                 gateTime=(formats.GATE_TIME_OFF, 'B', 0, 255),
                 midiChannel=(formats.MIDI_CHAN_OFF, 'B', 1, 16))
    _, source = fixtures()
    header, pads, refs, tail = formats.parse_skt(source)
    for pad in pads:
        pad['payload'][19] = 0
        pad['payload'][39] = 0
    source = formats.build_skt(header, pads, refs, tail)
    assert formats.build_skt(*formats.parse_skt(source)) == source
    result = []
    for swift, (offset, fmt, low, high) in specs.items():
        values = [low, high, low - 1, high + 1]
        if swift == 'gateTime':
            values += [99, 100, 109, 110, 254]
        for value in values:
            valid = low <= value <= high and (swift != 'gateTime' or value <= 109 or value == 255)
            expected = None
            if valid:
                kit, updated, strings, opaque = formats.parse_skt(source)
                stored = value - 1 if swift == 'midiChannel' else value
                struct.pack_into(fmt, updated[2]['payload'], offset, stored)
                expected = formats.build_skt(kit, updated, strings, opaque)
                absolute = len(kit) + 2 * 72 + 8 + offset
                assert all(a == b or i == absolute for i, (a, b) in enumerate(zip(source, expected)))
            result.append(dict(parameter=swift, value=value, expected=encode(expected)))
    for layer in (0, 1):
        for reference in (0, len(refs) - 1, 65535, -1, len(refs), 65536):
            expected = None
            if reference == 65535 or 0 <= reference < len(refs):
                kit, updated, strings, opaque = formats.parse_skt(source)
                updated[2]['layer_a' if layer == 0 else 'layer_b'] = reference
                expected = formats.build_skt(kit, updated, strings, opaque)
            result.append(dict(layer=layer, value=reference, expected=encode(expected)))
    return dict(source=encode(source), cases=result)


def encode(data):
    return base64.b64encode(data).decode() if data is not None else None


def main():
    payload = cases()
    encoded = json.dumps(payload, indent=2) + '\n'
    if sys.argv[1:] == ['--write']:
        OUTPUT.write_text(encoded, encoding='utf-8')
    else:
        assert not sys.argv[1:]
        assert OUTPUT.read_text(encoding='utf-8') == encoded, 'Regenerate with tools/test_kit_editing.py --write'
    print(f"{len(payload['cases'])} synthetic editing cases match Python's confirmed map and binary writer.")


if __name__ == '__main__':
    main()
