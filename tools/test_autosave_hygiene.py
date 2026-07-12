#!/usr/bin/env python3
"""
test_autosave_hygiene.py — unit tests for issue #9 (B4-3 autosave location,
B4-1 recovery dedup, A4-1 display name, B4-4 FX no-op history pollution).

Runs on the synthetic fixtures; library dir and volumes are faked in temp
dirs so nothing real is touched. Exit non-zero on failure.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strike_remap as sr  # noqa: E402

FX = ROOT / 'tests' / 'fixtures'
FAILURES = []


def check(name, cond):
    print(('  ok  ' if cond else '  FAIL') + ' ' + name)
    if not cond:
        FAILURES.append(name)


def main():
    tmp = Path(tempfile.mkdtemp(prefix='strike-autosave-test-'))
    orig_lib = sr.LIBRARY_DIR
    orig_getvol = sr.get_volumes
    try:
        lib = tmp / 'library'
        (lib / 'kits').mkdir(parents=True)
        sr.LIBRARY_DIR = lib
        sr.get_volumes = lambda: (None, None)

        # ── B4-3: autosave of a card-loaded kit lands in library/kits, not
        #    next to the kit (i.e. not on the card).
        card = tmp / 'fakecard'
        card.mkdir()
        shutil.copyfile(FX / 'synthetic_kit.skt', card / 'synthetic_kit.skt')
        sr.load_kit(str(card / 'synthetic_kit.skt'))
        sr.state['dirty'] = True
        dst = sr.autosave_kit()
        check('autosave path is under library/kits', dst is not None and Path(dst).parent == lib / 'kits')
        check('no autosave written next to the card kit',
              not (card / 'synthetic_kit.autosave.skt').exists())

        # ── save_kit cleans up the library-located autosave.
        out = tmp / 'saved' / 'synthetic_kit.skt'
        sr.save_kit(str(out))
        check('save_kit removed the library autosave', not Path(dst).exists())

        # ── A4-1: loading an autosave displays the original kit name.
        sr.state['dirty'] = True
        sr.state['kit_path'] = str(card / 'synthetic_kit.skt')
        dst = sr.autosave_kit()
        sr.load_kit(dst)
        check('autosave loads under original display name',
              sr.state['kit_display'] == 'synthetic_kit.skt')

        # ── B4-1: duplicate autosaves for the same kit dedup to the newest.
        user_vol = tmp / 'uservol'
        (user_vol / 'Kits').mkdir(parents=True)
        old = user_vol / 'dupkit.autosave.skt'
        new = user_vol / 'Kits' / 'dupkit.autosave.skt'
        shutil.copyfile(FX / 'synthetic_kit.skt', old)
        shutil.copyfile(FX / 'synthetic_kit.skt', new)
        past = time.time() - 3600
        import os
        os.utime(old, (past, past))
        sr.get_volumes = lambda: (user_vol, None)
        entries = [a for a in sr.find_autosaves() if a['name'] == 'dupkit']
        check('duplicate autosaves dedup to one entry', len(entries) == 1)
        check('newest duplicate wins', entries and entries[0]['autosave_path'] == str(new))

        # ── B4-4: setting a kit FX param to its current value is a no-op.
        sr.load_kit(str(FX / 'synthetic_kit.skt'))
        sr.set_kit_fx('reverb_type', 3)
        depth_before = len(sr.state['history'])
        sr.set_kit_fx('reverb_type', 3)
        check('no-op FX set adds no undo entry', len(sr.state['history']) == depth_before)
        sr.set_kit_fx('reverb_type', 2)
        check('real FX change still adds an undo entry',
              len(sr.state['history']) == depth_before + 1)
    finally:
        sr.LIBRARY_DIR = orig_lib
        sr.get_volumes = orig_getvol
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILURES:
        print(f'\n{len(FAILURES)} FAILURE(S): {FAILURES}')
        return 1
    print('\nall autosave-hygiene tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
