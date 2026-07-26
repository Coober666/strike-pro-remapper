#!/usr/bin/env python3
"""Regression checks for removable-media stalls (issue #35).

The module keeps its SD card mounted internally while also exporting it over
USB, so sustained host access can briefly lose the volume even though the card
is still connected. Reads come back as EINVAL / WinError 55 and succeed again
moments later. None of that should reach the user as a hard failure.
"""

import errno
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import strike_remap as app


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"  ok   {label}")


class StalledDevice(OSError):
    """Stand-in for WinError 55, constructible on POSIX CI too."""
    winerror = 55


class FlakyFile:
    """A card file that stalls the first `fails` reads, then succeeds."""

    def __init__(self, fails, exc):
        self.fails, self.exc, self.calls = fails, exc, 0

    def read_bytes(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        return b'kit payload'


class StalledPath:
    def resolve(self):
        raise OSError(errno.EIO, 'device stalled')


old = {
    'classify': app._classify_volumes,
    'find': app._find_strike_volumes,
    'last_seen': app._last_seen_user_volume,
    'delays': app._CARD_RETRY_DELAYS,
}

try:
    # The shipped delays are sized for a multi-second outage; assert that intent
    # here, then shrink them so the suite does not sleep through it.
    check(sum(app._CARD_RETRY_DELAYS) >= 3.0,
          'the retry window outlasts an observed card outage')
    check(app._CARD_RETRY_DELAYS[0] >= 0.25,
          'the first retry waits rather than landing inside the same outage')
    app._CARD_RETRY_DELAYS = (0.01, 0.01, 0.01)

    # --- which errors count as a stall ------------------------------------
    check(app._is_transient_volume_error(OSError(errno.EINVAL, 'Invalid argument')),
          'EINVAL is treated as a stall')
    check(app._is_transient_volume_error(OSError(errno.EIO, 'I/O error')),
          'EIO is treated as a stall')
    check(app._is_transient_volume_error(StalledDevice(errno.ENODEV, 'gone')),
          'WinError 55 is treated as a stall')
    check(not app._is_transient_volume_error(OSError(errno.ENOENT, 'No such file')),
          'a genuinely missing file is not a stall')
    check(not app._is_transient_volume_error(OSError(errno.EACCES, 'Permission denied')),
          'a permission error is not a stall')

    # --- reads ride out a stall -------------------------------------------
    flaky = FlakyFile(2, OSError(errno.EINVAL, 'Invalid argument'))
    check(app.read_card_bytes(flaky) == b'kit payload' and flaky.calls == 3,
          'a read that stalls twice still succeeds')

    hopeless = FlakyFile(99, OSError(errno.EINVAL, 'Invalid argument'))
    raised = False
    try:
        app.read_card_bytes(hopeless, tries=3)
    except OSError:
        raised = True
    check(raised and hopeless.calls == 3,
          'a read that never recovers raises after the retry budget')

    missing = FlakyFile(99, OSError(errno.ENOENT, 'No such file'))
    raised = False
    try:
        app.read_card_bytes(missing)
    except OSError:
        raised = True
    check(raised and missing.calls == 1,
          'a genuinely missing file fails immediately without retrying')

    # --- a stall must not look like an ejected card -----------------------
    app._find_strike_volumes = lambda: {}
    card = Path('L:/')

    app._last_seen_user_volume = card
    sequence = [(None, None), (card, None)]
    app._classify_volumes = lambda vols: sequence.pop(0) if sequence else (card, None)
    user, _ = app.get_volumes()
    check(user == card,
          'a card that blips mid-probe is re-scanned, not reported missing')

    app._last_seen_user_volume = card
    app._classify_volumes = lambda vols: (None, None)
    user, _ = app.get_volumes()
    check(user is None, 'a genuinely absent card is still reported missing')
    check(app._last_seen_user_volume is None,
          'the re-scan is not repeated once the card is really gone')

    # --- resolving a path on a stalled volume must not explode ------------
    check(app._is_under(StalledPath(), card) is False,
          'a stall while resolving a path degrades instead of raising')

    # --- what the user is told --------------------------------------------
    stall_msg = app._friendly_error(
        OSError(errno.EINVAL, 'Invalid argument', 'L:\\Kits\\THE POCKET REC.skt'))
    check('stopped responding' in stall_msg and 'THE POCKET REC.skt' in stall_msg,
          'an outage is reported as an outage, naming the file')
    check('still connected' in stall_msg,
          'the message does not imply the card came unplugged')
    check('try again' in stall_msg and 'server console' not in stall_msg,
          'the message is actionable instead of pointing at the console')
    check('Strike Editor' in stall_msg,
          'the message mentions the editor workaround')

    other_msg = app._friendly_error(OSError(errno.ENOENT, 'No such file', 'C:\\gone.skt'))
    check('server console' in other_msg,
          'unrelated OS errors keep the existing generic message')

    print('\nall card-resilience tests passed')
finally:
    app._classify_volumes = old['classify']
    app._find_strike_volumes = old['find']
    app._last_seen_user_volume = old['last_seen']
    app._CARD_RETRY_DELAYS = old['delays']
