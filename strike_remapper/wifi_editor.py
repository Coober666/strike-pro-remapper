"""Opt-in paired LAN access to the full editor. Default localhost server is unchanged."""
import argparse
import hmac
from http.cookies import SimpleCookie
import ipaddress
import json
from pathlib import Path
import secrets
import threading
import time

from strike_remapper.factory_bridge import Controller, WEB as FACTORY_WEB

WEB = Path(__file__).resolve().parent.parent / 'web' / 'wifi-editor'


class Pairing:
    def __init__(self, token, authority):
        self.token = token
        self.authority = authority
        self.cookie_name = 'strike_editor_' + authority.rsplit(':', 1)[1]
        self.sessions = {}
        self.lock = threading.Lock()

    def same_origin(self, headers, write=False):
        if headers.get('Host') != self.authority:
            return False
        origin = headers.get('Origin')
        if origin is not None and origin != 'http://' + self.authority:
            return False
        if write and origin != 'http://' + self.authority:
            return False
        return headers.get('Sec-Fetch-Site') not in ('cross-site',)

    def session_id(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('Cookie', ''))
            return cookie[self.cookie_name].value if self.cookie_name in cookie else ''
        except Exception:
            return ''

    def authenticated(self, headers):
        session = self.session_id(headers)
        with self.lock:
            return self.sessions.get(session, 0) > time.time()

    def pair(self, token):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
            return None
        with self.lock:
            self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > time.time()}
            if len(self.sessions) >= 32:
                del self.sessions[next(iter(self.sessions))]
            session = secrets.token_urlsafe(32)
            self.sessions[session] = time.time() + 12 * 3600
        return self.cookie(session, 12 * 3600)

    def cookie(self, value, age):
        # Secure is intentionally absent for trusted-LAN HTTP. Session cookies are
        # HttpOnly, SameSite=Strict, host-only, port-named, and process-scoped.
        return f'{self.cookie_name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}'

    def logout(self, headers):
        with self.lock:
            self.sessions.pop(self.session_id(headers), None)
        return self.cookie('', 0)


