"""Desktop host lifecycle, independent of the optional Tk launcher UI."""
import ipaddress
from pathlib import Path
import secrets
import socket
import threading

import strike_remap as app
from strike_remapper.wifi_editor import Pairing, make_handler
from strike_remapper.vendor.qrcodegen import QrCode


def lan_addresses():
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return sorted({s for s in addresses if ipaddress.ip_address(s).is_private
                   and not ipaddress.ip_address(s).is_loopback})


def pairing_matrix(url):
    qr = QrCode.encode_text(url, QrCode.Ecc.MEDIUM)
    return [[qr.get_module(x, y) for x in range(qr.get_size())] for y in range(qr.get_size())]


class Host:
    def __init__(self):
        self.server = None
        self.thread = None
        self.recovery = None
        self.library = None
        self.url = ''
        self.pair_url = ''

    @property
    def running(self):
        return self.server is not None

    def start(self, library, bind=None, port=8765):
        if self.running:
            raise ValueError('The editor is already running. Stop it before changing settings.')
        address = ipaddress.ip_address(bind or '127.0.0.1')
        if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError('Choose a specific private IPv4 address from this computer.')
        root = Path(library).expanduser().resolve()
        if not str(library).strip():
            raise ValueError('Choose a library folder.')
        root.mkdir(parents=True, exist_ok=True)
        # Check writability before binding; do not overwrite any existing library files.
        probe = root / ('.write-check-' + secrets.token_hex(8))
        try:
            with probe.open('xb') as f:
                f.write(b'')
        finally:
            probe.unlink(missing_ok=True)
        pairing = Pairing(secrets.token_urlsafe(32), f'{address}:{port}') if bind else None
        handler = make_handler(app, pairing) if pairing else app.Handler
        server = app._Server((str(address), port), handler)
        if pairing:
            pairing.authority = f'{address}:{server.server_port}'
        try:
            if self.library != root:
                with app.STATE_LOCK:
                    app.set_library_root(root)
                    app.state.update(kit_path=None, kit_display='', kit_raw=None, pads=[],
                                     instruments=[], tail=b'', dirty=False, history=[], avail={},
                                     sin_backups={}, sel_pad=None, skt_lossless=True, message='')
            recovery = app.RecoveryWorker()
        except Exception:
            server.server_close()
            raise
        self.library = root
        self.server = server
        self.recovery = recovery
        self.url = f'http://{address}:{server.server_port}'
        self.pair_url = f'{self.url}/wifi/pair#pair={pairing.token}' if pairing else ''
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        return self.pair_url or self.url

    def stop(self):
        if not self.running:
            return
        # A failed initial flush leaves the service available so the user can save.
        self.recovery.flush()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = None
        self.url = self.pair_url = ''
        self.recovery.close()

    def diagnostics(self):
        return '\n'.join([
            'Strike Remapper host',
            f'Status: {"Running" if self.running else "Stopped"}',
            f'Address: {self.url or "—"}',
            f'Library: {self.library or "Not selected"}',
            f'Wi-Fi: {"Enabled" if self.pair_url else "Off"}',
            'Recovery: every 60 seconds while running, and on a normal stop.',
            'If iPad cannot connect: same Wi-Fi, host awake, allow local-network access, use http://.',
        ])
