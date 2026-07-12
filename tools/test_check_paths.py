#!/usr/bin/env python3
"""
test_check_paths.py — unit tests for WAV-level broken-path detection (issue #4)
and assign_instrument validation (A0-3 rider).

check_paths() used to verify only that each pad's .sin existed in avail; a
moved/renamed sample folder (the common breakage) went undetected and the
relink wizard saw nothing. Runs on the synthetic fixtures; no library or
hardware needed. Exit non-zero on failure.
"""
import shutil
import sys
import tempfile
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
    sr.load_kit(str(FX / 'synthetic_kit.skt'))
    fixture_avail = {
        'Fixtures/single_zone.sin':    FX / 'single_zone.sin',
        'Fixtures/multi_velocity.sin': FX / 'multi_velocity.sin',
    }
    sr.state['avail'] = dict(fixture_avail)

    tmp = Path(tempfile.mkdtemp(prefix='strike-checkpaths-test-'))
    orig_roots = sr._sin_search_roots
    try:
        wav_rels = ['Fixtures/kick.wav', 'Fixtures/snare_soft.wav',
                    'Fixtures/snare_med.wav', 'Fixtures/snare_hard.wav']
        (tmp / 'Fixtures').mkdir()
        for rel in wav_rels:
            shutil.copyfile(FX / 'bright_a.wav', tmp / rel)
        sr._sin_search_roots = lambda: [tmp]

        # 1. Everything resolvable → clean.
        cp = sr.check_paths()
        check('all present -> broken empty', cp['broken'] == [])
        check('all present -> detail empty', cp['detail'] == {})

        # 2. Missing WAV (simulates a renamed sample folder) → the referencing
        #    .sin is reported, with a reason naming the sample.
        (tmp / 'Fixtures' / 'snare_med.wav').unlink()
        cp = sr.check_paths()
        check('missing WAV -> referencing sin reported',
              cp['broken'] == ['Fixtures/multi_velocity.sin'])
        check('missing WAV -> detail names the sample',
              'snare_med.wav' in cp['detail'].get('Fixtures/multi_velocity.sin', ''))
        shutil.copyfile(FX / 'bright_a.wav', tmp / 'Fixtures' / 'snare_med.wav')

        # 3. Missing .sin (removed from avail) → reported with its own reason.
        del sr.state['avail']['Fixtures/single_zone.sin']
        cp = sr.check_paths()
        check('missing sin -> reported', 'Fixtures/single_zone.sin' in cp['broken'])
        check('missing sin -> reason says instrument file',
              cp['detail'].get('Fixtures/single_zone.sin') == 'instrument file not found')
        sr.state['avail'] = dict(fixture_avail)

        # 4. assign_instrument accepts a rel that IS in avail.
        sr.assign_instrument('T1H', 'a', 'Fixtures/single_zone.sin')
        check('assign of existing instrument succeeds', True)

        # 5. assign_instrument rejects a nonexistent rel (used to silently
        #    accept it). Runs last: the failed lookup triggers a real
        #    refresh_available() that clobbers the fixture avail.
        try:
            sr.assign_instrument('T1H', 'a', 'Nope/does_not_exist.sin')
            check('assign of nonexistent instrument raises', False)
        except ValueError:
            check('assign of nonexistent instrument raises', True)
    finally:
        sr._sin_search_roots = orig_roots
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILURES:
        print(f'\n{len(FAILURES)} FAILURE(S): {FAILURES}')
        return 1
    print('\nall check-paths tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
