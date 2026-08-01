#!/usr/bin/env python3
"""Checks for the start-screen view model and interaction contracts."""

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
    (app.LIBRARY_DIR / 'instruments').mkdir(parents=True)
    app.get_volumes = lambda: (None, None)
    refresh_calls = []
    app.refresh_available = lambda: refresh_calls.append(1)
    avail_sentinel = {'Mounted/Only.sin': Path('/card/Mounted/Only.sin')}
    app.state['avail'] = dict(avail_sentinel)
    app.state['instruments'] = []
    app.state['kit_display'] = ''
    app.state['dirty'] = False

    d = app.start_overview()
    check(d['local_kits'] == 0 and d['local_instruments'] == 0,
          'a fresh install reports nothing on disk')
    check('kits' not in d and 'instruments' not in d,
          'the API uses explicit local-count field names')
    check(d['recent'] == [] and d['autosaves'] == [],
          'a fresh install has no history or recovery')
    check(not d['user_mounted'] and not d['preset_mounted'],
          'both cards report absent when nothing is connected')

    for name in ('Alpha.skt', 'Beta.skt', 'Gamma.skt'):
        (app.LIBRARY_DIR / 'kits' / name).write_bytes(b'\x00')
    for i in range(5):
        p = app.LIBRARY_DIR / 'instruments' / 'Kicks' / f'K{i}.sin'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'\x00')
    d = app.start_overview()
    check(d['local_kits'] == 3 and d['local_instruments'] == 5,
          'local counts come only from the local library')
    check(d['recent'] == [],
          'available kits are not called recent before they are opened')
    check(app.state['avail'] == avail_sentinel and not refresh_calls,
          'rendering does not mutate the global availability index')

    now = time.time()
    alpha = app.LIBRARY_DIR / 'kits' / 'Alpha.skt'
    beta = app.LIBRARY_DIR / 'kits' / 'Beta.skt'
    app.record_recent_kit(alpha, opened_at=now - 7200)
    app.record_recent_kit(beta, opened_at=now)
    d = app.start_overview()
    check([k['name'] for k in d['recent']] == ['Beta', 'Alpha'],
          'successful opens are ordered newest first')
    check(d['recent'][0]['age'].endswith('m') and d['recent'][1]['age'] == '2h',
          'history uses short relative age labels')
    check(all(k['source'] == 'On this computer' for k in d['recent']),
          'history uses friendly source labels')
    app.record_recent_kit(alpha, opened_at=now + 1)
    check([k['name'] for k in app.start_overview()['recent']] == ['Alpha', 'Beta'],
          'reopening moves a kit to the front without duplication')
    check(app._relative_age(time.time() - 30) == '1m',
          'under a minute still reads as 1m')

    (app.LIBRARY_DIR / 'kits' / 'Beta.autosave.skt').write_bytes(b'\x00')
    d = app.start_overview()
    check(len(d['autosaves']) == 1 and d['local_kits'] == 3,
          'autosaves are recovery entries, not local kits')
    check(all('autosave' not in k['name'].lower() for k in d['recent']),
          'autosaves never appear in recent kits')
    check(d['autosaves'][0]['name'] == 'Beta' and d['autosaves'][0].get('age'),
          'recovery includes its name and age')

    app.state['kit_display'] = 'Beta.skt'
    app.state['dirty'] = True
    d = app.start_overview()
    check(d['loaded_kit'] == 'Beta.skt' and d['dirty'] is True,
          'an open kit makes the screen dismissible')

    user = tmp / 'usercard'
    (user / 'Kits').mkdir(parents=True)
    (user / 'Kits' / 'Card Kit.skt').write_bytes(b'\x00')
    (user / 'Instruments' / 'Kicks').mkdir(parents=True)
    (user / 'Instruments' / 'Kicks' / 'Card Kick.sin').write_bytes(b'\x00')
    preset = tmp / 'presetcard'
    (preset / 'Kits' / 'ACOUSTIC').mkdir(parents=True)
    (preset / 'Kits' / 'ACOUSTIC' / 'Factory.skt').write_bytes(b'\x00')
    (preset / 'Instruments' / 'Snares').mkdir(parents=True)
    (preset / 'Instruments' / 'Snares' / 'Factory Snare.sin').write_bytes(b'\x00')
    app.get_volumes = lambda: (user, preset)
    app.record_recent_kit(user / 'Kits' / 'Card Kit.skt', opened_at=now + 2)
    app.record_recent_kit(preset / 'Kits' / 'ACOUSTIC' / 'Factory.skt', opened_at=now + 3)
    d = app.start_overview()
    check(d['user_mounted'] and d['preset_mounted'],
          'both cards are reported when mounted')
    sources = {k['source'] for k in d['recent']}
    check('User card' in sources and 'Factory card' in sources,
          'opened card kits remain in history with their source labels')
    check(d['local_kits'] == 3 and d['local_instruments'] == 5,
          'mounted cards do not inflate local counts')
    check(app.state['avail'] == avail_sentinel and not refresh_calls,
          'card rendering still leaves availability untouched')
    app.get_volumes = lambda: (None, None)
    hidden = app.start_overview()
    check(all(k['source'] == 'On this computer' for k in hidden['recent']),
          'disconnected card history is hidden without being mistaken for local content')
    app.get_volumes = lambda: (user, preset)
    check({'User card', 'Factory card'} <= {k['source'] for k in app.start_overview()['recent']},
          'card history returns when those paths are available again')

    html = app.HTML
    check('id="start-screen" role="dialog" aria-modal="true"' in html,
          'the start screen exposes modal dialog semantics')
    check('setStartBackgroundInert(true)' in html and
          'setStartBackgroundInert(false)' in html and
          "el.setAttribute('inert', '')" in html and "el.removeAttribute('inert')" in html,
          'opening and closing apply and remove inert')
    check('returnFocus.focus()' in html,
          'closing restores focus to the opener')
    check("if (e.key === 'Tab') { trapStartFocus(e); return; }" in html,
          'Tab and Shift+Tab stay within the modal')
    check('if (_startOpen) return true;' in html and 'if (_startLoading) return false;' in html,
          'duplicate opens preserve modal bookkeeping')
    open_source = html[html.index('async function openStartScreen()'):
                       html.index('function closeStartScreen()')]
    check(open_source.index("fetch('/api/start')") < open_source.index("classList.add('open')"),
          'start data renders before the editor is trapped')

    copy_source = html[html.index('function startCopyLibrary()'):
                       html.index('function startImport()')]
    before_confirm = copy_source.split('async function confirmStartCopyLibrary()')[0]
    check('syncLibrary()' not in before_confirm,
          'the S shortcut opens confirmation instead of copying')
    check('await syncLibrary()' in copy_source and 'id="start-sync-go"' in html,
          'only explicit confirmation starts the copy')
    check("e.key === 'Escape' && !document.getElementById('start-sync-confirm').hidden" in html,
          'Escape cancels copy confirmation first')
    check('id="boot-screen" role="status"' in html and
          'if (await openStartScreen()) hideBootScreen();' in html,
          'startup covers the editor until start data is ready')
    check('retryStartBoot()' in html and 'Continue to editor' in html,
          'startup failure offers retry and a usable escape')

    app._recent_kits_path().write_text('{broken', 'utf-8')
    check(app.load_recent_kits() == [], 'corrupt recent history is ignored')
    check(app.start_overview()['recent'] == [],
          'corrupt history cannot sink start data')
    app._recent_kits_path().write_text('[{"path":"x","opened_at":Infinity}]', 'utf-8')
    check(app.load_recent_kits() == [], 'non-finite history timestamps are ignored')

    print('\nall start-screen tests passed')
finally:
    app.LIBRARY_DIR = old['library']
    app.get_volumes = old['get_volumes']
    app.refresh_available = old['refresh']
    app.state.clear()
    app.state.update(old['state'])
    shutil.rmtree(tmp, ignore_errors=True)
