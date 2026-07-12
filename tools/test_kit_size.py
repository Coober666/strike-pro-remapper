#!/usr/bin/env python3
"""
test_kit_size.py — unit tests for get_kit_size() (issue #6).

The kit-size meter always read 0.0 MB / 0-of-0 because get_kit_size looked up
the pads' integer instrument-table indices directly in the string-keyed avail
dict (and its truthiness guard skipped index 0). Runs on the synthetic
fixtures from tools/make_fixtures.py; no library or hardware needed.
Exit non-zero on failure.
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
    sr.state['avail'] = {
        'Fixtures/single_zone.sin':    FX / 'single_zone.sin',
        'Fixtures/multi_velocity.sin': FX / 'multi_velocity.sin',
    }

    # The fixture kit must exercise the index-0 path (the old guard skipped it).
    idx0_used = any(p.get(k) == 0 for p in sr.state['pads'] for k in ('layer_a', 'layer_b'))
    check('fixture kit uses instrument-table index 0', idx0_used)

    # Stage the WAVs the fixture .sin files reference in a temp search root.
    tmp = Path(tempfile.mkdtemp(prefix='strike-kitsize-test-'))
    orig_roots = sr._sin_search_roots
    try:
        wav_rels = ['Fixtures/kick.wav', 'Fixtures/snare_soft.wav',
                    'Fixtures/snare_med.wav', 'Fixtures/snare_hard.wav']
        (tmp / 'Fixtures').mkdir()
        src = FX / 'bright_a.wav'
        for rel in wav_rels:
            shutil.copyfile(src, tmp / rel)
        sr._sin_search_roots = lambda: [tmp]

        ks = sr.get_kit_size()
        check('total_wavs counts all referenced WAVs (4)', ks['total_wavs'] == 4)
        check('found_wavs == total_wavs with all present', ks['found_wavs'] == 4)
        check('total_bytes > 0', ks['total_bytes'] > 0)

        # One missing WAV → still counted in total, dropped from found.
        (tmp / 'Fixtures' / 'snare_med.wav').unlink()
        ks = sr.get_kit_size()
        check('missing WAV still in total_wavs', ks['total_wavs'] == 4)
        check('missing WAV dropped from found_wavs', ks['found_wavs'] == 3)
    finally:
        sr._sin_search_roots = orig_roots
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILURES:
        print(f'\n{len(FAILURES)} FAILURE(S): {FAILURES}')
        return 1
    print('\nall kit-size tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
