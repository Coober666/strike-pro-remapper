"""Recovery and failure regressions against disposable local files only."""
import base64
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app

FIXTURE = Path(__file__).resolve().parent.parent / 'tests/fixtures/synthetic_kit.skt'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.set_library_root(self.tmp.name)
        app.state.update(kit_raw=None, dirty=False, kit_path=None)
        self.cards = patch.object(app, 'get_volumes', return_value=(None, None))
        self.cards.start()
        self.server = app._Server(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.cards.stop()
        self.tmp.cleanup()

    def post(self, route, data):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', '/api/' + route, json.dumps(data), {'Content-Type':'application/json'})
        result = json.loads(conn.getresponse().read())
        conn.close()
        return result

    def import_dirty(self):
        self.post('load_bytes', {'filename':'Imported.skt', 'data':base64.b64encode(FIXTURE.read_bytes()).decode()})
        app.set_pad_param('S1H', 'la_level', 67)

    def test_switch_preserves_import_and_recovery_is_still_dirty(self):
        self.import_dirty()
        expected = app.build_skt(app.state['kit_raw'], app.state['pads'], app.state['instruments'], app.state['tail'])
        self.assertNotIn('error', self.post('new_kit', {'name':'Next'}))
        recovery = Path(self.tmp.name) / 'kits/Imported.autosave.skt'
        self.assertEqual(recovery.read_bytes(), expected)
        loaded = self.post('load', {'path':str(recovery)})
        self.assertTrue(loaded['dirty'])
        self.assertEqual(loaded['name'], 'Imported.skt')
        self.assertEqual(Path(app.autosave_kit()), recovery)
        self.assertFalse(list(recovery.parent.glob('*.autosave.autosave.skt')))
        self.assertNotIn('error', self.post('save', {'path':loaded['lib_save_path']}))
        self.assertEqual(Path(loaded['lib_save_path']).read_bytes(), expected)

    def test_failed_recovery_write_blocks_switch_without_losing_state(self):
        self.import_dirty()
        before = app.state['pads']
        with patch.object(app, 'autosave_kit', side_effect=OSError('Disk full')):
            result = self.post('load', {'path':str(FIXTURE)})
        self.assertIn('error', result)
        self.assertIs(app.state['pads'], before)
        self.assertTrue(app.state['dirty'])

    def test_interrupted_atomic_write_preserves_previous_recovery(self):
        self.import_dirty()
        recovery = Path(app.autosave_kit())
        before = recovery.read_bytes()
        app.set_pad_param('S1H', 'la_level', 22)
        with patch.object(app.os, 'replace', side_effect=OSError('Interrupted write')):
            with self.assertRaises(OSError):
                app.autosave_kit()
        self.assertEqual(recovery.read_bytes(), before)
        self.assertFalse(list(recovery.parent.glob('*.deploying')))

    def test_host_recovery_runs_without_a_browser_and_flushes_at_stop(self):
        self.import_dirty()
        worker = app.RecoveryWorker(interval=.02)
        recovery = Path(self.tmp.name) / 'kits/Imported.autosave.skt'
        try:
            deadline = time.monotonic() + 2
            while not recovery.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(recovery.exists())
            with app.STATE_LOCK:
                app.set_pad_param('S1H', 'la_level', 21)
        finally:
            worker.close()
        app.state.update(kit_raw=None, dirty=False, kit_path=None)
        app.load_kit(str(recovery))
        view = app.Handler._pad_view(None, app.state['pads'], app.state['instruments'])
        self.assertEqual(next(p for p in view if p['id'] == 'S1H')['la_level'], 21)

    def test_new_kit_cannot_overwrite_an_existing_kit(self):
        self.assertNotIn('error', self.post('new_kit', {'name':'Keep me'}))
        target = Path(app.state['kit_path'])
        before = target.read_bytes()
        self.assertIn('error', self.post('new_kit', {'name':'Keep me'}))
        self.assertEqual(target.read_bytes(), before)

    def test_recovering_same_kit_loads_requested_copy_and_snapshots_current_edits(self):
        self.import_dirty()
        recovery = Path(app.autosave_kit())
        requested = recovery.read_bytes()
        app.set_pad_param('S1H', 'la_level', 33)
        current = app.build_skt(app.state['kit_raw'], app.state['pads'], app.state['instruments'], app.state['tail'])
        loaded = self.post('load', {'path':str(recovery)})
        self.assertNotIn('error', loaded)
        self.assertEqual(app.build_skt(app.state['kit_raw'], app.state['pads'], app.state['instruments'], app.state['tail']), requested)
        self.assertIn(current, [p.read_bytes() for p in app.SNAP_DIR.glob('*.skt')])


if __name__ == '__main__':
    unittest.main()
