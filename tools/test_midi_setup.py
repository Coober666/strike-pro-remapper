"""Host diagnostics do not open inputs or install packages."""
import importlib.metadata
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.midi_setup import check_setup


class SetupTests(unittest.TestCase):
    def test_missing_package_does_not_touch_driver(self):
        def missing(_):
            raise importlib.metadata.PackageNotFoundError()
        result = check_setup(object(), missing)
        self.assertEqual(result['status'], 'missing')
        self.assertIsNone(result['package'])
        self.assertNotIn('executable', result)

    def test_installed_package_enumerates_without_opening(self):
        class InputOnly:
            def inputs(self):
                return [{'id': 'test', 'name': 'Test drums'}]
        result = check_setup(InputOnly(), lambda _: 'test-version')
        self.assertEqual(result['status'], 'ready')
        self.assertIn('does not prove', result['message'])
        self.assertEqual(len(result['inputs']), 1)

    def test_no_inputs_and_driver_error_are_distinct(self):
        class Empty:
            def inputs(self):
                return []
        class Broken:
            def inputs(self):
                raise RuntimeError('driver blocked')
        self.assertEqual(check_setup(Empty(), lambda _: '1')['status'], 'no-inputs')
        result = check_setup(Broken(), lambda _: '1')
        self.assertEqual(result['status'], 'driver-error')
        self.assertEqual(result['detail'], 'driver blocked')


if __name__ == '__main__':
    unittest.main()
