"""Promotion contracts: trusted CI identity, exact payloads and exclusive output."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_release import REPO, prepare, validate_run, verify_package

SHA = 'a' * 40
# Independent fixture: actual main CI run 39697035863, including matrix names.
# Keep this separate from the validator's requirements so workflow drift fails.
MAIN_JOB_NAMES = ('source-backup-windows (3.11)', 'source-backup-windows (3.10)',
                  'windows-host', 'test (ubuntu-latest)', 'test (macos-latest)',
                  'browser', 'source-beta', 'windows-beta')


def package(root, kind, *, revision=SHA, changed=False, extra=False, corrupt=False):
    prefix, manifest = (('Strike Remapper/', 'PACKAGE-MANIFEST.json') if kind == 'windows'
                        else ('strike-remapper-beta/', 'BETA-MANIFEST.json'))
    path = root / (kind + '.zip')
    data = b'fixture only'
    info = {'format': f'strike-{kind}-beta', 'version': 1, 'revision': revision,
            'workingTreeChanged': changed, 'files': {'app.txt': hashlib.sha256(data).hexdigest()}}
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(prefix + 'app.txt', b'altered' if corrupt else data)
        z.writestr(prefix + manifest, json.dumps(info))
        if extra:
            z.writestr(prefix + '../escape', b'bad')
    path.with_suffix('.sha256.txt').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')
    return path


class DeliveryTests(unittest.TestCase):
    def test_only_successful_main_push_with_all_jobs(self):
        run = {'repository': {'full_name': REPO}, 'path': '.github/workflows/ci.yml',
               'event': 'push', 'head_branch': 'main', 'status': 'completed',
               'conclusion': 'success', 'head_sha': SHA}
        jobs = [{'name': n, 'conclusion': 'success'} for n in MAIN_JOB_NAMES]
        self.assertEqual(validate_run(run, jobs), SHA)
        for key, bad in [('event', 'pull_request'), ('head_branch', 'feature'),
                         ('path', 'other.yml'), ('conclusion', 'failure'),
                         ('repository', {'full_name': 'elsewhere/repo'}), ('head_sha', '../bad')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_run({**run, key: bad}, jobs)
        for lane in jobs:
            for change, changed in [
                    ('missing', [j for j in jobs if j is not lane]),
                    ('duplicate', jobs + [lane]),
                    ('failed', [{**j, 'conclusion': 'failure'} if j is lane else j for j in jobs]),
                    ('skipped', [{**j, 'conclusion': 'skipped'} if j is lane else j for j in jobs])]:
                with self.subTest(lane=lane['name'], change=change), self.assertRaises(ValueError):
                    validate_run(run, changed)
        # A former non-matrix job must not substitute for either platform lane.
        legacy = [j for j in jobs if not j['name'].startswith('test (')]
        with self.assertRaises(ValueError):
            validate_run(run, legacy + [{'name': 'test', 'conclusion': 'success'}])

    def test_identity_checksums_inventory_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for change in [{'revision': 'b'*40}, {'changed': True}, {'extra': True}, {'corrupt': True}]:
                path = package(root, 'source', **change)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    verify_package(path, SHA, 'source')
            path = package(root, 'source')
            path.with_suffix('.sha256.txt').write_text('wrong')
            with self.assertRaises(ValueError):
                verify_package(path, SHA, 'source')

    def test_preparation_preserves_bytes_and_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, windows = package(root, 'source'), package(root, 'windows')
            output = root / 'delivery'
            result = prepare(source, windows, SHA, 'beta-20261014.1', '123', output)
            for p in result['packages']:
                self.assertEqual((output/p['file']).read_bytes(), (root/p['original']).read_bytes())
            self.assertIn('Python is bundled', (output/'START-HERE.txt').read_text())
            with self.assertRaises(FileExistsError):
                prepare(source, windows, SHA, 'beta-20261014.1', '123', output)
            with self.assertRaises(ValueError):
                prepare(source, windows, SHA, '--bad', '123', root/'bad')
            self.assertFalse((root/'bad').exists())


if __name__ == '__main__':
    unittest.main()
