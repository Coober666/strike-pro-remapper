"""Host start/stop, pairing and recovery tests using loopback and temporary files."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.host import Host, pairing_matrix
import strike_remap as app


class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Host()
        self.cards = patch.object(app, 'get_volumes', return_value=(None, None))
        self.cards.start()

    def tearDown(self):
        self.host.stop()
        self.cards.stop()
        self.tmp.cleanup()

    def request(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.host.server.server_port)
        conn.request('POST' if body is not None else 'GET', path,
                     json.dumps(body) if body is not None else None, headers or {})
        response = conn.getresponse()
        status, headers, data = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, headers, data

    def test_local_host_lifecycle_and_stop_failure(self):
        self.host.start(self.tmp.name, port=0)
        self.assertEqual(self.request('/api/session')[0], 200)
        self.assertFalse(self.host.pair_url)
        app.create_new_kit('Lifecycle')
        app.set_pad_param('S1H', 'la_level', 66)
        with patch.object(app, 'autosave_kit', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):
                self.host.stop()
        self.assertTrue(self.host.running)
        self.assertEqual(self.request('/api/session')[0], 200)
        self.host.stop()
        self.assertTrue((Path(self.tmp.name) / 'kits/Lifecycle.autosave.skt').is_file())
        self.host.start(self.tmp.name, port=0)
        session = json.loads(self.request('/api/session')[2])
        self.assertTrue(session['dirty'])

    def test_wifi_pairing_requires_token_and_diagnostics_omit_it(self):
        url = self.host.start(self.tmp.name, bind='127.0.0.1', port=0)
        self.assertEqual(self.request('/api/session')[0], 401)
        token = url.split('#pair=')[1]
        self.assertNotIn(token, self.host.diagnostics())
        status, headers, _ = self.request('/wifi/pair', {'token':token}, {'Origin':self.host.url, 'Content-Type':'application/json'})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.assertEqual(self.request('/api/session', headers={'Cookie':cookie})[0], 200)
        matrix = pairing_matrix(url)
        self.assertTrue(all(len(row) == len(matrix) for row in matrix))
        self.assertEqual(matrix[0][:7], [True] * 7)
        self.host.stop()
        self.host.start(self.tmp.name, bind='127.0.0.1', port=0)
        self.assertNotEqual(self.host.pair_url, url)
        self.assertEqual(self.request('/api/session', headers={'Cookie':cookie})[0], 401)

    def test_unsafe_bind_and_occupied_port_are_not_reused(self):
        with self.assertRaises(ValueError):
            self.host.start(self.tmp.name, bind='0.0.0.0', port=0)
        self.host.start(self.tmp.name, port=0)
        other = Host()
        with self.assertRaises(OSError):
            other.start(self.tmp.name, port=self.host.server.server_port)
        self.assertFalse(other.running)
        self.assertTrue(self.host.running)


if __name__ == '__main__':
    unittest.main()
