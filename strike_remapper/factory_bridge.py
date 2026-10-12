"""Opt-in, paired LAN controller for factory activation only; not the editor API."""
import argparse
import ctypes
import hmac
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'web' / 'factory-controller'


def native_midi(selected=None):
    args = [sys.executable, '-m', 'strike_remapper.factory_midi']
    if selected is not None:
        args.append(selected)
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=6)
    except subprocess.TimeoutExpired:
        raise RuntimeError('MIDI driver timed out. The command may have been sent; check the card before trying again.') from None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('MIDI helper could not start on this host.') from None
    if result.returncode or data.get('error'):
        raise RuntimeError(data.get('error', 'MIDI helper failed.'))
    return data


def read_only_root(path):
    """Read OS volume flags; never create a probe file on either card."""
    if platform.system() == 'Windows':
        flags = ctypes.c_uint32()
        get_info = ctypes.WinDLL('kernel32').GetVolumeInformationW
        get_info.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
                            ctypes.c_void_p, ctypes.c_uint32]
        return bool(get_info(path.anchor, None, 0, None, None, ctypes.byref(flags), None, 0)
                    and flags.value & 0x80000)
    return bool(os.statvfs(path).f_flag & os.ST_RDONLY)


def factory_present(explicit_root=None):
    # Content shape plus read-only mount is evidence of an available factory library,
    # not a hardware identity assertion. Do not import/use the app's write-probe path.
    import strike_remap as app
    if explicit_root:
        roots = [Path(explicit_root)]
    elif platform.system() == 'Linux':
        roots = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            if len(fields) > 5 and 'ro' in fields[5].split(','):
                roots.append(Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])))
    else:
        roots = list(app._find_strike_volumes().values())
    matches = []
    for path in roots:
        try:
            if read_only_root(path) and (path / 'Instruments').is_dir() and app._looks_like_preset_root(path):
                matches.append(path.resolve())
        except OSError:
            continue
    return len(set(matches)) == 1


class Controller:
    def __init__(self, midi=native_midi, present=factory_present, timeout=15):
        self.midi, self.present, self.timeout = midi, present, timeout
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = None

    def start(self, request_id, output):
        if not re.fullmatch(r'[a-f0-9]{32}', request_id) or not re.fullmatch(r'[a-f0-9]{24}', output):
            raise ValueError('Refresh outputs and try again.')
        with self.lock:
            if request_id in self.jobs:
                job = self.jobs[request_id]
                if job['output'] != output:
                    raise ValueError('Request already belongs to a different output.')
                return dict(job)
            if self.active:
                raise ValueError('Activation is already running. Wait for its result.')
            while len(self.jobs) >= 64:
                del self.jobs[next(iter(self.jobs))]
            self.jobs[request_id] = {'id': request_id, 'output': output, 'state': 'checking',
                                     'message': 'Checking the host’s factory card…'}
            self.active = request_id
            job = dict(self.jobs[request_id])
        threading.Thread(target=self._run, args=(request_id, output), daemon=True).start()
        return job

    def get(self, request_id):
        with self.lock:
            return dict(self.jobs.get(request_id, {}))

    def _set(self, request_id, state, message):
        with self.lock:
            self.jobs[request_id].update(state=state, message=message)

    def _run(self, request_id, output):
        try:
            if self.present():
                self._set(request_id, 'ready', 'A read-only factory library is already available. No message sent.')
                return
            self.midi(output)  # exactly once; helper re-enumerates and validates selected Strike
            self._set(request_id, 'sent', 'Activation sent. Waiting for the host to detect the factory library…')
            until = time.monotonic() + self.timeout
            while time.monotonic() < until:
                if self.present():
                    self._set(request_id, 'ready', 'Read-only factory library detected on the USB host.')
                    return
                time.sleep(0.5)
            self._set(request_id, 'unconfirmed', 'Message sent, but a mounted read-only factory library was not confirmed. Check the host’s disks. No retry was sent.')
        except Exception as exc:
            self._set(request_id, 'failed', str(exc))
        finally:
            with self.lock:
                self.active = None


def make_handler(controller, token, authority):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # never log pairing tokens

        def reply(self, code, data, content_type='application/json'):
            body = json.dumps(data).encode() if content_type == 'application/json' else data
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, authenticated=True):
            if self.headers.get('Host') != authority:
                self.reply(403, {'error': 'Unexpected host address.'})
                return False
            origin = self.headers.get('Origin')
            if origin is not None and origin != 'http://' + authority:
                self.reply(403, {'error': 'Open the controller directly on its host address.'})
                return False
            if authenticated and not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                self.reply(401, {'error': 'Pair using the link shown on the USB host.'})
                return False
            return True

        def do_GET(self):
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/app.css': ('app.css', 'text/css; charset=utf-8')}
            if not self.guard(self.path not in assets):
                return
            if self.path in assets:
                name, content_type = assets[self.path]
                self.reply(200, (WEB / name).read_bytes(), content_type)
            elif self.path == '/api/outputs':
                try:
                    self.reply(200, controller.midi())
                except Exception as exc:
                    self.reply(503, {'error': str(exc)})
            elif self.path.startswith('/api/jobs/'):
                job = controller.get(self.path[len('/api/jobs/'):])
                self.reply(200 if job else 404, job or {'error': 'Activation session expired. Check the card on the host.'})
            else:
                self.reply(404, {'error': 'Not found.'})

        def do_POST(self):
            if not self.guard():
                return
            if self.path != '/api/activate':
                self.reply(404, {'error': 'Not found.'})
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 1024 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected a small JSON activation request.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'request_id', 'output'} or not all(isinstance(v, str) for v in data.values()):
                    raise ValueError('Expected a selected output and request ID.')
                self.reply(202, controller.start(data['request_id'], data['output']))
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1', help='Specific private LAN IPv4 address for iPad access')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--factory-root', type=Path, help='Optional known read-only factory mount (useful on headless Linux)')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required. Select your installed newer Python, not the macOS system Python.')
    address = ipaddress.ip_address(args.bind)
    if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
        parser.error('Bind to a specific private LAN IPv4 address or 127.0.0.1.')
    token = secrets.token_urlsafe(32)
    authority = f'{address}:{args.port}'
    controller = Controller(present=lambda: factory_present(args.factory_root))
    server = ThreadingHTTPServer((str(address), args.port), make_handler(controller, token, authority))
    print('Strike factory controller. Use only on your trusted local network; do not port-forward.')
    print('Pair this browser on the iPad (the link grants activation access until this process stops):')
    print(f'http://{authority}/#pair={token}', flush=True)
    print('This controller exposes activation only. The full editor remains localhost-only.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
