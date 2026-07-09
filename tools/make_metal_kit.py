#!/usr/bin/env python3
"""
make_metal_kit.py — generate a baseline heavy/metal kit and save to library/kits/.

Usage:
    python tools/make_metal_kit.py

The kit is saved as "Metal Baseline.skt" in library/kits/ and is immediately
visible in the Strike Pro Remapper browser.
"""
import sys
from pathlib import Path

# Make sure we can import strike_remap from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr


# ── Instrument assignments ─────────────────────────────────────────────────────
# (pad_id, layer, sin_rel)
# sin_rel is relative to the Instruments root — must exist in library/instruments/
ASSIGNMENTS = [
    # Kick — layer A: main body,  layer B: high-attack click for definition
    ('K1H', 'a', 'Kicks/Metal 2.sin'),
    ('K1H', 'b', 'Kicks/Hard Click.sin'),

    # Snare — layer A: full hit,  layer B: Ludwig Black Beauty for extra crack
    ('S1H', 'a', 'Snares/UberMetal Center.sin'),
    ('S1H', 'b', 'Snares/Lud14inBlackRock Center.sin'),
    ('S1R', 'a', 'Snares/UberMetal Rimshot.sin'),

    # Toms — Arena Rock series (punchy, present, very classic metal rack/floor tone)
    ('T1H', 'a', 'Toms/Arena Rock 1.sin'),   # high rack
    ('T2H', 'a', 'Toms/Arena Rock 2.sin'),   # mid rack
    ('T3H', 'a', 'Toms/Arena Rock 3.sin'),   # low rack
    ('T4H', 'a', 'Toms/Arena Rock 4.sin'),   # floor tom

    # Hi-Hat — TightHat: bright, controlled, minimal wash — perfect for fast metal
    ('H1B', 'a', 'HiHats/TightHat Bow.sin'),
    ('H1E', 'a', 'HiHats/TightHat Edge.sin'),
    ('H1F', 'a', 'HiHats/TightHat Pedal.sin'),

    # Crash 1 — Paiste 2002 Power Crash: the classic metal crash sound
    ('C1B', 'a', 'Crashes/Pste20in2002Power Crash.sin'),
    ('C1E', 'a', 'Crashes/Pste20in2002Power Crash.sin'),

    # Crash 2 — Sabian AAX Dark Crash: darker second crash for variety
    ('C2B', 'a', 'Crashes/AAXDarkCrash20in Bow.sin'),
    ('C2E', 'a', 'Crashes/AAXDarkCrash20in Edge.sin'),

    # Crash 3 — Sabian Blackwell China: trash/accent cymbal
    ('C3B', 'a', 'Chinas&Splashes/ChinaSabBlackwell Bow.sin'),
    ('C3E', 'a', 'Chinas&Splashes/ChinaSabBlackwell Edge.sin'),

    # Ride — 21" Heavy: cutting bell, controlled bow, trashy edge
    ('R1D', 'a', 'Rides/21inHeavyStick Bell.sin'),
    ('R1B', 'a', 'Rides/21inHeavyStick Bow.sin'),
    ('R1E', 'a', 'Rides/21inHeavyStick Edge.sin'),
]

# ── Optional parameter tweaks ──────────────────────────────────────────────────
# (pad_id, param, value)
PARAMS = [
    # Kick: layer B (click) slightly lower volume — blends under the body
    ('K1H', 'lb_level', 80),
    # Snare: layer B (LBB) is a subtle mix-in, keep it quiet
    ('S1H', 'lb_level', 60),
    # Snare: velocity xfade — layer B kicks in on harder hits (velocity > 80)
    ('S1H', 'xfade_vel', 80),
]


def main():
    print('Building Metal Baseline kit...')

    # Verify all referenced .sin files actually exist in the library
    lib_inst = sr.LIBRARY_DIR / 'instruments'
    missing = []
    for pad_id, layer, sin_rel in ASSIGNMENTS:
        if not (lib_inst / sin_rel).exists():
            missing.append(sin_rel)

    if missing:
        print('\nWARNING — these instruments are not in the library:')
        for m in missing:
            print(f'  {m}')
        print('\nRun  python tools/copy_samples.py  with the preset SD card mounted,')
        print('then re-run this script.')
        print('\nProceeding anyway — missing instruments will be skipped.')

    # Create a blank kit
    sr.create_new_kit('Metal Baseline')
    print(f'Created blank kit at  {sr.state["kit_path"]}')

    # Seed the available instruments from the library
    sr.refresh_available()

    # Assign instruments (skip any that aren't available)
    for pad_id, layer, sin_rel in ASSIGNMENTS:
        if sin_rel not in sr.state['avail']:
            print(f'  skip  {pad_id} {layer.upper()}  —  {sin_rel} (not in library)')
            continue
        sr.assign_instrument(pad_id, layer, sin_rel)
        print(f'  {pad_id} L{layer.upper()} <- {sin_rel}')

    # Apply parameter tweaks
    for pad_id, param, value in PARAMS:
        try:
            sr.set_pad_param(pad_id, param, value)
        except Exception as e:
            print(f'  param {pad_id}/{param}: {e}')

    # Save
    out = sr.LIBRARY_DIR / 'kits' / 'Metal Baseline.skt'
    sr.save_kit(str(out))
    print(f'\nSaved -> {out}')
    print('Open the remapper and load "Metal Baseline" from the kit list.')


if __name__ == '__main__':
    main()
