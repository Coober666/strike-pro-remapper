#!/usr/bin/env python3
"""Regression checks for the relink wizard's suggestion engine (issue #40).

Filename matching alone returns nothing when a kit was authored against a
different sound library — the right sound is on the card under an unrelated
name. These checks pin the evidence fallbacks and, just as importantly, that a
guess is always labelled as one.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import strike_remap as app


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"  ok   {label}")


def feats(centroid, rolloff, zcr, brightness, decay):
    return {'centroid': centroid, 'rolloff': rolloff, 'zcr': zcr,
            'brightness': brightness, 'decay': decay}


# Two families that are far apart in feature space: kicks are dark and long,
# crashes bright and ringing. `near` sits beside the surviving kick layer.
FP = {
    'Kicks/Survivor.sin': feats(80, 200, 40, 0.02, 0.40),
    'Kicks/Near.sin':     feats(85, 210, 42, 0.03, 0.42),
    'Kicks/Far.sin':      feats(300, 900, 180, 0.30, 0.10),
    'Crashes/Bright.sin': feats(6000, 11000, 3000, 0.85, 2.10),
    'Crashes/Other.sin':  feats(6200, 11500, 3100, 0.88, 2.30),
}
AVAIL = {rel: Path('X:/Instruments') / rel for rel in FP}


def set_state(instruments, pads, avail=None):
    app.state['instruments'] = list(instruments)
    app.state['pads'] = pads
    app.state['avail'] = dict(avail if avail is not None else AVAIL)


def pad(pid, a=None, b=None):
    return {'id': pid, 'label': pid,
            'layer_a': app.NO_INSTRUMENT if a is None else a,
            'layer_b': app.NO_INSTRUMENT if b is None else b,
            'payload': bytearray(64)}   # _snapshot() deep-copies this for undo


old = {
    'state': dict(app.state),
    'fp_cache': app._fp_cache,
    'fp_factory': app._fp_factory,
    'catalog': app._factory_catalog_data,
    'catalog_keys': app._factory_catalog_keys,
    'search_roots': app._sin_search_roots,
    'refresh': app.refresh_available,
}

try:
    # No catalog, so grouping falls through to the folder names above.
    app._factory_catalog_data = {}
    app._factory_catalog_keys = set()
    app._fp_factory = {}
    app._fp_cache = {rel: {'feats': f} for rel, f in FP.items()}
    # check_paths() reads each resolvable .sin to verify its WAVs; keep it off disk.
    app._sin_search_roots = lambda: []
    app._sin_missing_wavs = lambda sin_abs: []
    # _ensure_avail() rescans when avail is empty — these tests set avail by hand.
    app.refresh_available = lambda: None

    # --- grouping and family helpers --------------------------------------
    check(app._instrument_groups('Kicks/Near.sin') == {0, 7},
          'folder name identifies a kick when the catalog has no entry')
    check(app._instrument_groups('PS Snares MK3/Whatever.sin') == {1, 8},
          'an expansion-pack folder still resolves to its family')
    check(app._instrument_groups('Mystery/Thing.sin') == set(),
          'an unrecognisable folder claims no family rather than guessing')
    app._factory_catalog_data = {'Odd/Name.sin': {'group': 5}}
    check(app._instrument_groups('Odd/Name.sin') == {5},
          'the committed catalog wins over the folder heuristic')
    app._factory_catalog_data = {}
    check(app._pad_family_groups('K1H') == {0, 7} and app._pad_family_groups('R1D') == {5}
          and app._pad_family_groups('H1F') == {3},
          'pad ids map to families, including the ride bell and hi-hat foot')

    # --- tier 1: filename still wins --------------------------------------
    set_state(['Kicks/Near.sin'], [pad('K1H', a=0)])
    app.state['avail'] = dict(AVAIL)
    s = app.relink_suggestions()['suggestions']
    check(not s, 'a kit whose instruments all resolve has nothing to suggest')

    set_state(['Elsewhere/Near.sin', 'Kicks/Survivor.sin'],
              [pad('K1H', a=0, b=1)])
    s = app.relink_suggestions()['suggestions'][0]
    check(s['basis'] == 'name' and s['candidates'][0]['rel'] == 'Kicks/Near.sin',
          'an identical filename in another folder is still matched by name')

    # --- tier 2: ranked by sound against the surviving layer ---------------
    set_state(['Kicks/Gone.sin', 'Kicks/Survivor.sin'], [pad('K1H', a=0, b=1)])
    out = app.relink_suggestions()
    s = out['suggestions'][0]
    check(s['basis'] == 'sound', 'a broken layer is ranked against its surviving partner')
    check(s['candidates'][0]['rel'] == 'Kicks/Near.sin',
          'the nearest-sounding instrument ranks first')
    check('Survivor' in s['why'] and 'K1H' in s['why'],
          'the reason names the layer and pad the ranking came from')
    check(all(c['basis'] == 'sound' for c in s['candidates']),
          'every sound-ranked candidate is labelled as such')
    check(s['candidates'][0]['score'] <= 1.0 and s['candidates'][0]['dist'] >= 0,
          'sound candidates carry both a 0-1 score and the raw distance')
    check(not out['needs_fingerprints'],
          'nothing needs analysing when the surviving layer is already fingerprinted')

    # --- the family filter keeps a crash off a kick pad --------------------
    check(all(c['rel'].startswith('Kicks/') for c in s['candidates']),
          'candidates for a kick pad stay in the kick family')

    # a pad whose family has too few members drops the filter rather than
    # returning nothing useful
    set_state(['Crashes/Gone.sin', 'Crashes/Bright.sin'], [pad('C1B', a=0, b=1)])
    s = app.relink_suggestions()['suggestions'][0]
    check(s['basis'] == 'sound' and len(s['candidates']) >= 1,
          'a small family falls back to the whole corpus instead of coming up empty')

    # --- sibling on the same physical piece, not the same pad --------------
    set_state(['Kicks/Gone.sin', 'Kicks/Survivor.sin'],
              [pad('S1H', a=0), pad('S1R', a=1)])
    s = app.relink_suggestions()['suggestions'][0]
    check(s['basis'] == 'sound',
          'a surviving layer on the same trigger (S1H/S1R) counts as evidence')

    # --- tier 3: family only ----------------------------------------------
    app._fp_cache = {}
    app._fp_factory = {}
    set_state(['Kicks/Gone.sin', 'Kicks/Survivor.sin'], [pad('K1H', a=0, b=1)])
    out = app.relink_suggestions()
    s = out['suggestions'][0]
    check(s['basis'] == 'category', 'with no fingerprints it falls back to the pad family')
    check(s['candidates'] and all(c['rel'].startswith('Kicks/') for c in s['candidates']),
          'family suggestions are drawn from the right family')
    check('Audition' in s['why'], 'the family tier tells the user to listen first')
    check(out['needs_fingerprints'] == ['Kicks/Survivor.sin'],
          'the surviving layer is offered up for analysis')

    # --- no evidence at all -----------------------------------------------
    set_state(['Mystery/Gone.sin'], [pad('K1H', a=0)], avail={})
    s = app.relink_suggestions()['suggestions'][0]
    check(s['candidates'] == [] and s['basis'] == 'none',
          'an unmatched path returns cleanly with no candidates')
    check(s['why'], 'even a hopeless row explains itself')

    # --- an unscanned library must not look like an empty one --------------
    # state['avail'] fills in lazily; without this guard the first repair check
    # after startup calls every instrument in the kit missing.
    scans = []
    app.refresh_available = lambda: scans.append(1)
    set_state(['Kicks/Near.sin'], [pad('K1H', a=0)], avail={})
    app._ensure_avail()
    check(len(scans) == 1, 'an empty library with a kit loaded triggers one rescan')
    app.state['avail'] = dict(AVAIL)
    app._ensure_avail()
    check(len(scans) == 1, 'an already-scanned library is not rescanned')
    app.state['instruments'] = []
    app.state['avail'] = {}
    app._ensure_avail()
    check(len(scans) == 1, 'no rescan when no kit is loaded')
    app.refresh_available = lambda: None

    # --- apply still guards ------------------------------------------------
    set_state(['Kicks/Gone.sin'], [pad('K1H', a=0)])
    refused = False
    try:
        app.relink_apply({'Kicks/Gone.sin': 'Kicks/NotOnCard.sin'})
    except ValueError:
        refused = True
    check(refused, 'relinking to an instrument that is not available is refused')
    refused = False
    try:
        app.relink_apply({'Not/InKit.sin': 'Kicks/Near.sin'})
    except ValueError:
        refused = True
    check(refused, 'relinking a path the kit does not reference is refused')

    app.state['history'] = []
    n = app.relink_apply({'Kicks/Gone.sin': 'Kicks/Near.sin'})
    check(n == 1 and app.state['instruments'][0] == 'Kicks/Near.sin',
          'a valid relink rewrites the instrument table')
    check(len(app.state['history']) == 1,
          'relinking every affected pad costs exactly one undo entry')

    print('\nall relink tests passed')
finally:
    app.state.clear(); app.state.update(old['state'])
    app._fp_cache = old['fp_cache']
    app._fp_factory = old['fp_factory']
    app._factory_catalog_data = old['catalog']
    app._factory_catalog_keys = old['catalog_keys']
    app._sin_search_roots = old['search_roots']
    app.refresh_available = old['refresh']