def make_handler(app, pairing, controller=None):
    controller = controller or Controller()
    # Serialize ownership changes with complete editor writes (including deploy).
    # A page gets a fresh token on reload; in-flight writes from its old page lose
    # authority. No timeout silently transfers an unsaved kit to another browser.
    edit_lock = threading.RLock()
    owner = {'session': '', 'token': ''}

    class Handler(app.Handler):
        def editor_access(self):
            with pairing.lock:
                alive = pairing.sessions.get(owner['session'], 0) > time.time()
            if not alive:
                owner.update(session='', token='')
            editing = bool(owner['token']) and (
                owner['session'] == pairing.session_id(self.headers)
                and hmac.compare_digest(owner['token'].encode(), self.headers.get('X-Strike-Editor', '').encode()))
            return {'editing': editing, 'occupied': bool(owner['token'])}

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
            super().end_headers()

        def _guard(self):
            if not pairing.same_origin(self.headers, write=self.command == 'POST'):
                self.send_json({'error': 'Forbidden: open the editor directly at its paired host address.'}, 403)
                return False
            if not pairing.authenticated(self.headers):
                self.send_json({'error': 'Pairing required. Open the pairing link from the USB host.'}, 401)
                return False
            return True

        def document(self, body, content_type='text/html; charset=utf-8', cookie=None):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not pairing.same_origin(self.headers):
                self.send_json({'error': 'Unexpected host or origin.'}, 403)
                return
            assets = {'/wifi/pair.js': (WEB / 'pair.js', 'text/javascript; charset=utf-8'),
                      '/wifi/pair.css': (FACTORY_WEB / 'app.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                path, kind = assets[self.path]
                self.document(path.read_bytes(), kind)
                return
            if self.path == '/wifi/pair' or (self.path in ('/', '/index.html') and not pairing.authenticated(self.headers)):
                self.document((WEB / 'pair.html').read_bytes())
                return
            if not self._guard():
                return
            if self.path == '/wifi/editor':
                with edit_lock:
                    self.send_json(self.editor_access())
            elif self.path in ('/', '/index.html'):
                self.document(app.HTML.replace('<html lang="en">', '<html lang="en" data-wifi-editor="true">', 1))
            elif self.path == '/factory':
                page = (FACTORY_WEB / 'index.html').read_text(encoding='utf-8')
                self.document(page.replace('<html lang="en">', '<html lang="en" data-host-session="true">', 1))
            elif self.path in ('/app.js', '/app.css'):
                kind = 'text/javascript' if self.path.endswith('.js') else 'text/css'
                self.document((FACTORY_WEB / self.path[1:]).read_bytes(), kind + '; charset=utf-8')
            elif self.path == '/api/outputs':
                try:
                    self.send_json(controller.midi())
                except Exception as exc:
                    self.send_json({'error': str(exc)}, 503)
            elif self.path.startswith('/api/jobs/'):
                job = controller.get(self.path[len('/api/jobs/'):])
                self.send_json(job or {'error': 'Activation session expired. Check the host.'}, 200 if job else 404)
            else:
                super().do_GET()

        def small_json(self):
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 1024 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected a small JSON request.')
            return json.loads(self.rfile.read(length))

        def do_POST(self):
            if not pairing.same_origin(self.headers, write=True):
                self.send_json({'error': 'Forbidden: request must come from this editor.'}, 403)
                return
            if self.path == '/wifi/pair':
                try:
                    data = self.small_json()
                    cookie = pairing.pair(data.get('token')) if isinstance(data, dict) else None
                    if not cookie:
                        self.send_json({'error': 'Pairing link is incorrect or expired. Use the current link from the Mac/PC.'}, 401)
                        return
                    self.document('{"paired":true}', 'application/json', cookie)
                except (ValueError, TypeError):
                    self.send_json({'error': 'Invalid pairing request.'}, 400)
                return
            if not self._guard():
                return
            if self.path == '/wifi/logout':
                with edit_lock:
                    self.document('{"disconnected":true}', 'application/json', pairing.logout(self.headers))
                    self.editor_access()
            elif self.path == '/wifi/editor':
                try:
                    data = self.small_json()
                    if not isinstance(data, dict) or not isinstance(data.get('resume', ''), str):
                        raise ValueError('Invalid editor request.')
                    with edit_lock:
                        access = self.editor_access()
                        resume = (owner['session'] == pairing.session_id(self.headers)
                                  and bool(owner['token'])
                                  and hmac.compare_digest(owner['token'].encode(), data.get('resume', '').encode()))
                        if not access['occupied'] or resume or data.get('takeover') is True:
                            owner.update(session=pairing.session_id(self.headers), token=secrets.token_urlsafe(32))
                            self.send_json({'editing': True, 'occupied': True, 'token': owner['token']})
                        else:
                            self.send_json({'editing': False, 'occupied': True})
                except (ValueError, TypeError):
                    self.send_json({'error': 'Invalid editor request.'}, 400)
            elif self.path == '/api/activate':
                try:
                    data = self.small_json()
                    if not isinstance(data, dict) or set(data) != {'output', 'request_id'} or not all(isinstance(v, str) for v in data.values()):
                        raise ValueError('Expected a selected output and request ID.')
                    self.send_json(controller.start(data['request_id'], data['output']), 202)
                except (ValueError, TypeError) as exc:
                    self.send_json({'error': str(exc)}, 400)
            else:
                with edit_lock:
                    if not self.editor_access()['editing']:
                        self.send_json({'error': 'This page is view-only. Take editing control to load the current kit before making changes.',
                                        'code': 'editor_read_only'}, 409)
                        return
                    super().do_POST()

    return Handler


def main():
    import sys
    if sys.version_info < (3, 10):
        raise SystemExit('Use Python 3.10 or newer; older macOS system Python is not supported.')
    import strike_remap as app
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', required=True, help='Specific private LAN IPv4 address')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--library-root', type=Path, help='Persistent host library folder')
    args = parser.parse_args()
    try:
        address = ipaddress.ip_address(args.bind)
    except ValueError:
        parser.error('Use a private LAN IPv4 address.')
    if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
        parser.error('Use a specific private LAN IPv4 address.')
    if args.library_root:
        app.set_library_root(args.library_root)
    pairing = Pairing(secrets.token_urlsafe(32), f'{address}:{args.port}')
    server = app._Server((str(address), args.port), make_handler(app, pairing))
    print('Strike full editor Wi-Fi mode. Use only on your trusted local network; do not port-forward.')
    print('Pairing grants full editor access, including library edits and deliberate Deploy actions.')
    print(f'http://{pairing.authority}/wifi/pair#pair={pairing.token}', flush=True)
    print('Files and USB stay on this host. One page controls editing; other pages open view-only.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
