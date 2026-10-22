"""Simulator selection contracts; no Xcode or device access."""
import json
import io
import unittest
import subprocess
from pathlib import Path
import tempfile
from contextlib import redirect_stderr, redirect_stdout
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


class TestSessionTests(unittest.TestCase):
    def exercise(self, failing_phase=None, change_source=False, fail_boot=False):
        """Exercise actual orchestration/receipts with injected Xcode and boot failures."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'source with spaces'
            helper = root / 'tools/build_ios_companion.py'
            helper.parent.mkdir(parents=True)
            helper.write_text('# disposable helper input')
            source = root / 'native/StrikeCompanioniOS/Sources/App.swift'
            source.parent.mkdir(parents=True)
            source.write_text('original source')
            scheme = root / 'native/StrikeCompanioniOS/StrikeCompanion.xcodeproj/xcshareddata/xcschemes/StrikeCompanion.xcscheme'
            scheme.parent.mkdir(parents=True)
            scheme.write_text('<Scheme><TestAction><Testables>' + ''.join(
                f'<TestableReference skipped="NO"><BuildableReference BlueprintName="{name}"/></TestableReference>'
                for name in ('CompanionTests', 'CompanionUITests')) + '</Testables></TestAction></Scheme>')
            output = root / 'output'
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if command[:3] == ['xcrun', 'simctl', 'bootstatus'] and fail_boot:
                    raise subprocess.TimeoutExpired(command, 300)
                phase = None
                if command[0] == 'xcodebuild':
                    phase = 'build' if command[1] == 'build-for-testing' else (
                        'models' if '-only-testing:CompanionTests' in command else 'ui')
                    if phase == 'models' and change_source:
                        source.write_text('changed during test')
                return subprocess.CompletedProcess(command, 65 if phase == failing_phase and phase else 0)

            error = None
            with patch.object(build_ios_companion, '__file__', str(helper)), \
                    patch.object(build_ios_companion.sys, 'platform', 'darwin'), \
                    patch.object(build_ios_companion.sys, 'argv', ['build_ios_companion.py', '--output', str(output), '--device', 'fake-device']), \
                    patch.object(build_ios_companion, 'simulator_inventory', return_value={'devices': {'runtime': []}}), \
                    patch('build_ios_companion.subprocess.check_output', side_effect=['Xcode test', 'a' * 40]), \
                    patch('build_ios_companion.subprocess.run', side_effect=run), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    build_ios_companion.main()
                except (ValueError, SystemExit, subprocess.TimeoutExpired) as caught:
                    error = caught
            receipt = json.loads((output / 'test-receipt.json').read_text())
            return receipt, calls, error

    def test_all_targets_run_in_separate_sessions_without_rebuild_or_retry(self):
        receipt, calls, error = self.exercise()
        self.assertIsNone(error)
        commands = [command for command in calls if command[0] == 'xcodebuild']
        self.assertEqual([command[1] for command in commands],
                         ['build-for-testing', 'test-without-building', 'test-without-building'])
        self.assertEqual([[arg for arg in command if arg.startswith('-only-testing:')] for command in commands],
                         [[], ['-only-testing:CompanionTests'], ['-only-testing:CompanionUITests']])
        for command in commands[1:]:
            self.assertEqual(command[command.index('-default-test-execution-time-allowance') + 1], '180')
            self.assertEqual(command[command.index('-maximum-test-execution-time-allowance') + 1], '300')
            self.assertEqual(command[command.index('-parallel-testing-enabled') + 1], 'NO')
            self.assertNotIn('-retry-tests-on-failure', command)
            self.assertNotIn('-test-iterations', command)
        phases = receipt['runs'][0]['phases']
        self.assertNotEqual(phases[1]['result'], phases[2]['result'])
        self.assertTrue(receipt['inputs_unchanged'])
        self.assertTrue(receipt['runs'][0]['completed'])

    def test_phase_failure_is_retained_and_prevents_later_sessions(self):
        for phase, expected in [('build', ['build']), ('models', ['build', 'models']), ('ui', ['build', 'models', 'ui'])]:
            with self.subTest(phase=phase):
                receipt, calls, error = self.exercise(failing_phase=phase)
                self.assertIsInstance(error, SystemExit)
                self.assertEqual(error.code, 65)
                run = receipt['runs'][0]
                self.assertEqual([step['phase'] for step in run['phases']], expected)
                self.assertEqual(run['exit_code'], 65)
                self.assertFalse(run['completed'])
                self.assertTrue(receipt['inputs_unchanged'])
                self.assertEqual(calls[-1], ['xcrun', 'simctl', 'shutdown', 'fake-device'])

    def test_boot_failure_still_retains_source_receipt_and_owned_cleanup(self):
        receipt, calls, error = self.exercise(fail_boot=True)
        self.assertIsInstance(error, subprocess.TimeoutExpired)
        run = receipt['runs'][0]
        self.assertEqual(run['error_type'], 'TimeoutExpired')
        self.assertEqual(run['phase'], 'startup')
        self.assertEqual(run['phases'], [])
        self.assertFalse(run['completed'])
        self.assertEqual(calls[-1], ['xcrun', 'simctl', 'shutdown', 'fake-device'])

    def test_source_change_blocks_next_session_and_marks_incomplete(self):
        receipt, calls, error = self.exercise(change_source=True)
        self.assertIsInstance(error, ValueError)
        self.assertFalse(receipt['inputs_unchanged'])
        self.assertFalse(receipt['runs'][0]['completed'])
        self.assertFalse(any('-only-testing:CompanionUITests' in command for command in calls))

    def test_changed_or_disabled_scheme_targets_cannot_silently_lose_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheme = root / 'native/StrikeCompanioniOS/StrikeCompanion.xcodeproj/xcshareddata/xcschemes/StrikeCompanion.xcscheme'
            scheme.parent.mkdir(parents=True)
            for targets in [[], [('CompanionTests', 'NO')],
                            [('CompanionTests', 'NO'), ('CompanionUITests', 'YES')],
                            [('CompanionTests', 'NO'), ('CompanionUITests', 'NO'), ('NewTests', 'NO')]]:
                scheme.write_text('<Scheme><TestAction><Testables>' + ''.join(
                    f'<TestableReference skipped="{skip}"><BuildableReference BlueprintName="{name}"/></TestableReference>'
                    for name, skip in targets) + '</Testables></TestAction></Scheme>')
                with self.assertRaisesRegex(ValueError, 'Every scheme test target'):
                    build_ios_companion.validate_test_targets(root)


class FailureSummaryTests(unittest.TestCase):
    def test_build_errors_survive_when_the_log_tail_only_names_failed_commands(self):
        reason = '/tmp/CompanionUITests.swift:28:22: error: main actor-isolated property cannot be referenced'
        self.assertEqual(build_ios_companion.failure_summary('\n'.join([
            reason, *['SwiftCompile normal arm64 other.swift'] * 500,
            '** TEST BUILD FAILED **'])), [reason])

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
