"""Host MIDI contracts with injected drivers/clocks; no device or card access."""
import json
from pathlib import Path
import sys
import threading
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.midi_capture import MidiCapture, CaptureError, MAX_EVENTS
from strike_remapper.midi_input import run_worker, ports_snapshot, channel_message


class FakeBackend:
    def __init__(self):
        self.opens = 0
        self.closes = 0
        self.names = ['Drums']

    def inputs(self):
        return ports_snapshot(self.names)

    def open(self, port, receive, failed):
        self.opens += 1
        self.receive, self.failed = receive, failed
        return self

    def close(self):
        self.closes += 1


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.backend = FakeBackend()
        self.capture = MidiCapture(self.backend, lambda: self.now)
        self.id = 'a'*32

    def tearDown(self):
        self.capture.close()

    def call(self, action, owner='one', **data):
        return self.capture.request(owner, {'action': action, 'id': self.id, **data})

    def start(self):
        return self.call('start', input=self.backend.inputs()[0]['id'])

    def test_timestamp_pause_segments_and_input_filter(self):
        self.start()
        self.now += .1
        self.backend.receive([0x99, 38, 70], self.now)
        self.backend.receive([0xf0, 1, 0xf7], self.now)
        self.call('pause')
        self.now += 10
        self.backend.receive([0x99, 38, 90], self.now)
        self.call('resume')
        self.backend.receive([0x99, 38, 80], self.now-.01)  # queued before resume
        self.now += .2
        self.backend.receive([0x99, 38, 100], self.now)
        result = self.call('stop')
        self.assertEqual([e['t'] for e in result['events']], [100., 300.])
        self.assertEqual(result['session']['segments'], [0, 1])
        self.assertEqual(result['session']['captureStatus'], 'complete')
        self.assertEqual(self.backend.closes, 1)

    def test_idempotent_start_and_controls_no_takeover(self):
        self.start(); self.start()
        self.assertEqual(self.backend.opens, 1)
        with self.assertRaises(CaptureError): self.call('poll', owner='two')
        with self.assertRaises(CaptureError):
            self.capture.request('two', {'action':'start', 'id':'b'*32, 'input':self.backend.inputs()[0]['id']})
        self.call('pause'); self.call('pause')
        self.call('resume'); self.call('resume')
        self.assertEqual(self.call('stop')['mode'], 'stopped')
        self.assertEqual(self.call('resume')['mode'], 'stopped')

    def test_lost_response_replays_batch_without_loss_or_duplicate(self):
        self.start()
        for i in range(2050):
            self.backend.receive([0x99, 38, 70], self.now+i/100000)
        first = self.call('poll')
        retry = self.call('poll')
        self.assertEqual(first['events'], retry['events'])
        second = self.call('poll', offset=first['next'])
        third = self.call('stop', offset=second['next'])
        self.assertEqual(len(first['events']+second['events']+third['events']), 2050)
        self.assertEqual(third['next'], third['total'])

    def test_lease_stops_then_retains_then_expires(self):
        self.start()
        self.backend.receive([0x99, 38, 70], self.now)
        self.now += 16
        self.capture.maintenance()
        result = self.call('poll')
        self.assertEqual(result['mode'], 'stopped')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(self.backend.closes, 1)
        self.now += 601
        self.capture.maintenance()
        with self.assertRaises(CaptureError): self.call('poll')

    def test_limits_and_failure_preserve_events(self):
        self.start()
        for _ in range(MAX_EVENTS+1): self.backend.receive([0x99, 38, 70], self.now)
        self.assertEqual(self.call('poll')['total'], MAX_EVENTS)
        self.assertEqual(self.call('poll')['mode'], 'stopped')
        self.call('discard'); self.start()
        self.backend.receive([0x99, 38, 70], self.now)
        self.backend.failed('Driver overflow')
        result = self.call('poll')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['session']['captureStatus'], 'partial')

    def test_duration_limit_and_revoke_close_input(self):
        self.start()
        self.now += 1201
        self.capture.maintenance()
        self.assertEqual(self.call('poll')['mode'], 'stopped')
        self.call('discard'); self.start()
        self.capture.revoke('one')
        self.assertIsNone(self.capture.take)
        self.assertEqual(self.backend.closes, 2)

    def test_stale_port_and_invalid_requests(self):
        old = self.backend.inputs()[0]['id']; self.backend.names.insert(0,'Other')
        with self.assertRaises(CaptureError): self.call('start', input=old)
        self.start()
        for data in ([], {}, {'action':'poll','id':self.id,'offset':True}, {'action':'poll','id':self.id,'offset':1}):
            with self.assertRaises(CaptureError): self.capture.request('one', data)


class DriverTests(unittest.TestCase):
    def test_input_driver_filters_timestamps_and_closes_without_outputs(self):
        stop = threading.Event()
        class Input:
            def get_ports(self): return ['Drums']
            def ignore_types(self, **kw): self.filters=kw
            def set_callback(self, cb): self.callback=cb
            def open_port(self, index):
                self.index=index
                self.callback(([0x99, 38, 80], .1), None)
                self.callback(([0xf0, 1, 0xf7], .1), None)
            def close_port(self): self.closed=True
            def delete(self): self.deleted=True
        midi = Input()
        driver = types.SimpleNamespace(MidiIn=lambda: midi)  # no MidiOut API
        output=[]
        def receive(item):
            output.append(item); stop.set()
        run_worker(driver, ports_snapshot(['Drums'])[0]['id'], receive, stop)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]['data'], [0x99, 38, 80])
        self.assertGreater(output[0]['stamp'], 0)
        self.assertTrue(all(midi.filters.values()))
        self.assertTrue(midi.closed and midi.deleted)

    def test_filter_and_port_order_identity(self):
        for data in ([0xf8], [0xf0,1,0xf7], [0x99,38], [0x99,38,128], [0x99,38,True]):
            self.assertFalse(channel_message(data))
        self.assertTrue(channel_message([0xc9,1]))
        self.assertNotEqual(ports_snapshot(['A','B'])[0]['id'], ports_snapshot(['B','A'])[1]['id'])


if __name__ == '__main__':
    unittest.main()
