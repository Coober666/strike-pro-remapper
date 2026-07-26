#!/usr/bin/env python3
"""Regression checks for Deploy to Module preflight and safe transfer."""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import strike_remap as app


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"  ok   {label}")


old = {
    'library': app.LIBRARY_DIR,
    'get_volumes': app.get_volumes,
    'parse_wavs': app.parse_sin_all_wavs,
    'resolve_wav': app._resolve_wav,
    'snapshot': app._auto_snapshot,
    'state': dict(app.state),
}

try:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        app.LIBRARY_DIR = root / 'library'
        user = root / 'user-card'
        preset = root / 'preset-card'
        (user / 'Instruments').mkdir(parents=True)
        (preset / 'Instruments').mkdir(parents=True)
        app._auto_snapshot = lambda *args, **kwargs: None
        app.create_new_kit('Deploy Test')

        app.get_volumes = lambda: (None, None)
        p = app.deploy_preflight()
        check(not p['ready'], 'preflight blocks without a user card')
        check(any(i['code'] == 'no_user_card' for i in p['issues']),
              'missing-card issue is explicit')

        app.get_volumes = lambda: (user, preset)
        p = app.deploy_preflight()
        check(p['ready'], 'empty kit is ready with a writable user card')
        check(Path(p['target_path']) == user / 'Kits' / 'Deploy Test.skt',
              'target is the user-card Kits folder')

        result = app.deploy_kit()
        card_kit = user / 'Kits' / 'Deploy Test.skt'
        local_kit = app.LIBRARY_DIR / 'kits' / 'Deploy Test.skt'
        check(result['verified'] and card_kit.exists(), 'kit is written and verified on card')
        check(local_kit.read_bytes() == card_kit.read_bytes(),
              'local working copy and module copy match')
        check(app.state['kit_path'] == str(local_kit),
              'deployment keeps the local library as the working copy')

        card_kit.write_bytes(b'older module copy')
        result = app.deploy_kit()
        backup = Path(result['backup_path'])
        check(backup.exists() and backup.read_bytes() == b'older module copy',
              'replaced module kit is backed up locally')

        sin = app.LIBRARY_DIR / 'instruments' / 'Custom' / 'Split Hat.sin'
        wav = app.LIBRARY_DIR / 'samples' / 'Custom' / 'split-hat.wav'
        sin.parent.mkdir(parents=True); wav.parent.mkdir(parents=True)
        sin.write_bytes(b'local custom instrument')
        wav.write_bytes(b'local custom sample')
        app.state['instruments'] = ['Custom/Split Hat.sin']
        app.state['pads'][0]['layer_a'] = 0
        app.state['avail'] = {'Custom/Split Hat.sin': sin}
        app.parse_sin_all_wavs = lambda data: ['Custom/split-hat.wav']
        app._resolve_wav = lambda rel, roots: wav if rel == 'Custom/split-hat.wav' else None

        p = app.deploy_preflight()
        check(p['ready'] and p['asset_counts']['copy'] == 2,
              'preflight plans local instrument and sample transfer')
        result = app.deploy_kit()
        check((user / 'Instruments' / 'Custom' / 'Split Hat.sin').read_bytes() == sin.read_bytes(),
              'custom instrument copied to user card')
        check((user / 'Samples' / 'Custom' / 'split-hat.wav').read_bytes() == wav.read_bytes(),
              'custom sample copied to user card')

        (user / 'Instruments' / 'Custom' / 'Split Hat.sin').write_bytes(b'conflicting version')
        p = app.deploy_preflight()
        check(not p['ready'] and any(i['code'] == 'asset_conflict' for i in p['issues']),
              'different existing asset blocks deployment instead of overwriting')

        preset_sin = preset / 'Instruments' / 'Factory' / 'Hat.sin'
        preset_wav = preset / 'Samples' / 'Factory' / 'hat.wav'
        preset_sin.parent.mkdir(parents=True); preset_wav.parent.mkdir(parents=True)
        preset_sin.write_bytes(b'factory instrument'); preset_wav.write_bytes(b'factory sample')
        app.state['instruments'] = ['Factory/Hat.sin']
        app.state['pads'][0]['layer_a'] = 0
        app.state['avail'] = {'Factory/Hat.sin': preset_sin}
        app.parse_sin_all_wavs = lambda data: ['Factory/hat.wav']
        app._resolve_wav = lambda rel, roots: preset_wav
        p = app.deploy_preflight()
        check(p['ready'] and p['asset_counts']['copy'] == 0
              and p['asset_counts']['available'] == 2,
              'factory-card assets are reused without duplication')

    print('\nall deploy workflow tests passed')
finally:
    app.LIBRARY_DIR = old['library']
    app.get_volumes = old['get_volumes']
    app.parse_sin_all_wavs = old['parse_wavs']
    app._resolve_wav = old['resolve_wav']
    app._auto_snapshot = old['snapshot']
    app.state.clear(); app.state.update(old['state'])
