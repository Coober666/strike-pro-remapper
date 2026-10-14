"""Bundle imports use disposable libraries, never mounted module cards."""
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app
from strike_remapper import bundle_import as bundles


def archive(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        for name, content in entries:
            z.writestr(name, content)
    return data.getvalue()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.library = self.root / 'library'
        self.library.mkdir()
        old, library = copy.deepcopy(app.state), app.LIBRARY_DIR
        self.addCleanup(lambda: (app.state.clear(), app.state.update(old), app.set_library_root(library)))
        app.set_library_root(self.library)
        guard = patch.object(app, 'get_volumes', side_effect=AssertionError('No cards'))
        guard.start(); self.addCleanup(guard.stop)
        refresh = patch.object(app, 'refresh_available')
        refresh.start(); self.addCleanup(refresh.stop)

    def test_unsafe_entries_reject_before_any_file_is_imported(self):
        for name in ('samples/../../escape.wav', 'samples/..\\..\\escape.wav',
                     'samples/' + (self.root / 'escape.wav').as_posix(),
                     'samples/NUL.wav', 'samples/bad.wav:stream'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    app.import_bundle(archive([('kits/first.skt', b'kit'), (name, b'bad')]))
                self.assertEqual(list(self.library.rglob('*.skt')), [])
                self.assertFalse((self.root / 'escape.wav').exists())

    def test_late_corruption_does_not_leave_earlier_files(self):
        original = zipfile.ZipFile.open
        def broken(z, name, *args, **kwargs):
            if (name.filename if isinstance(name, zipfile.ZipInfo) else name) == 'samples/bad.wav':
                raise zipfile.BadZipFile('CRC fixture')
            return original(z, name, *args, **kwargs)
        payload = archive([('kits/first.skt', b'kit'), ('samples/bad.wav', b'bad')])
        with patch.object(zipfile.ZipFile, 'open', broken):
            with self.assertRaises((ValueError, zipfile.BadZipFile)):
                app.import_bundle(payload)
        self.assertEqual(list(self.library.rglob('*.skt')), [])

    def test_repeat_sample_only_import_is_successful_and_preserves_conflicts(self):
        payload = archive([('Pack/Samples/Drums/one.wav', b'one')])
        self.assertEqual(app.import_bundle(payload)['samples'], 1)
        self.assertEqual(app.import_bundle(payload)['skipped'], 1)
        conflict = app.import_bundle(archive([('Samples/Drums/one.wav', b'different')]))
        self.assertEqual(conflict['conflicts'], ['Drums/one.wav'])
        self.assertEqual((self.library / 'samples/Drums/one.wav').read_bytes(), b'one')

    def test_kit_rename_and_loose_sample_mapping_remain_compatible(self):
        (self.library / 'kits').mkdir()
        (self.library / 'kits/Show.skt').write_bytes(b'original')
        sin = app._build_sin([('Drums/one.wav', 1, 127, 1)])
        payload = archive([('Pack/Kits/Show.skt', b'new'), ('Pack/Instruments/Drums/One.sin', sin), ('one.wav', b'wave')])
        result = app.import_bundle(payload)
        self.assertEqual(result['kit_names'], ['Show (2).skt'])
        self.assertEqual((self.library / 'kits/Show.skt').read_bytes(), b'original')
        self.assertEqual((self.library / 'samples/Drums/one.wav').read_bytes(), b'wave')
        self.assertEqual(app.import_bundle(payload)['skipped'], 3)

    def test_partial_disk_failure_is_reported_and_retry_skips_completed_files(self):
        payload = archive([('kits/Show.skt', b'kit'), ('samples/one.wav', b'wave')])
        original = bundles.shutil.copyfileobj
        def fail_sample(source, target, *args):
            if Path(target.name).name == 'one.wav':
                target.write(b'partial')
                raise OSError('disk full fixture')
            return original(source, target, *args)
        with patch.object(bundles.shutil, 'copyfileobj', fail_sample):
            with self.assertRaisesRegex(bundles.ImportStopped, 'after 1 completed new file'):
                app.import_bundle(payload)
        self.assertEqual((self.library / 'kits/Show.skt').read_bytes(), b'kit')
        self.assertFalse((self.library / 'samples/one.wav').exists())
        result = app.import_bundle(payload)
        self.assertEqual((result['skipped'], result['samples']), (1, 1))
        self.assertFalse((self.library / 'kits/Show (2).skt').exists())

    def test_exclusive_creation_preserves_a_racing_file(self):
        target = self.library / 'sample.wav'; target.write_bytes(b'existing')
        source = self.root / 'staged'; source.write_bytes(b'new')
        with self.assertRaises(FileExistsError):
            bundles.publish(source, target)
        self.assertEqual(target.read_bytes(), b'existing')

    def test_refresh_failure_reports_completed_import(self):
        with patch.object(app, 'refresh_available', side_effect=OSError('listing fixture')):
            with self.assertRaisesRegex(bundles.ImportStopped, 'after 1 completed new file.*listing could not refresh'):
                app.import_bundle(archive([('samples/one.wav', b'wave')]))
        self.assertEqual((self.library / 'samples/one.wav').read_bytes(), b'wave')

    def test_cleanup_failure_identifies_incomplete_file(self):
        original = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path == self.library / 'samples/one.wav':
                raise OSError('cleanup fixture')
            return original(path, *args, **kwargs)
        def fail_copy(source, target, *args):
            target.write(b'partial'); raise OSError('disk fixture')
        with patch.object(Path, 'unlink', fail_cleanup), patch.object(bundles.shutil, 'copyfileobj', fail_copy):
            with self.assertRaisesRegex(bundles.ImportStopped, 'incomplete file one.wav; inspect it'):
                app.import_bundle(archive([('samples/one.wav', b'wave')]))
        self.assertEqual((self.library / 'samples/one.wav').read_bytes(), b'partial')

    def test_links_limits_duplicate_paths_and_unsafe_sample_references_are_preflighted(self):
        link = zipfile.ZipInfo('samples/link.wav'); link.create_system = 3
        link.external_attr = 0o120777 << 16
        bad = [archive([(link, b'target')]), archive([('samples/A.wav', b'a'), ('samples/a.wav', b'b')]),
               archive([('one/Samples/A.wav', b'a'), ('two/Samples/a.wav', b'b')]),
               archive([('Instruments/Test/one.sin', app._build_sin([('../escape.wav', 1, 127, 1)])), ('escape.wav', b'wave')])]
        for payload in bad:
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                app.import_bundle(payload)
            self.assertEqual(list(self.library.rglob('*')), [])
        payload = archive([('samples/one.wav', b'large')])
        for name, value in [('MAX_ENTRIES', 0), ('MAX_FILE_BYTES', 2), ('MAX_TOTAL_BYTES', 2), ('MAX_ZIP_BYTES', 2)]:
            with patch.object(bundles, name, value), self.assertRaises(ValueError):
                app.import_bundle(payload)
            self.assertEqual(list(self.library.rglob('*')), [])

    def test_linked_destination_is_rejected_before_publication(self):
        outside = self.root / 'outside'; outside.mkdir()
        try:
            (self.library / 'samples').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable on this host')
        with self.assertRaises(ValueError):
            app.import_bundle(archive([('kits/first.skt', b'kit'), ('samples/one.wav', b'wave')]))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.library / 'kits/first.skt').exists())


if __name__ == '__main__':
    unittest.main()
