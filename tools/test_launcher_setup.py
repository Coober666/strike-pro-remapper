"""First-run failures should give an action instead of a Python traceback."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launch_editor


class LauncherSetupTests(unittest.TestCase):
    def test_missing_tk_explains_non_graphical_alternative(self):
        with patch.dict(sys.modules, {'tkinter': None}):
            with self.assertRaisesRegex(SystemExit, 'without Tk'):
                launch_editor.main()

    def test_missing_display_explains_desktop_or_terminal_options(self):
        class DisplayError(Exception):
            pass
        def unavailable():
            raise DisplayError('No display')
        fake = SimpleNamespace(Tk=unavailable, TclError=DisplayError,
                               filedialog=None, messagebox=None, ttk=None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'APPDATA': tmp}), \
                patch.dict(sys.modules, {'tkinter': fake}):
            with self.assertRaisesRegex(SystemExit, 'desktop session'):
                launch_editor.main()
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
