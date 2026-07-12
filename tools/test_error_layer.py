#!/usr/bin/env python3
"""
test_error_layer.py — unit tests for _friendly_error + the no-kit save guard
(issue #8).

Raw exception strings (OS errno text, NoneType reprs, internal identifiers)
used to flow straight into the UI, and saving with no kit loaded crashed with
'cannot convert NoneType object to bytearray'. No library or hardware needed.
Exit non-zero on failure.
"""
import sys
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


def friendly(exc):
    try:
        raise exc
    except type(exc) as e:
        return sr._friendly_error(e)


def main():
    # 1. Save with no kit loaded → friendly ValueError, not a NoneType crash.
    sr.state['kit_raw'] = None
    sr.state['pads'] = []
    sr.state['instruments'] = []
    try:
        sr.save_kit(str(FX / 'should-not-exist.skt'))
        check('save with no kit raises', False)
    except ValueError as e:
        check('save with no kit raises', True)
        check('no-kit message is friendly', 'No kit loaded' in str(e))
    except Exception as e:
        check(f'save with no kit raises ValueError (got {type(e).__name__})', False)
    check('no-kit save wrote nothing', not (FX / 'should-not-exist.skt').exists())

    # 2. autosave with no kit is a silent no-op.
    sr.state['kit_path'] = str(FX / 'synthetic_kit.skt')
    sr.state['dirty'] = True
    check('autosave with kit_raw=None returns None', sr.autosave_kit() is None)
    sr.state['dirty'] = False

    # 3. ValueError text passes through verbatim (user-facing by convention).
    msg = friendly(ValueError('Instrument not found: Foo/bar.sin'))
    check('ValueError passes through', msg == 'Instrument not found: Foo/bar.sin')

    # 4. Internal errors do not leak reprs.
    msg = friendly(TypeError("cannot convert 'NoneType' object to bytearray"))
    check('TypeError hidden behind generic message', 'NoneType' not in msg)
    check('generic message points at console', 'server console' in msg)

    # 5. OSError shows at most the basename, not the errno text or full path.
    err = OSError(13, 'Permission denied')
    err.filename = r'C:\Users\someone\secret\place\kit.skt'
    msg = friendly(err)
    check('OSError hides errno text', 'Permission denied' not in msg)
    check('OSError hides full path', 'secret' not in msg)
    check('OSError keeps the basename', 'kit.skt' in msg)

    if FAILURES:
        print(f'\n{len(FAILURES)} FAILURE(S): {FAILURES}')
        return 1
    print('\nall error-layer tests passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
