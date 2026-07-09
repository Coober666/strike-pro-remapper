#!/usr/bin/env python3
"""
test_sin_roundtrip.py — verify parse_sin() / patch_sin() preserve .sin files exactly.

For every instrument: a no-op patch and an identity patch (writing every parsed value
back unchanged) must both reproduce the original bytes, and parsed values must fall
inside their documented ranges.

Usage:
    python tools/test_sin_roundtrip.py                  # tests all library instruments
    python tools/test_sin_roundtrip.py path/to/i.sin    # test specific files
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr


def test_file(path: Path) -> bool:
    original = path.read_bytes()
    try:
        parsed = sr.parse_sin(original)
    except Exception as e:
        print(f'FAIL {path.name}: parse error: {e}')
        return False

    for name, (_, _, lo, hi) in sr._SIN_PARAM_MAP.items():
        v = parsed['params'][name]
        if not lo <= v <= hi:
            print(f'FAIL {path.name}: {name}={v} outside [{lo},{hi}]')
            return False

    if sr.patch_sin(original) != original:
        print(f'FAIL {path.name}: no-op patch changed bytes')
        return False

    identity = sr.patch_sin(
        original,
        params=parsed['params'],
        cycle_random=parsed['cycle_random'],
        mappings=[{'index': i, **{k: m[k] for k in ('vmin', 'vmax', 'rr', 'hh_min', 'hh_max')}}
                  for i, m in enumerate(parsed['mappings'])],
    )
    if identity != original:
        diff = next(i for i in range(len(original)) if original[i] != identity[i])
        print(f'FAIL {path.name}: identity patch differs at byte {diff}')
        return False
    return True


def main():
    if len(sys.argv) > 1:
        files = [Path(a) for a in sys.argv[1:]]
    else:
        root = Path(__file__).resolve().parent.parent / 'library' / 'instruments'
        files = sorted(root.rglob('*.sin'))
    if not files:
        print('No .sin files found')
        sys.exit(1)

    passed = failed = 0
    for f in files:
        if test_file(f):
            passed += 1
        else:
            failed += 1
    print(f'\n{passed} passed, {failed} failed  ({passed + failed} instruments)')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
