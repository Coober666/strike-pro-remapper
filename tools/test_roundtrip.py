#!/usr/bin/env python3
"""
test_roundtrip.py — verify parse_skt() → build_skt() is lossless.

Usage:
    python tools/test_roundtrip.py                  # tests all kits in library/kits/
    python tools/test_roundtrip.py path/to/kit.skt  # test specific files
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr


def test_file(path: Path) -> bool:
    original = path.read_bytes()
    try:
        kit_raw, pads, instruments, tail = sr.parse_skt(original)
    except Exception as e:
        print(f'  PARSE ERROR  {e}')
        return False

    rebuilt = sr.build_skt(kit_raw, pads, instruments, tail)

    if original == rebuilt:
        print(f'  PASS  ({len(original)} bytes)')
        return True

    # Find first differing byte for diagnosis
    min_len = min(len(original), len(rebuilt))
    first_diff = next((i for i in range(min_len) if original[i] != rebuilt[i]), min_len)
    print(f'  FAIL  original={len(original)}B  rebuilt={len(rebuilt)}B  '
          f'first diff at byte {first_diff} (0x{first_diff:04x})')
    # Show a hex window around the first difference
    lo = max(0, first_diff - 4)
    hi = min(min_len, first_diff + 12)
    print(f'    original[{lo}:{hi}]: {original[lo:hi].hex(" ")}')
    print(f'    rebuilt [{lo}:{hi}]: {rebuilt[lo:hi].hex(" ")}')
    return False


def main():
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        lib = Path(__file__).resolve().parent.parent / 'library' / 'kits'
        paths = sorted(lib.glob('*.skt'))
        if not paths:
            print('No .skt files found in library/kits/. Pass a path as argument.')
            sys.exit(1)

    passed = failed = 0
    for p in paths:
        print(p.name)
        if test_file(p):
            passed += 1
        else:
            failed += 1

    print(f'\n{passed} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
