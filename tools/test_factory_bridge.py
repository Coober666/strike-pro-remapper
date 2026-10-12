"""Pairing, fixed-message, concurrency, and read-only discovery contracts; no hardware."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper import factory_bridge as bridge, factory_midi as midi


class FakeMIDI:
    def __init__(self):
        self.devices = [(0, 'Keyboard'), (2, 'Alesis Strike'), (3, 'NotStrike')]
        self.sent = []

    def outputs(self):
        return self.devices

    def activate(self, endpoint):
        self.sent.append(endpoint)


class NativeContracts(unittest.TestCase):
    def test_packet_matches_hardware_evidence_and_only_selected_strike_can_send(self):
        packet = bridge.ROOT / 'docs/evidence/factory-sd-2026-10-12/activation.syx'
        self.assertEqual(midi.ACTIVATION, packet.read_bytes())
        fake = FakeMIDI()
        outputs = midi.execute(backend=fake)['outputs']
        self.assertEqual([o['name'] for o in outputs], ['Alesis Strike'])
        self.assertEqual(fake.sent, [])
        selected = outputs[0]['id']
        with self.assertRaises(ValueError):
            midi.execute(midi.output_id(0, 'Keyboard'), fake)
        midi.execute(selected, fake)
        self.assertEqual(fake.sent, [2])
        fake.devices = [(2, 'Keyboard')]
        with self.assertRaises(ValueError):
            midi.execute(selected, fake)
        self.assertEqual(fake.sent, [2])

    def test_alsa_ignores_input_only_ports_and_does_not_execute_names(self):
        listing = 'Dir Device Name\nI hw:1,0,0 Alesis Strike\nIO hw:2,0,0 Alesis Strike\nO hw:3,1 Other\n'
        with patch.object(midi.shutil, 'which', return_value='/usr/bin/amidi'), patch.object(midi.subprocess, 'run') as run:
            run.return_value.stdout, run.return_value.returncode = listing, 0
            driver = midi.LinuxMIDI()
            self.assertEqual(driver.outputs(), [('hw:2,0,0', 'Alesis Strike'), ('hw:3,1', 'Other')])
            driver.activate('hw:2,0,0')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/amidi', '-p', 'hw:2,0,0', '-S', midi.ACTIVATION.hex()])

    def test_discovery_reads_only_and_requires_read_only_factory_shape(self):
        import strike_remap as app
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Instruments').mkdir()
            (root / 'Kits/ACOUSTIC').mkdir(parents=True)
            (root / 'Kits/ACOUSTIC/test.skt').write_bytes(b'fixture')
            before = sorted(p.relative_to(root) for p in root.rglob('*'))
            with patch.object(bridge, 'read_only_root', return_value=False):
                self.assertFalse(bridge.factory_present(root))
            with patch.object(bridge, 'read_only_root', return_value=True), patch.object(app, '_volume_writable', side_effect=AssertionError('must not write probe')):
                self.assertTrue(bridge.factory_present(root))
            self.assertEqual(before, sorted(p.relative_to(root) for p in root.rglob('*')))


def wait_job(controller, request_id):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        job = controller.get(request_id)
        if job['state'] not in ('checking', 'sent'):
            return job
        time.sleep(.01)
    raise AssertionError('job never completed')


class ControllerContracts(unittest.TestCase):
    def test_duplicate_and_concurrent_requests_send_once(self):
        gate = threading.Event()
        sent = []
        def send(output):
            sent.append(output)
            gate.wait(2)
        controller = bridge.Controller(send, lambda: bool(sent) and gate.is_set())
        request_id, output = 'a' * 32, 'b' * 24
        controller.start(request_id, output)
        controller.start(request_id, output)
        with self.assertRaises(ValueError):
            controller.start('c' * 32, output)
        with self.assertRaises(ValueError):
            controller.start(request_id, 'd' * 24)
        gate.set()
        self.assertEqual(wait_job(controller, request_id)['state'], 'ready')
        controller.start(request_id, output)
        self.assertEqual(sent, [output])

    def test_already_available_skips_midi(self):
        def no_send(*args):
            raise AssertionError('already mounted')
        controller = bridge.Controller(no_send, lambda: True)
        controller.start('a' * 32, 'b' * 24)
        self.assertEqual(wait_job(controller, 'a' * 32)['state'], 'ready')

    def test_timeout_and_driver_error_do_not_retry(self):
        for fail in (False, True):
            sent = []
            def send(output):
                sent.append(output)
                if fail:
                    raise RuntimeError('driver unavailable')
            controller = bridge.Controller(send, lambda: False, timeout=.02)
            controller.start('a' * 32, 'b' * 24)
            self.assertEqual(wait_job(controller, 'a' * 32)['state'], 'failed' if fail else 'unconfirmed')
            self.assertEqual(sent, ['b' * 24])


class HTTPContracts(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.output = 'b' * 24
        def native(selected=None):
            if selected is not None:
                self.sent.append(selected)
            return {'outputs': [{'id': self.output, 'name': 'Alesis Strike'}]}
        self.controller = bridge.Controller(native, lambda: bool(self.sent))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.make_handler(self.controller, 'test-pair', 'host.test:8766'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        base = {'Host': 'host.test:8766', 'Authorization': 'Bearer test-pair', 'Content-Type': 'application/json'}
        base.update(headers or {})
        connection.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, base)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_pairing_origin_host_and_fixed_route_are_required(self):
        body = {'request_id': 'a' * 32, 'output': self.output}
        self.assertEqual(self.request('/api/outputs', headers={'Authorization': ''})[0], 401)
        self.assertEqual(self.request('/api/outputs', headers={'Host': 'evil.test'})[0], 403)
        for origin in ('null', 'http://evil.test', 'http://host.test:9999'):
            self.assertEqual(self.request('/api/activate', body, {'Origin': origin})[0], 403)
        self.assertEqual(self.request('/api/send', body)[0], 404)
        self.assertEqual(self.request('/api/activate', dict(body, bytes=[1, 2, 3]))[0], 400)
        self.assertEqual(self.request('/api/activate', {'request_id': [], 'output': self.output})[0], 400)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.request('/api/activate', body, {'Origin': 'http://host.test:8766'})[0], 202)
        self.assertEqual(wait_job(self.controller, body['request_id'])['state'], 'ready')
        self.assertEqual(self.sent, [self.output])

    def test_assets_do_not_leak_pairing_or_expose_editor_files(self):
        code, page = self.request('/', headers={'Authorization': ''})
        self.assertEqual(code, 200)
        self.assertNotIn(b'test-pair', page)
        self.assertEqual(self.request('/../strike_remap.py')[0], 404)
        self.assertEqual(self.request('/api/status')[0], 404)
        self.assertEqual(self.request('/api/outputs')[0], 200)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
