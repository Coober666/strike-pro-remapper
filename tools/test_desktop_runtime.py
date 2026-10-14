"""Source/frozen helper routing and external-library safety contracts."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper import runtime
from strike_remapper.desktop_worker import main


class RuntimeTests(unittest.TestCase):
    def test_source_helper_and_unknown_operation(self):
        self.assertEqual(runtime.worker_command('midi-input', 'selected'),
                         [sys.executable, '-m', 'strike_remapper.desktop_worker', 'midi-input', 'selected'])
        with patch.object(sys, 'argv', ['helper', 'arbitrary-module']):
            with self.assertRaises(ValueError):
                main()

    def test_frozen_paths_and_internal_library_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve() / 'app'
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, '_MEIPASS', str(folder / '_internal'), create=True), \
                    patch.object(sys, 'executable', str(folder / 'Strike Remapper.exe')):
                self.assertEqual(runtime.worker_command('midi-input'),
                                 [str(folder / '_internal/StrikeHelper.exe'), 'midi-input'])
                for root in (folder, folder / 'library', folder / '_internal/library'):
                    with self.assertRaises(ValueError):
                        runtime.validate_library(root)
                    self.assertFalse(root.exists())
                runtime.validate_library(Path(tmp).resolve() / 'external-library')

    def test_utility_allowlist_before_file_access(self):
        with patch.object(sys, 'argv', ['helper', 'utility', '.', '../other.py']):
            with self.assertRaises(ValueError):
                main()


if __name__ == '__main__':
    unittest.main()
