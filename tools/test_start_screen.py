#!/usr/bin/env python3
"""Checks for the start-screen view model (issue #25).

start_overview() must be a read-only composition of what already exists — card
detection and library scanning live in one place and this must not become a
second copy of them. These checks pin the shape the screen renders from and the
states it has to distinguish.
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strike_remap as app  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"  ok   {label}")


old = {
    'library': app.LIBRARY_DIR,
    'get_volumes': app.get_volumes,
    'refresh': app.refresh_available,
    'state': dict(app.state),
}

try:
    tmp = Path(tempfile.mkdtemp(prefix='strike-start-test-'))
    app.LIBRARY_DIR = tmp / 'library'
    (app.LIBRARY_DIR / 'kits').mkdir(parents=True)
    app.get_volumes = lambda: (None, None)
    app.refresh_available = lambda: None
    app.state['avail'] = {}
    app.state['instruments'] = []
    app.state['kit_display'] = ''
    app.state['dirty'] = False

    # --- fresh install: nothing anywhere ----------------------------------
    d = app.start_overview()
    check(d['kits'] == 0 and d['instruments'] == 0, 'a fresh install reports nothing on disk')
    check(d['recent'] == [] and d['autosaves'] == [], 'no recents and no recovery on a fresh install')
    check(d['user_mounted'] is False and d['preset_mounted'] is False,
          'both cards report absent when nothing is connected')
    check(d['loaded_kit'] == '', 'no kit is reported open')

    # --- local library, still no card -------------------------------------
    for name in ('Alpha.skt', 'Beta.skt', 'Gamma.skt'):
        (app.LIBRARY_DIR / 'kits' / name).write_bytes(b'\x00')
    app.state['avail'] = {f'Kicks/K{i}.sin': Path(f'/x/K{i}.sin') for i in range(5)}
    d = app.start_overview()
    check(d['kits'] == 3 and d['instruments'] == 5, 'local kits and instruments are counted')
    check(len(d['recent']) == 3, 'local kits appear as recents')
    check(all(k['source'] == 'On this computer' for k in d['recent']),
          'sources are friendly names, not raw paths')
    check(all(not k['name'].endswith('.skt') for k in d['recent']),
          'recent names drop the .skt extension')
    check(d['user_mounted'] is False,
          'a local library does not imply a card — local editing stands alone')

    # --- recents are newest-first -----------------------------------------
    now = time.time()
    import os
    os.utime(app.LIBRARY_DIR / 'kits' / 'Beta.skt', (now, now))
    os.utime(app.LIBRARY_DIR / 'kits' / 'Alpha.skt', (now - 7200, now - 7200))
    os.utime(app.LIBRARY_DIR / 'kits' / 'Gamma.skt', (now - 700000, now - 700000))
    d = app.start_overview()
    check([k['name'] for k in d['recent']] == ['Beta', 'Alpha', 'Gamma'],
          'recents are ordered newest first')
    check(d['recent'][0]['age'].endswith('m') and d['recent'][1]['age'] == '2h',
          'ages render as short relative labels')

    check(app._relative_age(time.time() - 30) == '1m', 'under a minute still reads as 1m')
    check(app._relative_age(time.time() - 5 * 86400) not in ('', None),
          'a five-day-old file gets a weekday label')

    # --- recovery present --------------------------------------------------
    (app.LIBRARY_DIR / 'kits' / 'Beta.autosave.skt').write_bytes(b'\x00')
    d = app.start_overview()
    check(len(d['autosaves']) == 1, 'a recoverable autosave is surfaced')
    check(all('autosave' not in k['name'].lower() for k in d['recent']),
          'autosaves stay out of recent kits — opening a crash copy by mistake is the risk')
    check(d['kits'] == 3, 'autosaves are not counted as kits')
    check(d['autosaves'][0]['name'] == 'Beta', 'the recoverable kit is named')
    check(d['autosaves'][0].get('age'), 'the recovery entry carries an age for the banner')
    check(d['autosaves'][0]['autosave_path'].endswith('Beta.autosave.skt'),
          'the recovery entry keeps the path the existing recover flow needs')

    # --- a kit is open: the screen becomes dismissible ---------------------
    app.state['kit_display'] = 'Beta.skt'
    app.state['dirty'] = True
    d = app.start_overview()
    check(d['loaded_kit'] == 'Beta.skt' and d['dirty'] is True,
          'an open kit is reported so the screen can offer a way back')

    # --- cards present -----------------------------------------------------
    user = tmp / 'usercard'
    (user / 'Kits').mkdir(parents=True)
    (user / 'Kits' / 'Card Kit.skt').write_bytes(b'\x00')
    preset = tmp / 'presetcard'
    (preset / 'Kits' / 'ACOUSTIC').mkdir(parents=True)
    (preset / 'Kits' / 'ACOUSTIC' / 'Factory.skt').write_bytes(b'\x00')
    app.get_volumes = lambda: (user, preset)
    d = app.start_overview()
    check(d['user_mounted'] and d['preset_mounted'], 'both cards are reported when mounted')
    sources = {k['source'] for k in d['recent']}
    check('User card' in sources and 'Factory card' in sources,
          'card kits are labelled by which card they came from')

    # --- an unreadable kit must not sink the whole screen ------------------
    ghost = app.LIBRARY_DIR / 'kits' / 'Ghost.skt'
    ghost.write_bytes(b'\x00')
    real_stat = Path.stat

    def flaky_stat(self, *a, **kw):
        if self.name == 'Ghost.skt':
            raise OSError('card stalled')
        return real_stat(self, *a, **kw)

    Path.stat = flaky_stat
    try:
        d = app.start_overview()
        check(all(k['name'] != 'Ghost' for k in d['recent']),
              'a kit that cannot be stat-ed is skipped, not fatal')
        check(len(d['recent']) > 0, 'the rest of the list still renders')
    finally:
        Path.stat = real_stat

    print('\nall start-screen tests passed')
finally:
    app.LIBRARY_DIR = old['library']
    app.get_volumes = old['get_volumes']
    app.refresh_available = old['refresh']
    app.state.clear(); app.state.update(old['state'])
    shutil.rmtree(tmp, ignore_errors=True)
