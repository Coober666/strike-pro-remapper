"""Simulator selection contracts; no Xcode or device access."""
import json
import io
import unittest
import subprocess
from pathlib import Path
import tempfile
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


class SourceReceiptTests(unittest.TestCase):
    def test_hashes_sources_in_build_parent_but_excludes_generated_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / '.build' / 'checkout'
            source = root / 'native/StrikeCompanion/Sources/Setlist.swift'
            source.parent.mkdir(parents=True)
            source.write_text('shared source')
            mobile = root / 'native/StrikeCompanioniOS/Sources/App.swift'
            mobile.parent.mkdir(parents=True)
            mobile.write_text('mobile source')
            script = root / 'tools/build_ios_companion.py'
            script.parent.mkdir(parents=True)
            script.write_text('build helper')
            for child in ('.build', '.swiftpm', 'xcuserdata'):
                generated = root / 'native/StrikeCompanioniOS' / child / 'generated.swift'
                generated.parent.mkdir(parents=True)
                generated.write_text('generated')
            with patch.object(build_ios_companion, '__file__', str(script)):
                before = build_ios_companion.source_hashes(root)
                self.assertEqual(set(before), {
                    'native/StrikeCompanion/Sources/Setlist.swift',
                    'native/StrikeCompanioniOS/Sources/App.swift', 'tools/build_ios_companion.py'})
                source.write_text('changed source')
                self.assertNotEqual(before, build_ios_companion.source_hashes(root))


class FailureSummaryTests(unittest.TestCase):
    def test_extracts_failure_reasons_from_anywhere_in_the_log(self):
        reason = ("/tmp/UITests/CompanionUITests.swift:154: error: -[CompanionUITests.CompanionUITests "
                  "testColdLaunchRestoresSongAndReadingPreferences] : XCTAssertTrue failed")
        text = '\n'.join([
            "Test Case '-[CompanionUITests.CompanionUITests testAdaptiveLayoutAndScrollReset]' passed (12.0 seconds).",
            '    t =     3.10s Tap "next" Button',
            '    ' + reason,
            "Test Case '-[CompanionUITests.CompanionUITests testColdLaunchRestoresSongAndReadingPreferences]' failed (31.2 seconds).",
            *['    t =     1.00s Find the "midi-count" StaticText'] * 500,
            '    ' + reason,
            "Test Case '-[CompanionUITests.CompanionUITests testFilePickerCancellationPreservesSong]' exceeded execution time allowance of 5 minutes.",
            'Failing tests:'])
        self.assertEqual(build_ios_companion.failure_summary(text), [
            reason,
            "Test Case '-[CompanionUITests.CompanionUITests testColdLaunchRestoresSongAndReadingPreferences]' failed (31.2 seconds).",
            "Test Case '-[CompanionUITests.CompanionUITests testFilePickerCancellationPreservesSong]' exceeded execution time allowance of 5 minutes."])

    def test_passing_log_has_no_diagnostics_and_output_is_bounded(self):
        self.assertEqual(build_ios_companion.failure_summary(
            "Test Case '-[A b]' passed (1.0 seconds).\n** TEST SUCCEEDED **"), [])
        many = '\n'.join(f"Test Case '-[A test{index}]' failed (1.0 seconds)." for index in range(300))
        self.assertEqual(len(build_ios_companion.failure_summary(many)), 100)


if __name__ == '__main__':
    unittest.main()
