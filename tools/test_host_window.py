"""Exercise real Tk controls with a disposable library; skip when Tk/display is absent."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch_editor
from strike_remapper.host import Host
import strike_remap as app

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:
    tk = None


class WindowTests(unittest.TestCase):
    def setUp(self):
        if tk is None:
            if os.environ.get('STRIKE_REQUIRE_TK') == '1':
                self.fail('Tk is required for this acceptance job')
            self.skipTest('Tk is not installed')
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get('STRIKE_REQUIRE_TK') == '1':
                self.fail(f'A graphical display is required: {exc}')
            self.skipTest(f'No graphical display: {exc}')
        # Real geometry and event processing without placing a window on the desktop.
        self.root.withdraw()
        self.root.attributes('-alpha', 0)
        self.tmp = tempfile.TemporaryDirectory()
        self.library = (Path(self.tmp.name) / 'library').resolve()
        self.config = Path(self.tmp.name) / 'StrikeRemapper/launcher.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'library': str(self.library), 'address':'127.0.0.1'}))
        self.host = Host()
        self.errors = []
        self.opened = []
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.close_window)
        self.addCleanup(self.host.stop)

    def close_window(self):
        for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(timer)
        self.root.destroy()

    def assert_controls_fit(self):
        self.root.update_idletasks()
        for widget in self.widgets():
            if widget.winfo_class() != 'TButton':
                continue
            right = widget.winfo_rootx() - self.root.winfo_rootx() + widget.winfo_reqwidth()
            bottom = widget.winfo_rooty() - self.root.winfo_rooty() + widget.winfo_reqheight()
            self.assertLessEqual(right, self.root.winfo_width(), widget.cget('text'))
            self.assertLessEqual(bottom, self.root.winfo_height(), widget.cget('text'))

    def widgets(self, parent=None):
        for child in (parent or self.root).winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, text):
        return next(w for w in self.widgets() if w.winfo_class() == 'TButton' and str(w.cget('text')) == text)

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Launcher action did not finish')

    def run_window(self, action):
        real_start = self.host.start
        def start(root, bind=None):
            return real_start(root, bind, port=0)
        def inspect(root):
            root.deiconify()
            root.update()
            action()
            self.assertFalse(self.callback_errors)
        with patch.dict(os.environ, {'APPDATA': self.tmp.name}), \
                patch.object(tk, 'Tk', return_value=self.root), \
                patch.object(tk.Misc, 'mainloop', inspect), \
                patch.object(launch_editor.webbrowser, 'open', side_effect=lambda url: self.opened.append(url) or True), \
                patch.object(launch_editor, 'Host', return_value=self.host), \
                patch.object(launch_editor, 'lan_addresses', return_value=['127.0.0.1']), \
                patch.object(self.host, 'start', side_effect=start), \
                patch.object(app, 'get_volumes', return_value=(None, None)), \
                patch.object(messagebox, 'showerror', side_effect=lambda *args: self.errors.append(args)):
            launch_editor.main()

    def test_start_stop_and_saved_library(self):
        def exercise():
            self.assert_controls_fit()
            self.button('Open editor').invoke()
            self.wait(lambda: self.host.running and not self.button('Stop').instate(['disabled']))
            self.assertFalse(self.host.pair_url, 'Wi-Fi must remain opt-in even with a saved address')
            self.assertEqual(self.host.library, self.library)
            self.assertEqual(self.opened, [self.host.url])
            self.button('Try a demo').invoke()
            self.assertEqual(self.opened[-1], self.host.url.rstrip('/') + '/midi?demo=1')
            self.assertFalse(self.button('Open editor').instate(['disabled']))
            conn = http.client.HTTPConnection('127.0.0.1', self.host.server.server_port, timeout=3)
            conn.request('GET', '/api/session')
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()
            app.create_new_kit('Window check')
            app.set_pad_param('S1H', 'la_level', 31)
            self.button('Stop').invoke()
            self.wait(lambda: not self.button('Open editor').instate(['disabled']))
            self.assertFalse(self.host.running)
            self.assertTrue((self.library / 'kits/Window check.autosave.skt').exists())
            self.assertEqual(json.loads(self.config.read_text())['library'], str(self.library))
            self.assertFalse(self.errors)
        self.run_window(exercise)

    def test_final_save_failure_keeps_retry_controls_available(self):
        def exercise():
            self.button('Open editor').invoke()
            self.wait(lambda: self.host.running and not self.button('Stop').instate(['disabled']))
            app.create_new_kit('Retry check')
            app.set_pad_param('S1H', 'la_level', 45)
            def failed_close():
                self.host.recovery.stop_event.set()
                self.host.recovery.thread.join()
                raise OSError('Disk full')
            with patch.object(self.host.recovery, 'close', side_effect=failed_close):
                self.button('Stop').invoke()
                self.wait(lambda: bool(self.errors))
                self.root.tk.call(self.root.protocol('WM_DELETE_WINDOW'))
                self.wait(lambda: len(self.errors) == 2)
                self.assertTrue(self.root.winfo_exists())
            self.assertFalse(self.host.running)
            self.assertTrue(self.host.recovery_pending)
            self.assertTrue(self.button('Open editor').instate(['disabled']))
            self.assertFalse(self.button('Retry recovery save').instate(['disabled']))
            self.root.geometry('600x440')
            self.root.update()
            self.assert_controls_fit()
            self.assertIn('Keep this window', ' '.join(w.cget('text') for w in self.widgets() if w.winfo_class() == 'TLabel'))
            self.button('Retry recovery save').invoke()
            self.wait(lambda: not self.button('Open editor').instate(['disabled']))
            self.assertFalse(self.host.recovery_pending)
            self.assertTrue((self.library / 'kits/Retry check.autosave.skt').exists())
        self.run_window(exercise)

    def test_wifi_pairing_and_short_window_scrolling(self):
        def exercise():
            self.root.geometry('600x440')
            self.root.update()
            next(w for w in self.widgets() if w.winfo_class() == 'TCheckbutton').invoke()
            self.button('Open editor').invoke()
            self.wait(lambda: self.host.running and not self.button('Stop').instate(['disabled']))
            self.assertIn('/wifi/pair#pair=', self.host.pair_url)
            self.button('Try a demo').invoke()
            self.assertEqual(self.opened[-1], self.host.pair_url + '&view=demo')
            self.assert_controls_fit()
            canvases = [w for w in self.widgets() if w.winfo_class() == 'Canvas']
            viewport = next(w for w in canvases if w.cget('yscrollcommand'))
            qr = next(w for w in canvases if w is not viewport)
            self.assertGreater(len(qr.find_all()), 100)
            self.assertLess(viewport.yview()[1], 1)
            viewport.yview_moveto(1)
            self.root.update()
            self.assertGreater(viewport.yview()[0], 0)
            # Tabbing back to the library field reveals it after scrolling down.
            entry = next(w for w in self.widgets() if w.winfo_class() == 'TEntry')
            entry.event_generate('<FocusIn>')
            self.root.update()
            self.assertGreaterEqual(entry.winfo_rooty(), viewport.winfo_rooty())
            self.button('Stop').invoke()
            self.wait(lambda: not self.button('Open editor').instate(['disabled']))
            self.assertFalse(self.errors)
        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
