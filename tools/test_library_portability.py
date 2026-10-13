"""Fresh-process upgrade/backup rehearsal with copied applications and synthetic kits.

Set STRIKE_PREVIOUS_APP to an extracted previous release to also rehearse a real
version boundary. Without it, CI checks relocation using two copies of current code.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
PROBE = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import strike_remap as app
app.set_library_root(sys.argv[2])
app.get_volumes = lambda: (None, None)
root = Path(sys.argv[2])
if sys.argv[3] == 'prepare':
    app.create_new_kit('Portable kit')
    app.set_pad_param('S1H', 'la_level', 63)
    app.autosave_kit()
    (root / 'tags.json').write_text('{"Snare/test.sin": ["Keep this tag"]}')
    (root / 'samples').mkdir(exist_ok=True)
    (root / 'samples' / 'keep.bin').write_bytes(b'synthetic sample sentinel')
else:
    recovery = root / 'kits' / 'Portable kit.autosave.skt'
    before = recovery.read_bytes()
    app.load_kit(str(recovery))
    actual = app.build_skt(app.state['kit_raw'], app.state['pads'], app.state['instruments'], app.state['tail'])
    assert actual == before, 'Recovered bytes changed across application versions'
    pads = app.Handler._pad_view(None, app.state['pads'], app.state['instruments'])
    assert next(p for p in pads if p['id'] == 'S1H')['la_level'] == 63
    assert b'Keep this tag' in (root / 'tags.json').read_bytes()
    assert (root / 'samples' / 'keep.bin').read_bytes() == b'synthetic sample sentinel'
print('verified', sys.argv[3])
'''


def manifest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class LibraryPortabilityTests(unittest.TestCase):
    def test_backup_upgrade_and_rollback_keep_external_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            release = base / 'New application folder'
            release.mkdir()
            for name in ('strike_remap.py', 'factory_catalog.json', 'factory_fingerprints.json'):
                shutil.copy2(ROOT / name, release / name)
            shutil.copytree(ROOT / 'strike_remapper', release / 'strike_remapper',
                            ignore=shutil.ignore_patterns('__pycache__'))
            previous = Path(os.environ.get('STRIKE_PREVIOUS_APP', ROOT)).resolve()
            library = base / 'My persistent library'
            library.mkdir()

            def run(application, folder, phase):
                result = subprocess.run([sys.executable, '-c', PROBE, str(application), str(folder), phase],
                                        cwd=base, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            # Start on the previous version, back up its complete library, then
            # recover with the application launched from a new installation path.
            run(previous, library, 'prepare')
            baseline = manifest(library)
            self.assertTrue(any(Path(name).parts[0] == 'snapshots' and name.endswith('.skt') for name in baseline))
            self.assertIn('tags.json', baseline)
            backup = base / 'Backup before upgrade'
            shutil.copytree(library, backup)
            self.assertEqual(manifest(backup), baseline)
            run(release, library, 'recover')
            self.assertEqual(manifest(backup), baseline)
            # Rollback uses a fresh copy of the backup, never the live library.
            restored = base / 'Rollback working copy'
            shutil.copytree(backup, restored)
            self.assertEqual(manifest(restored), baseline)
            live_after_upgrade = manifest(library)
            run(previous, restored, 'recover')
            self.assertEqual(manifest(library), live_after_upgrade)
            self.assertEqual(manifest(backup), baseline)
            self.assertFalse((release / 'library').exists())


if __name__ == '__main__':
    unittest.main()
