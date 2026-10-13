"""Bounded, leased host MIDI takes, independent of kits and MIDI outputs."""
from datetime import datetime, timezone
import math
import re
import threading
import time

from strike_remapper.midi_input import NativeInput, channel_message

MAX_EVENTS = 50000
MAX_SECONDS = 1200
LEASE_SECONDS = 15
RETAIN_SECONDS = 600


class CaptureError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class MidiCapture:
    def __init__(self, backend=None, clock=time.monotonic):
        self.backend = backend or NativeInput()
        self.clock = clock
        self.lock = threading.RLock()
        self.commands = threading.Lock()
        self.take = None
        self.reader = None
        self.closed = threading.Event()
        self.monitor = None

    def inputs(self):
        return self.backend.inputs()

    def _duration(self, take):
        duration = take['elapsed'] + (max(0, self.clock()-take['start']) if take['mode'] == 'recording' else 0)
        return min(MAX_SECONDS * 1000, max(duration * 1000, take['session']['events'][-1]['t'] if take['session']['events'] else 0))

    def _stop(self, reason, complete=True):
        if self.take and self.take['mode'] in ('recording', 'paused'):
            self.take['session']['durationMs'] = self._duration(self.take)
            self.take['session']['captureStatus'] = 'complete' if complete else 'partial'
            self.take.update(mode='stopped', reason=reason, retained=self.clock())

    def _failed(self, capture_id, reason):
        with self.lock:
            if self.take and self.take['id'] == capture_id:
                self._stop(reason, complete=False)

    def _receive(self, capture_id, data, stamp):
        with self.lock:
            take = self.take
            if not take or take['id'] != capture_id or take['mode'] != 'recording' or not channel_message(data):
                return
            if not isinstance(stamp, (float, int)) or not math.isfinite(stamp) or stamp < take['start']:
                return
            t = (take['elapsed'] + stamp - take['start']) * 1000
            events = take['session']['events']
            if t >= MAX_SECONDS * 1000 or len(events) >= MAX_EVENTS:
                self._stop('Capture limit reached. Save or export the take.')
                return
            # Helper timestamps use the same host monotonic clock; network arrival
            # time is never part of the measurements.
            t = max(events[-1]['t'] if events else 0, round(t, 3))
            events.append({'t': t, 'data': list(data)})
            if len(events) == MAX_EVENTS:
                self._stop('50,000-event limit reached. Save or export the take.')

    def _owned(self, owner, capture_id):
        if not self.take or self.take['id'] != capture_id:
            raise CaptureError('Host take expired or the host restarted. Received events are still available in this page.', 404)
        if self.take['owner'] != owner:
            raise CaptureError('This host take belongs to another paired browser.', 403)
        return self.take

    def request(self, owner, data):
        if not isinstance(data, dict) or data.get('action') not in ('start', 'poll', 'pause', 'resume', 'stop', 'discard'):
            raise CaptureError('Invalid MIDI capture request.', 400)
        action, capture_id = data['action'], data.get('id')
        if not isinstance(capture_id, str) or not re.fullmatch(r'[a-f0-9]{32}', capture_id):
            raise CaptureError('Invalid capture identifier.', 400)
        offset = data.get('offset', 0)
        if type(offset) is not int or not 0 <= offset <= MAX_EVENTS:
            raise CaptureError('Invalid event offset.', 400)
        if action == 'start' and offset != 0:
            raise CaptureError('A new capture must start at event zero.', 400)
        with self.commands:
            if self.closed.is_set():
                raise CaptureError('Host MIDI is shutting down.', 503)
            self.maintenance()
            if action == 'start':
                with self.lock:
                    if self.take:
                        if self.take['id'] != capture_id or self.take['owner'] != owner:
                            raise CaptureError('A host take is already open. Its browser must stop and release it, or wait for it to expire.')
                        if self.take['port'] != data.get('input'):
                            raise CaptureError('This request already belongs to a different input.')
                    else:
                        inputs = self.backend.inputs()
                        port = next((p for p in inputs if p['id'] == data.get('input')), None)
                        if not port:
                            raise CaptureError('MIDI inputs changed. Refresh inputs and choose again.', 400)
                        now = self.clock()
                        self.take = {'id': capture_id, 'owner': owner, 'port': port['id'], 'start': now,
                                     'elapsed': 0, 'seen': now, 'mode': 'recording', 'reason': 'Recording on the USB host.',
                                     'session': {'format': 'drum-midi-session', 'version': 1,
                                                 'name': 'Host capture', 'source': port['name'][:160], 'synthetic': False,
                                                 'createdAt': datetime.now(timezone.utc).isoformat(),
                                                 'durationMs': 0, 'segments': [0], 'captureStatus': 'partial', 'events': []}}
                        try:
                            self.reader = self.backend.open(port['id'],
                                lambda values, stamp: self._receive(capture_id, values, stamp),
                                lambda reason: self._failed(capture_id, reason))
                        except Exception as exc:
                            self._stop('Could not open MIDI input: ' + str(exc), complete=False)
                        if self.monitor is None:
                            self.monitor = threading.Thread(target=self._monitor, daemon=True)
                            self.monitor.start()
            with self.lock:
                take = self._owned(owner, capture_id)
                if offset > len(take['session']['events']):
                    raise CaptureError('Event offset is ahead of this take.', 400)
                take['seen'] = self.clock()
                if action == 'pause' and take['mode'] == 'recording':
                    take['elapsed'] = self._duration(take)/1000
                    take['mode'] = 'paused'
                    take['reason'] = 'Paused on the USB host.'
                elif action == 'resume' and take['mode'] == 'paused':
                    events = take['session']['events']
                    if take['session']['segments'][-1] != len(events):
                        take['session']['segments'].append(len(events))
                    take.update(start=self.clock(), mode='recording', reason='Recording on the USB host.')
                elif action in ('stop', 'discard'):
                    self._stop('Capture stopped. Save or export this take.')
                result = self._snapshot(take, offset)
            self.maintenance()
            if action == 'discard':
                with self.lock:
                    self.take = None
                return {'released': True}
            return result

    def _snapshot(self, take, offset):
        session = take['session']
        metadata = {key: value for key, value in session.items() if key != 'events'}
        metadata['segments'] = list(session['segments'])
        metadata['durationMs'] = self._duration(take) if take['mode'] != 'stopped' else session['durationMs']
        events = session['events'][offset:offset+1024]
        return {'id': take['id'], 'mode': take['mode'], 'reason': take['reason'], 'session': metadata,
                'offset': offset, 'next': offset+len(events), 'total': len(session['events']), 'events': events}

    def maintenance(self):
        with self.lock:
            if self.take:
                take = self.take
                if self.clock()-take['seen'] >= LEASE_SECONDS:
                    self._stop('Browser connection was lost or suspended. Capture stopped; recover the retained take.')
                if self._duration(take) >= MAX_SECONDS * 1000:
                    self._stop('20-minute limit reached. Save or export the take.')
                if take['mode'] == 'stopped' and self.clock()-take['retained'] >= RETAIN_SECONDS:
                    self.take = None
            reader = None
            if not self.take or self.take['mode'] == 'stopped':
                reader, self.reader = self.reader, None
        # Never join a native reader while holding the lock its callback needs.
        if reader:
            reader.close()

    def _monitor(self):
        while not self.closed.wait(.5):
            with self.commands:
                self.maintenance()

    def revoke(self, owner):
        with self.commands:
            with self.lock:
                if self.take and self.take['owner'] == owner:
                    self._stop('Pairing ended.')
                    self.take = None
            self.maintenance()

    def close(self):
        self.closed.set()
        with self.commands:
            with self.lock:
                self._stop('Host stopped.')
                self.take = None
            self.maintenance()
        if self.monitor:
            self.monitor.join(timeout=3)
