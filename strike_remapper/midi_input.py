"""Optional input-only RtMidi helper, isolated from the editor process."""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from strike_remapper.runtime import worker_command

ROOT = Path(__file__).resolve().parent.parent
MISSING = 'Host MIDI needs python-rtmidi. Install requirements-midi.txt with the Python that runs the editor, then refresh inputs.'


def channel_message(data):
    if not isinstance(data, (list, tuple)) or not data or any(type(v) is not int for v in data):
        return False
    return (0x80 <= data[0] < 0xf0 and len(data) == (2 if data[0] >> 4 in (12, 13) else 3)
            and all(0 <= v < 128 for v in data[1:]))


def ports_snapshot(names):
    # Include the complete enumeration so a changed order cannot silently select
    # a different device. Names are not a persistent hardware identity.
    digest = hashlib.sha256(json.dumps(names).encode()).hexdigest()[:16]
    return [{'id': f'{digest}-{i}', 'name': name[:160]} for i, name in enumerate(names)]


def process_options():
    return {'cwd': ROOT, 'text': True, 'encoding': 'utf-8',
            'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}


class NativeInput:
    def inputs(self):
        try:
            result = subprocess.run(worker_command('midi-input'),
                                    capture_output=True, timeout=8, **process_options())
            data = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError('Host MIDI driver did not respond. Check the host setup and refresh inputs.') from exc
        if result.returncode or 'error' in data:
            raise RuntimeError(data.get('error', 'Host MIDI helper failed.'))
        return data['inputs']

    def open(self, port, receive, failed):
        return InputProcess(port, receive, failed)


class InputProcess:
    def __init__(self, port, receive, failed):
        self.closed = False
        self.process = subprocess.Popen(worker_command('midi-input', port),
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        **process_options())
        self.thread = threading.Thread(target=self._read, args=(receive, failed), daemon=True)
        self.thread.start()

    def _read(self, receive, failed):
        reason = 'Host MIDI input stopped or disconnected. Captured events are kept.'
        try:
            for line in self.process.stdout:
                item = json.loads(line)
                if 'error' in item:
                    reason = item['error']
                    break
                if channel_message(item.get('data')):
                    receive(item['data'], item['stamp'])
        except (OSError, ValueError, KeyError):
            reason = 'Host MIDI stream failed. Captured events are kept.'
        finally:
            if not self.closed:
                failed(reason)

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
        self.process.stdout.close()


def run_worker(rtmidi, selected=None, output=None, stop=None):
    """Injectable driver boundary. Never constructs a MIDI output object."""
    output = output or (lambda value: print(json.dumps(value), flush=True))
    stop = stop or threading.Event()
    midi = rtmidi.MidiIn()
    try:
        names = midi.get_ports()
        ports = ports_snapshot(names)
        if selected is None:
            output({'inputs': ports})
            return
        index = next((i for i, port in enumerate(ports) if port['id'] == selected), None)
        if index is None:
            raise ValueError('MIDI inputs changed. Refresh inputs and select the device again.')
        events = queue.Queue(maxsize=4096)
        overflow = threading.Event()

        def receive(event, _):
            data, _delta = event
            if channel_message(data):
                try:
                    events.put_nowait({'data': list(data), 'stamp': time.monotonic()})
                except queue.Full:
                    overflow.set()

        midi.ignore_types(sysex=True, timing=True, active_sense=True)
        midi.set_callback(receive)
        midi.open_port(index)
        check_at = time.monotonic()
        while not stop.is_set():
            if overflow.is_set():
                raise RuntimeError('MIDI input overflowed. Capture stopped; this take may be incomplete.')
            if time.monotonic() >= check_at:
                if midi.get_ports() != names:
                    raise RuntimeError('MIDI inputs changed or disconnected. Capture stopped; refresh inputs.')
                check_at = time.monotonic() + 1
            try:
                output(events.get(timeout=.1))
            except queue.Empty:
                pass
    finally:
        midi.close_port()
        midi.delete()


def main():
    try:
        try:
            import rtmidi
        except ImportError:
            raise RuntimeError(MISSING) from None
        run_worker(rtmidi, sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
