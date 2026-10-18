"""Simulator selection contracts; no Xcode or device access."""
import json
import io
import unittest
import subprocess
from unittest.mock import patch

import build_ios_companion


def pair(label):
    return [{'name': family + ' test', 'udid': label + family, 'isAvailable': True}
            for family in ('iPhone', 'iPad')]


class SimulatorSelectionTests(unittest.TestCase):
    def select(self, groups, sdk):
        with patch('build_ios_companion.subprocess.check_output',
                   side_effect=[json.dumps({'devices': groups}), sdk]):
            return build_ios_companion.simulator_ids()

    def test_selects_newest_complete_runtime_supported_by_selected_sdk(self):
        groups = {f'com.apple.CoreSimulator.SimRuntime.iOS-{version}': pair(label)
                  for version, label in [('18-5', 'old'), ('26-2-0', 'current'), ('27-0', 'future')]}
        self.assertEqual(self.select(groups, '26.2\n'), ['currentiPhone', 'currentiPad'])
        self.assertEqual(self.select(groups, '18.5\n'), ['oldiPhone', 'oldiPad'])

    def test_does_not_mix_runtimes_or_choose_unavailable_devices(self):
        unavailable = pair('unavailable')
        unavailable[1]['isAvailable'] = False
        groups = {'com.apple.CoreSimulator.SimRuntime.iOS-27-1': pair('phone-only')[:1],
                  'com.apple.CoreSimulator.SimRuntime.iOS-27-0': unavailable,
                  'com.apple.CoreSimulator.SimRuntime.iOS-26-2': pair('complete'),
                  'com.apple.CoreSimulator.SimRuntime.tvOS-27-1': pair('wrong-platform')}
        self.assertEqual(self.select(groups, '27.1'), ['completeiPhone', 'completeiPad'])

    def test_missing_compatible_pair_fails_before_build(self):
        with self.assertRaisesRegex(ValueError, 'both an iPhone and iPad'):
            self.select({'com.apple.CoreSimulator.SimRuntime.iOS-27-0': pair('future')}, '26.2')


class SimulatorLifecycleTests(unittest.TestCase):
    def test_preserves_preexisting_booted_simulator_on_failure(self):
        with patch('build_ios_companion.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'test failed'):
                with build_ios_companion.ready_simulator('test-device', io.StringIO(), True):
                    raise RuntimeError('test failed')
        self.assertEqual(run.call_count, 1)

    def test_cleans_up_owned_simulator_even_if_startup_fails(self):
        with patch('build_ios_companion.subprocess.run', side_effect=[
                subprocess.TimeoutExpired('bootstatus', 300),
                subprocess.CompletedProcess('shutdown', 0)]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                with build_ios_companion.ready_simulator('test-device', io.StringIO(), False):
                    self.fail('Startup failure must prevent testing')
        self.assertEqual(run.call_args.args[0], ['xcrun', 'simctl', 'shutdown', 'test-device'])


if __name__ == '__main__':
    unittest.main()
