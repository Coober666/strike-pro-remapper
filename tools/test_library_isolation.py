#!/usr/bin/env python3
"""Regression contracts for redirecting every writable library path."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import strike_remap as app


def main():
    failures = []

    def check(condition, message):
        print(('  ok   ' if condition else '  FAIL ') + message)
        if not condition:
            failures.append(message)

    original_root = app.LIBRARY_DIR
    try:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            first = (temp / 'first-library').resolve()
            second = (temp / 'second-library').resolve()

            app.set_library_root(first)
            app.save_tags({'sentinel.sin': ['first']})
            app._save_snap_index([{'id': 'first'}])
            first_tags = app._TAGS_PATH
            first_index = app.SNAP_INDEX_PATH
            first_tags_bytes = first_tags.read_bytes()
            first_index_bytes = first_index.read_bytes()
            first_tags_mtime = first_tags.stat().st_mtime_ns
            first_index_mtime = first_index.stat().st_mtime_ns

            app._fp_cache = {'old': {}}
            app._preset_manifest_cache = {'old': {}}
            app._waveform_cache['old.sin'] = [1.0]
            app.set_library_root(second)

            expected = {
                'LIBRARY_DIR': second,
                '_TAGS_PATH': second / 'tags.json',
                'SNAP_DIR': second / 'snapshots',
                'SNAP_INDEX_PATH': second / 'snapshots' / 'index.json',
                'FP_PATH': second / 'fingerprints.json',
                'PRESET_MANIFEST_PATH': second / 'preset_manifest.json',
            }
            for name, path in expected.items():
                check(getattr(app, name) == path, f'{name} follows the configured root')

            leaks = []
            for name, value in vars(app).items():
                if not isinstance(value, Path):
                    continue
                try:
                    if value.resolve().is_relative_to(first):
                        leaks.append(name)
                except OSError:
                    pass
            check(not leaks, f'no module Path remains under the previous root: {leaks}')
            check(app._fp_cache is None, 'fingerprint cache is invalidated')
            check(app._preset_manifest_cache is None, 'preset manifest cache is invalidated')
            check(app._waveform_cache == {}, 'waveform cache is invalidated')

            app.save_tags({'sentinel.sin': ['second']})
            app._save_snap_index([{'id': 'second'}])
            check(app._TAGS_PATH.is_file(), 'tag writes land in the new root')
            check(app.SNAP_INDEX_PATH.is_file(), 'snapshot index writes land in the new root')
            check(first_tags.read_bytes() == first_tags_bytes and
                  first_tags.stat().st_mtime_ns == first_tags_mtime,
                  'tag writes leave the previous root unchanged')
            check(first_index.read_bytes() == first_index_bytes and
                  first_index.stat().st_mtime_ns == first_index_mtime,
                  'snapshot writes leave the previous root unchanged')
    finally:
        app.set_library_root(original_root)

    if failures:
        print(f'\n{len(failures)} library-isolation contract(s) failed')
        sys.exit(1)
    print('\nall library-isolation contracts passed')


if __name__ == '__main__':
    main()
