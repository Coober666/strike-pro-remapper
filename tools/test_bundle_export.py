"""Bundle consistency and restore checks with synthetic, disposable libraries."""
import copy
import http.client
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import socket
import unittest
from unittest.mock import patch
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.library = self.root / 'source'
        old_state, old_root = copy.deepcopy(app.state), app.LIBRARY_DIR
        self.addCleanup(lambda: (app.state.clear(), app.state.update(old_state), app.set_library_root(old_root)))
        app.set_library_root(self.library)
        guard = patch.object(app, 'get_volumes', return_value=(None, None))
        guard.start(); self.addCleanup(guard.stop)
        app.create_new_kit('Export fixture')
        self.ref = 'Test/One.sin'; self.wav = 'Test/one.wav'
        self.sin_path = self.library / 'instruments' / self.ref
        self.sin_path.parent.mkdir(parents=True, exist_ok=True)
        self.sin = app._build_sin([(self.wav, 1, 127, 1)])
        self.sin_path.write_bytes(self.sin)
        self.wav_path = self.library / 'samples' / self.wav
        self.wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(self.wav_path), 'wb') as sound:
            sound.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            sound.writeframes(b'\x01\x00' * 20)
        app.state['instruments'] = [self.ref]
        pad = app.state['pads'][0]; pad['layer_a'] = 0
        struct.pack_into('<H', pad['payload'], 4, 0)
        app.state['avail'] = {}

    def unpack(self):
        payload, name = app.export_bundle()
        self.assertTrue(name.endswith('.strike-bundle.zip'))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        return payload, files, json.loads(files['manifest.json'])

    def test_lazy_inventory_and_unsaved_round_trip_into_fresh_library(self):
        app.set_pad_param(app.state['pads'][0]['id'], 'la_level', 73)
        before = copy.deepcopy(app.state)
        expected = app.build_skt(before['kit_raw'], before['pads'], before['instruments'], before['tail'])
        payload, files, manifest = self.unpack()
        self.assertEqual(files['instruments/' + self.ref], self.sin)
        self.assertEqual(files['samples/' + self.wav], self.wav_path.read_bytes())
        self.assertEqual(manifest['missing'], {'instruments': [], 'samples': []})
        self.assertEqual(files['kit/' + manifest['kit']], expected)
        for key in ('kit_path', 'pads', 'instruments', 'dirty', 'history'):
            self.assertEqual(app.state[key], before[key])
        target = self.root / 'restored'; app.set_library_root(target)
        result = app.import_bundle(payload)
        self.assertEqual([result[k] for k in ('kits', 'instruments', 'samples')], [1, 1, 1])
        self.assertEqual((target / 'kits' / manifest['kit']).read_bytes(), expected)
        self.assertEqual((target / 'instruments' / self.ref).read_bytes(), self.sin)
        self.assertEqual((target / 'samples' / self.wav).read_bytes(), files['samples/' + self.wav])
        self.assertEqual(app.import_bundle(payload)['skipped'], 3)

    def test_library_instrument_edits_win_over_shadow_inventory(self):
        shadow = self.root / 'shadow.sin'; shadow.write_bytes(b'old instrument')
        app.state['avail'] = {self.ref: shadow}
        _, files, _ = self.unpack()
        self.assertEqual(files['instruments/' + self.ref], self.sin)

    def test_export_holds_state_lock_until_archive_is_built(self):
        app.state['avail'] = {self.ref: self.sin_path}
        acquired = threading.Event(); workers = []; observed = []
        build = app.build_skt
        def competing_edit():
            with app.STATE_LOCK:
                app.state['instruments'] = ['Changed/Other.sin']
                acquired.set()
        def interleave(*args):
            data = build(*args)
            thread = threading.Thread(target=competing_edit); workers.append(thread); thread.start()
            observed.append(acquired.wait(.15))
            return data
        try:
            with patch.object(app, 'build_skt', interleave):
                _, files, _ = self.unpack()
        finally:
            for worker in workers: worker.join(3)
        self.assertEqual(observed, [False], 'an edit entered while the bundle was being built')
        self.assertTrue(acquired.is_set())
        self.assertIn('instruments/' + self.ref, files)

    def test_missing_dependencies_are_explicit_and_read_failures_fail_export(self):
        app.state['avail'] = {self.ref: self.sin_path}
        self.wav_path.unlink()
        _, _, manifest = self.unpack()
        self.assertEqual(manifest['missing']['samples'], [self.wav])
        with patch.object(app, 'read_card_bytes', side_effect=OSError('read failed fixture')):
            with self.assertRaisesRegex(OSError, 'read failed fixture'):
                app.export_bundle()

    def test_unsafe_sample_reference_is_rejected_before_read(self):
        self.sin_path.write_bytes(app._build_sin([('../outside.wav', 1, 127, 1)]))
        (self.library / 'outside.wav').write_bytes(b'private fixture')
        app.state['avail'] = {self.ref: self.sin_path}
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            app.export_bundle()

    def test_export_respects_import_size_limits_and_case_collisions(self):
        from strike_remapper import bundle_import as limits
        app.state['avail'] = {self.ref: self.sin_path}
        for key, bound in [('MAX_ZIP_BYTES', 2), ('MAX_SIN_BYTES', 2),
                           ('MAX_FILE_BYTES', 2), ('MAX_TOTAL_BYTES', 2), ('MAX_ENTRIES', 2)]:
            with self.subTest(key=key), patch.object(limits, key, bound):
                with self.assertRaisesRegex(ValueError, 'limit'):
                    app.export_bundle()
        self.sin_path.write_bytes(app._build_sin([(self.wav, 1, 60, 1), ('Test/ONE.wav', 61, 127, 1)]))
        other = self.wav_path.with_name('ONE.wav')
        if not other.exists():  # Case-sensitive hosts need both fixtures.
            other.write_bytes(self.wav_path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Case-ambiguous'):
            app.export_bundle()

    def test_disconnected_http_download_releases_lock_and_keeps_server_usable(self):
        before = copy.deepcopy(app.state)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', json.dumps({'missing': {'instruments': [], 'samples': []}}))
            archive.writestr('sample.wav', b'\0' * (8 * 1024 * 1024))
        server = app._Server(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            with patch.object(app, '_export_bundle_locked', return_value=(data.getvalue(), 'Test.zip')):
                connection.connect()
                connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                connection.request('GET', '/api/export_bundle')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                acquired = app.STATE_LOCK.acquire(timeout=1)
                self.assertTrue(acquired, 'network transfer still holds editor lock')
                if acquired: app.STATE_LOCK.release()
                response.close(); connection.close()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            connection.request('GET', '/api/session')
            response = connection.getresponse(); response.read()
            self.assertEqual(response.status, 200)
            for key in ('kit_path', 'pads', 'dirty', 'history'):
                self.assertEqual(app.state[key], before[key])
        finally:
            connection.close(); server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__':
    unittest.main()
