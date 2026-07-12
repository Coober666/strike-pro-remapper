#!/usr/bin/env python3
"""
test_volume_classify.py — unit tests for _classify_volumes (issue #3 / B1-4).

Builds fake card trees in temp dirs and asserts the user/preset assignment is
driven by CONTENT + WRITABILITY, never by dict key (label) or insertion order.
No hardware or library needed. Exit non-zero on failure.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strike_remap as sr  # noqa: E402

FAILURES = []


def check(name, cond):
    print(('  ok  ' if cond else '  FAIL') + ' ' + name)
    if not cond:
        FAILURES.append(name)


def make_user_card(base: Path) -> Path:
    """User card: flat .skt files in Kits/ (plus typical junk dirs)."""
    root = base / 'usercard'
    (root / 'Kits').mkdir(parents=True)
    (root / 'Instruments').mkdir()
    (root / 'Samples').mkdir()
    (root / 'Kits' / 'My Gig Kit.skt').write_bytes(b'\x00')
    (root / 'Don rec.skt').write_bytes(b'\x00')
    return root


def make_preset_card(base: Path) -> Path:
    """Factory preset card: Kits/<CATEGORY>/*.skt category tree."""
    root = base / 'presetcard'
    for cat in ('ACOUSTIC', 'ELECTRONIC'):
        d = root / 'Kits' / cat
        d.mkdir(parents=True)
        (d / f'{cat.title()} Kit 1.skt').write_bytes(b'\x00')
    (root / 'Instruments').mkdir()
    (root / 'Samples').mkdir()
    (root / 'Ext').mkdir()
    return root


def main():
    tmp = Path(tempfile.mkdtemp(prefix='strike-classify-test-'))
    try:
        user_root = make_user_card(tmp)
        preset_root = make_preset_card(tmp)

        # 1. Shape detection itself
        check('preset card shape detected', sr._looks_like_preset_root(preset_root))
        check('user card shape NOT preset', not sr._looks_like_preset_root(user_root))

        # 2. Both cards, either insertion order, meaningless keys (no labels on
        #    real cards — Windows falls back to drive letters).
        u, p = sr._classify_volumes({'F:': preset_root, 'J:': user_root})
        check('order preset-first: user correct', u == user_root)
        check('order preset-first: preset correct', p == preset_root)
        u, p = sr._classify_volumes({'J:': user_root, 'F:': preset_root})
        check('order user-first: user correct', u == user_root)
        check('order user-first: preset correct', p == preset_root)

        # 3. Labels must be ignored entirely — adversarial keys.
        u, p = sr._classify_volumes({'NO NAME': preset_root, 'NO NAME 1': user_root})
        check('adversarial NO NAME keys: user correct', u == user_root)
        check('adversarial NO NAME keys: preset correct', p == preset_root)

        # 4. Single card scenarios.
        u, p = sr._classify_volumes({'J:': user_root})
        check('lone user card -> user', u == user_root and p is None)
        u, p = sr._classify_volumes({'F:': preset_root})
        check('lone preset card -> preset', p == preset_root and u is None)

        # 5. Unwritable, non-preset-shaped volume must be PROTECTED (preset
        #    slot), never offered as a save target.
        orig = sr._volume_writable
        sr._volume_writable = lambda root: False
        try:
            u, p = sr._classify_volumes({'X:': user_root})
            check('unwritable unknown volume -> protected, not user',
                  u is None and p == user_root)
        finally:
            sr._volume_writable = orig

        # 6. Empty dict.
        check('no volumes -> (None, None)', sr._classify_volumes({}) == (None, None))

        # 7. The write probe must clean up after itself.
        writable = sr._volume_writable(user_root)
        leftovers = list(user_root.glob('.strike-remap-write-probe*'))
        check('write probe returns True on writable dir', writable)
        check('write probe leaves no residue', leftovers == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILURES:
        print(f'\n{len(FAILURES)} FAILURE(S): {FAILURES}')
        return 1
    print('\nall volume-classification tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
