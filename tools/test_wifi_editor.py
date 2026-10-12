"""Full-editor pairing boundary tests; no hardware or real library access."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app
from strike_remapper.wifi_editor import Pairing, make_handler
from strike_remapper.factory_bridge import Controller


class WifiEditorTests(unittest.TestCase):
    def setUp(self):
        self.original_root = app.LIBRARY_DIR
        self.temp = tempfile.TemporaryDirectory()
        app.set_library_root(self.temp.name)
        self.cards = patch.object(app, 'get_volumes', return_value=(None, None))
        self.cards.start()
        self.access = Pairing('test-editor-pairing', '127.0.0.1:0')
        self.controller = Controller(lambda selected=None: {'outputs': []}, lambda: False)
        self.server = app._Server(('127.0.0.1', 0), make_handler(app, self.access, self.controller))
        self.authority = f'127.0.0.1:{self.server.server_port}'
        self.access.authority = self.authority
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.cards.stop()
        app.set_library_root(self.original_root)
        self.temp.cleanup()

    def request(self, path='/', body=None, overrides=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Host': self.authority, 'Cookie': self.cookie}
        if body is not None:
            headers.update({'Origin': 'http://' + self.authority, 'Content-Type': 'application/json'})
        headers.update(overrides or {})
        conn.request('POST' if body is not None else 'GET', path,
                     body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def pair(self):
        code, headers, body = self.request('/wifi/pair', {'token': 'test-editor-pairing'})
        self.assertEqual(code, 200, body)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        return headers

    def test_unpaired_cannot_read_editor_or_mutate_or_send_midi(self):
        code, _, page = self.request()
        self.assertEqual(code, 200)
        self.assertIn(b'Pairing link', page)
        self.assertNotIn(b'boot-screen', page)
        self.assertNotIn(b'test-editor-pairing', page)
        for path in ('/api/kits', '/api/status', '/api/session', '/api/export_bundle', '/factory', '/api/outputs'):
            self.assertEqual(self.request(path)[0], 401, path)
        for path in ('/api/select', '/api/save', '/api/run_tool', '/api/deploy', '/api/activate'):
            self.assertEqual(self.request(path, {})[0], 401, path)
        self.assertEqual(self.request('/wifi/pair', {'token': 'wrong'})[0], 401)
        self.assertEqual(self.request('/wifi/pair', ['bad'])[0], 401)

    def test_pair_cookie_opens_editor_and_authenticated_api(self):
        headers = self.pair()
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertNotIn('test-editor-pairing', headers['Set-Cookie'])
        code, headers, page = self.request()
        self.assertEqual(code, 200)
        self.assertIn(b'data-wifi-editor="true"', page)
        self.assertIn(b'boot-screen', page)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(self.request('/api/kits')[0], 200)
        self.assertEqual(self.request('/api/select', {'pad_id': 'SNARE'})[0], 200)
        self.assertEqual(self.request('/api/outputs')[0], 200)
        self.assertIn(b'data-host-session="true"', self.request('/factory')[2])

    def test_origin_host_and_cross_site_checks_also_apply_after_pairing(self):
        self.pair()
        for headers in ({'Host':'evil.test'}, {'Origin':'http://evil.test'}, {'Origin':'null'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('/api/status', overrides=headers)[0], 403)
        for origin in ('', 'null', 'http://localhost:8765', 'http://' + self.authority + '/evil'):
            self.assertEqual(self.request('/api/select', {}, {'Origin':origin})[0], 403)
        # A Host-only spoof without Origin is not accepted for writes.
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', '/api/select', '{}', {'Host':self.authority, 'Cookie':self.cookie})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        conn.close()

    def test_logout_expiry_and_process_restart_revoke_access(self):
        self.pair()
        cookie = self.cookie
        self.assertEqual(self.request('/wifi/logout', {})[0], 200)
        self.assertEqual(self.request('/api/status')[0], 401)
        self.pair()
        with self.access.lock:
            self.access.sessions = dict.fromkeys(self.access.sessions, 0)
        self.assertEqual(self.request('/api/status')[0], 401)
        new_process = Pairing('new-pair-link', self.authority)
        self.assertFalse(new_process.authenticated({'Cookie':cookie}))


if __name__ == '__main__':
    unittest.main()
