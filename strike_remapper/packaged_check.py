"""Explicit release smoke check using a new disposable library and no cards."""
import http.client
import json
from pathlib import Path
from unittest.mock import patch


def check_launcher(root):
    """Drive the actual windowed executable without opening a browser or device."""
    import os
    import time
    import tkinter as tk
    from tkinter import messagebox
    import launch_editor
    import strike_remap as app
    from strike_remapper.host import Host
    root.mkdir()
    library = root / 'library'
    config = root / 'StrikeRemapper'
    config.mkdir()
    (config / 'launcher.json').write_text(json.dumps({'library': str(library)}), encoding='utf-8')
    window = tk.Tk()
    window.withdraw()
    host = Host()
    opened = []
    errors = []
    real_start = host.start

    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)

    def button(label):
        return next(w for w in widgets(window) if w.winfo_class() == 'TButton' and str(w.cget('text')) == label)

    def wait(predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            window.update()
            if errors:
                raise RuntimeError(str(errors))
            if predicate():
                return
            time.sleep(.01)
        raise RuntimeError('Launcher did not finish its action')

    def exercise(_window):
        button('Try a demo').invoke()
        wait(lambda: bool(opened))
        if opened != [host.url.rstrip('/') + '/midi?demo=1']:
            raise RuntimeError('Launcher demo URL failed')
        button('Open editor').invoke()
        if opened[-1] != host.url:
            raise RuntimeError('Launcher editor URL failed')
        app.create_new_kit('Launcher check')
        app.set_pad_param('S1H', 'la_level', 33)
        button('Stop').invoke()
        wait(lambda: not host.running and not button('Open editor').instate(['disabled']))
        if not (library / 'kits/Launcher check.autosave.skt').is_file():
            raise RuntimeError('Launcher recovery missing')

    try:
        with patch.dict(os.environ, {'APPDATA': str(root)}), \
                patch.object(tk, 'Tk', return_value=window), \
                patch.object(tk.Misc, 'mainloop', exercise), \
                patch.object(launch_editor, 'Host', return_value=host), \
                patch.object(launch_editor, 'lan_addresses', return_value=[]), \
                patch.object(launch_editor.webbrowser, 'open', side_effect=lambda url: opened.append(url) or True), \
                patch.object(host, 'start', side_effect=lambda path, bind=None: real_start(path, bind, port=0)), \
                patch.object(app, 'get_volumes', return_value=(None, None)), \
                patch.object(app, '_find_strike_volumes', return_value={}), \
                patch.object(messagebox, 'showerror', side_effect=lambda *args: errors.append(args)):
            window.report_callback_exception = lambda *args: errors.append(str(args))
            launch_editor.main()
    finally:
        host.stop()
        for timer in window.tk.splitlist(window.tk.call('after', 'info')):
            window.after_cancel(timer)
        window.destroy()
    return {'launcher': True, 'demo': True, 'recovery': True}


def check(root):
    import strike_remap as app
    from strike_remapper.host import Host
    from strike_remapper.midi_input import NativeInput
    from strike_remapper.factory_bridge import native_midi
    from strike_remapper.support import identity
    root = root.resolve()
    root.mkdir()  # Refuse an existing library, even for an explicitly invoked check.
    host = Host()
    with patch.object(app, 'get_volumes', return_value=(None, None)), \
            patch.object(app, '_find_strike_volumes', return_value={}):
        try:
            host.start(root, port=0)
            assets = {}
            for path in ('/', '/midi', '/midi/app.js', '/midi/core.js',
                         '/api/session', '/api/support_report'):
                connection = http.client.HTTPConnection('127.0.0.1', host.server.server_port, timeout=5)
                connection.request('GET', path)
                response = connection.getresponse()
                body = response.read()
                connection.close()
                if response.status != 200 or not body:
                    raise RuntimeError('Packaged asset failed: ' + path)
                assets[path] = len(body)
            if not app._factory_catalog():
                raise RuntimeError('Factory metadata missing')
            import io
            import wave
            import zipfile
            sample, bundle = io.BytesIO(), io.BytesIO()
            with wave.open(sample, 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0' * 32)
            with zipfile.ZipFile(bundle, 'w') as archive:
                archive.writestr('Samples/Package/check.wav', sample.getvalue())
                archive.writestr('Instruments/Package/check.sin', app._build_sin([('Package/check.wav', 1, 127, 1)]))
            with app.STATE_LOCK:
                imported = app.import_bundle(bundle.getvalue())
                repeated = app.import_bundle(bundle.getvalue())
            if imported['samples'] != 1 or imported['instruments'] != 1 or repeated['skipped'] != 2:
                raise RuntimeError('Bundled ZIP import/repeat failed')
            app.create_new_kit('Packaged check')
            app.assign_instrument('S1H', 'a', 'Package/check.sin')
            app.set_pad_param('S1H', 'la_level', 31)
            saved = root / 'kits/Packaged check.skt'
            app.save_kit(str(saved))
            if not saved.is_file():
                raise RuntimeError('External library save failed')
            inspection = app.hex_inspect_pad('S1H')
            if not inspection.strip() or 'Traceback' in inspection:
                raise RuntimeError('Bundled utility failed: ' + inspection)
            app.set_pad_param('S1H', 'la_level', 32)
            connection = http.client.HTTPConnection('127.0.0.1', host.server.server_port, timeout=5)
            connection.request('GET', '/api/export_bundle')
            response = connection.getresponse()
            exported = response.read(); connection.close()
            if response.status != 200 or response.getheader('X-Strike-Missing-Assets') != '0':
                raise RuntimeError('Packaged bundle export failed')
            with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                expected = app.build_skt(app.state['kit_raw'], app.state['pads'], app.state['instruments'], app.state['tail'])
                if archive.testzip() is not None or archive.read('kit/Packaged check.skt') != expected or archive.read('samples/Package/check.wav') != sample.getvalue():
                    raise RuntimeError('Packaged bundle lost unsaved edits or sample bytes')
            inputs = NativeInput().inputs()  # Enumerates only; never opens any port.
            outputs = native_midi()['outputs']  # No selected output: no send.
        finally:
            host.stop()
        if not (root / 'kits/Packaged check.autosave.skt').is_file():
            raise RuntimeError('Recovery save missing')
        from urllib.parse import urlparse, parse_qs
        try:
            host.start(root, bind='127.0.0.1', port=0)
            url = urlparse(host.pair_url)
            token = parse_qs(url.fragment)['pair'][0]
            connection = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
            connection.request('POST', '/wifi/pair', json.dumps({'token': token}),
                               {'Content-Type': 'application/json', 'Origin': 'http://' + url.netloc})
            response = connection.getresponse()
            response.read()
            if response.status != 200:
                raise RuntimeError('Packaged pairing failed')
            cookie = response.getheader('Set-Cookie').split(';')[0]
            for path in ('/wifi/pair.js', '/wifi/pair.css', '/midi/host.js', '/midi/profile-ui.js', '/midi/styles.css'):
                connection.request('GET', path, headers={'Cookie': cookie})
                response = connection.getresponse()
                if response.status != 200 or not response.read():
                    raise RuntimeError('Paired asset failed: ' + path)
            connection.close()
        finally:
            host.stop()
    return {'paired': True, 'factory_outputs': len(outputs), 'assets': assets, 'saved': True, 'recovery': True, 'utility': True, 'bundle_import': True, 'bundle_export': True,
            'midi_inputs': len(inputs), 'identity': identity(Path(app.__file__).parent)}
