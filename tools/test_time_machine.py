#!/usr/bin/env python3
"""
test_time_machine.py — exercise the persistent snapshot (kit time machine) engine
end-to-end without a browser or the git-ignored library.

Redirects the snapshot store to a throwaway temp dir, then loads a synthetic kit,
snapshots it, edits it, snapshots again, diffs the two, restores the first, and
checks dedupe + retention. Round-trip losslessness is implied by restore matching
the original bytes byte-for-byte.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr

FIX = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'synthetic_kit.skt'


def main():
    if not FIX.is_file():
        print('Run tools/make_fixtures.py first (missing synthetic_kit.skt)')
        sys.exit(1)

    fails = []

    def check(cond, msg):
        print(('  PASS  ' if cond else '  FAIL  ') + msg)
        if not cond:
            fails.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        # Redirect the snapshot store into a throwaway dir.
        sr.SNAP_DIR        = Path(tmp) / 'snapshots'
        sr.SNAP_INDEX_PATH = sr.SNAP_DIR / 'index.json'
        sr.SNAP_MAX_PER_KIT = 5   # small cap so retention is easy to test

        original = FIX.read_bytes()
        sr.load_kit_bytes(original, 'synthetic_kit.skt')

        # load_kit_bytes fires a 'load' snapshot automatically.
        snaps = sr.list_snapshots()
        check(len(snaps) == 1, f'auto-snapshot on load created 1 snapshot (got {len(snaps)})')
        base_id = snaps[0]['id']
        check(snaps[0]['kind'] == 'load', 'load snapshot tagged kind=load')

        # Dedupe: an unchanged manual snapshot must not create a new entry.
        r = sr.create_snapshot('unchanged', 'manual')
        check(r.get('deduped') is True, 'identical state deduped (no new snapshot)')
        check(len(sr.list_snapshots()) == 1, 'dedupe kept snapshot count at 1')

        # Edit a pad, then snapshot -> a distinct entry.
        sr.set_pad_param('K1H', 'la_level', 42)
        r2 = sr.create_snapshot('after edit', 'manual')
        check(not r2.get('deduped'), 'edited state produced a new snapshot')
        snaps = sr.list_snapshots()
        check(len(snaps) == 2, f'two snapshots after edit (got {len(snaps)})')
        edit_id = snaps[0]['id']  # newest first

        # Diff the two snapshots -> la_level change on K1H.
        d = sr.diff_snapshots(edit_id, base_id)
        k1h = next((x for x in d['diff'] if x['id'] == 'K1H'), None)
        check(k1h is not None and 'la_level' in k1h.get('changed', {}),
              'snapshot-vs-snapshot diff reports the K1H la_level change')
        check(k1h['changed']['la_level']['current'] == 42
              and k1h['changed']['la_level']['other'] == 95,
              'diff shows correct before/after values (42 vs 95)')

        # Diff a snapshot against the live current state.
        dc = sr.diff_snapshots('current', base_id)
        check(any(x['id'] == 'K1H' for x in dc['diff']),
              'diff of current-vs-snapshot also flags K1H')

        # Restore the baseline as an undoable mutation; bytes must match the original.
        undo_before = len(sr.state['history'])
        sr.restore_snapshot(base_id)
        check(len(sr.state['history']) == undo_before + 1,
              'restore pushed one undo entry (undoable, not a clobber)')
        restored = sr.build_skt(sr.state['kit_raw'], sr.state['pads'],
                                sr.state['instruments'], sr.state['tail'])
        check(restored == original, 'restored kit is byte-identical to the original')

        # Undo the restore -> back to the edited state.
        sr.undo()
        check(sr.state['pads'][0] is not None, 'undo after restore did not crash')

        # Pin + retention: pinned snapshots survive the per-kit cap.
        sr.set_snapshot_pin(base_id, True)
        for i in range(10):
            sr.set_pad_param('K1H', 'la_level', 50 + i)
            sr.create_snapshot(f'edit {i}', 'auto')
        snaps = sr.list_snapshots()
        nonpinned = [s for s in snaps if not s.get('pinned')]
        check(len(nonpinned) <= sr.SNAP_MAX_PER_KIT,
              f'retention capped non-pinned at {sr.SNAP_MAX_PER_KIT} (got {len(nonpinned)})')
        check(any(s['id'] == base_id and s['pinned'] for s in snaps),
              'pinned baseline survived retention pruning')

        # Delete removes both the index entry and the .skt file.
        sr.delete_snapshot(edit_id)
        check(not any(s['id'] == edit_id for s in sr.list_snapshots()),
              'delete removed the snapshot from the index')
        check(not (sr.SNAP_DIR / f'{edit_id}.skt').exists(),
              'delete removed the snapshot .skt file')

    print(f'\n{"ALL PASS" if not fails else str(len(fails)) + " FAILED"}')
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
