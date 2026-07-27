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
    'manifest_path': app.PRESET_MANIFEST_PATH,
    'manifest_cache': app._preset_manifest_cache,
    'catalog_keys': app._factory_catalog_keys,
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

        # --- issue #33: unresolvable is not the same as absent -----------------
        # With the official editor closed the module hides the factory card, so
        # references to it cannot be resolved here. That must warn, never block.
        app.PRESET_MANIFEST_PATH = app.LIBRARY_DIR / 'preset_manifest.json'
        app._preset_manifest_cache = {}
        app._factory_catalog_keys = set()
        missing_rel = 'PS Snares MK3/PS Taye MapleSnHd Amb.sin'
        app.state['instruments'] = [missing_rel]
        app.state['pads'][0]['layer_a'] = 0
        app.state['avail'] = {}

        p = app.deploy_preflight()
        check(p['ready'], 'an unresolvable reference does not block deployment')
        check(not any(i['severity'] == 'blocker' for i in p['issues']),
              'no blocker is raised for a reference we simply cannot see')
        check(p['asset_counts']['unverified'] == 1, 'the reference is counted as unverified')
        warnings = [i for i in p['issues'] if i['code'] == 'unverified_assets']
        check(len(warnings) == 1 and warnings[0]['severity'] == 'warning',
              'unverified references roll up into one warning, not one row each')
        check('could not be verified' in warnings[0]['title'],
              'with no manifest the warning admits it cannot tell missing from unseen')
        check(app.deploy_kit()['verified'],
              'deploy still completes and verifies with an unverified reference')

        # A manifest that does NOT list the path is informative too: the sound is
        # on neither card, so say that instead of blaming the editor.
        app._preset_manifest_cache = {'instruments': ['Something/Else.sin'], 'samples': []}
        p = app.deploy_preflight()
        gone = [i for i in p['issues'] if i['code'] == 'unverified_assets']
        check(p['ready'] and len(gone) == 1 and 'missing from both cards' in gone[0]['title'],
              'once captured, an unresolved reference is reported as genuinely missing')
        check(gone[0]['severity'] == 'warning',
              'a genuinely missing sound still warns rather than blocking')

        app._preset_manifest_cache = {'instruments': [missing_rel], 'samples': []}
        p = app.deploy_preflight()
        check(p['asset_counts']['unverified'] == 0 and p['asset_counts']['available'] == 1,
              'a captured manifest resolves the reference as available')
        check(not any(i['code'] == 'unverified_assets' for i in p['issues']),
              'the warning clears once the factory card has been captured')
        check(p['preset_manifest'], 'preflight reports that a manifest is present')

        app._preset_manifest_cache = {}
        app._factory_catalog_keys = {missing_rel}
        check(app.deploy_preflight()['asset_counts']['unverified'] == 0,
              'the committed factory catalog covers stock content with no capture')

        # --- capturing the factory card ---------------------------------------
        app._preset_manifest_cache = None
        app._factory_catalog_keys = set()
        captured = app.capture_preset_manifest()
        check(captured['instruments'] == 1 and captured['samples'] == 1,
              'capture records what the mounted factory card holds')
        check(app.PRESET_MANIFEST_PATH.exists(), 'capture writes the library sidecar')
        check(app._preset_manifest_has('instrument', 'Factory/Hat.sin'),
              'a captured instrument is recognised afterwards')

        app.get_volumes = lambda: (user, None)
        refused = False
        try:
            app.capture_preset_manifest()
        except ValueError:
            refused = True
        check(refused, 'capture refuses when no factory card is mounted')
        app.get_volumes = lambda: (user, preset)

    print('\nall deploy workflow tests passed')
finally:
    app.LIBRARY_DIR = old['library']
    app.get_volumes = old['get_volumes']
    app.parse_sin_all_wavs = old['parse_wavs']
    app._resolve_wav = old['resolve_wav']
    app._auto_snapshot = old['snapshot']
    app.PRESET_MANIFEST_PATH = old['manifest_path']
    app._preset_manifest_cache = old['manifest_cache']
    app._factory_catalog_keys = old['catalog_keys']
    app.state.clear(); app.state.update(old['state'])
