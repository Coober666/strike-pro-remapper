"""Build/test the iPhone/iPad companion with installed Xcode simulators only.

No downloads, signing setup, physical devices, library reads or publication.
Supply installed simulator UUIDs with --device (repeat for iPhone and iPad).
Without --device, choose an iPhone/iPad pair from the newest installed iOS runtime
supported by the selected Xcode simulator SDK. Never mix runtime versions.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


TEST_SESSIONS = (('models', 'CompanionTests'), ('ui', 'CompanionUITests'))


def validate_test_targets(root):
    """Never silently omit a test target when splitting the test sessions."""
    scheme = root / 'native/StrikeCompanioniOS/StrikeCompanion.xcodeproj/xcshareddata/xcschemes/StrikeCompanion.xcscheme'
    references = ET.parse(scheme).findall('./TestAction/Testables/TestableReference')
    names = [item.get('BlueprintName', '') for reference in references
             if (item := reference.find('BuildableReference')) is not None]
    expected = sorted(target for _, target in TEST_SESSIONS)
    if len(names) != len(references) or sorted(names) != expected or any(item.get('skipped', 'NO') != 'NO' for item in references):
        raise ValueError('Every scheme test target must have an enabled session; update the session plan for changed targets.')


def test_steps(root, device, output, index):
    """Build once, then give hosted model tests and UI tests separate sessions."""
    common = ['-project', str(root / 'native/StrikeCompanioniOS/StrikeCompanion.xcodeproj'),
              '-scheme', 'StrikeCompanion', '-destination', f'platform=iOS Simulator,id={device}',
              '-derivedDataPath', str(output / 'DerivedData')]
    limits = ['-parallel-testing-enabled', 'NO', '-test-timeouts-enabled', 'YES',
              '-collect-test-diagnostics', 'never', '-default-test-execution-time-allowance', '180',
              '-maximum-test-execution-time-allowance', '300']
    steps = [('build', ['xcodebuild', 'build-for-testing', *common, 'CODE_SIGNING_ALLOWED=NO'], None)]
    for phase, target in TEST_SESSIONS:
        result = output / f'simulator-{index}-{phase}.xcresult'
        command = ['xcodebuild', 'test-without-building', *common, *limits,
                   f'-only-testing:{target}', '-resultBundlePath', str(result), 'CODE_SIGNING_ALLOWED=NO']
        steps.append((phase, command, result.name))
    return steps


def simulator_inventory():
    return json.loads(subprocess.check_output(
        ['xcrun', 'simctl', 'list', 'devices', 'available', '--json'], text=True))


def simulator_ids():
    inventory = simulator_inventory()
    sdk = tuple(map(int, subprocess.check_output(
        ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], text=True).strip().split('.')))
    sdk = (sdk + (0, 0, 0))[:3]
    runtimes = []
    for identifier, devices in inventory['devices'].items():
        prefix = 'com.apple.CoreSimulator.SimRuntime.iOS-'
        if identifier.startswith(prefix):
            version = tuple(map(int, identifier.removeprefix(prefix).split('-')))
            version = (version + (0, 0, 0))[:3]
            if version <= sdk:
                runtimes.append((version, devices))
    for _, devices in sorted(runtimes, key=lambda item: item[0], reverse=True):
        chosen = [next((item['udid'] for item in devices
                        if item.get('isAvailable', False) and item['name'].startswith(family)), None)
                  for family in ('iPhone', 'iPad')]
        if all(chosen):
            return chosen
    raise ValueError('No installed iOS runtime compatible with this Xcode SDK has both an iPhone and iPad simulator. Install one in Xcode first.')


@contextmanager
def ready_simulator(device, stream, already_booted):
    """Wait for startup and release only a simulator this run needed to boot."""
    try:
        subprocess.run(['xcrun', 'simctl', 'bootstatus', device, '-b'], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=300)
        yield
    finally:
        if not already_booted:
            try:
                result = subprocess.run(['xcrun', 'simctl', 'shutdown', device], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=60)
                if result.returncode:
                    print(f'Could not shut down test simulator {device}; see its log.', file=sys.stderr)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'Could not shut down test simulator {device}: {error}', file=sys.stderr)


def source_hashes(root):
    inputs = [path for folder in ('native/StrikeCompanion', 'native/StrikeCompanioniOS')
              for path in (root / folder).rglob('*')
              if path.is_file() and not any(part in ('.build', '.swiftpm', 'xcuserdata') for part in path.relative_to(root / folder).parts)]
    inputs.append(Path(__file__).resolve())
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(inputs)}


# xcodebuild prints the reason for each failed test far from the end of its log.
FAILURE_MARKERS = (': error:', "' failed (", 'Assertion Failure:',
                   'exceeded execution time allowance', 'Restarting after unexpected exit')


def failure_summary(text, limit=100):
    """Return the failing-test diagnostic lines of an xcodebuild log, in order and deduplicated."""
    lines = []
    for line in text.splitlines():
        line = line.strip()[:2000]
        if any(marker in line for marker in FAILURE_MARKERS) and line not in lines:
            lines.append(line)
            if len(lines) == limit:
                break
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New directory; never overwrites')
    parser.add_argument('--device', action='append', help='Installed simulator UUID; repeat to test more devices')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use macOS with full Xcode and installed iOS simulators.')
    root = Path(__file__).resolve().parent.parent
    validate_test_targets(root)
    devices = args.device or simulator_ids()
    booted = {item['udid'] for group in simulator_inventory()['devices'].values()
              for item in group if item['state'] == 'Booted'}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = subprocess.check_output(['xcodebuild', '-version'], text=True).strip()
    hashes = source_hashes(root)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    runs = []
    for index, device in enumerate(devices, 1):
        log = output / f'simulator-{index}.log'
        run = {'device': device, 'exit_code': None, 'completed': False,
               'log': log.name, 'phase': 'startup', 'phases': []}
        runs.append(run)
        print(f'Testing simulator {device}; log: {log}', flush=True)
        try:
            with log.open('w') as stream, ready_simulator(device, stream, device in booted):
                for phase, command, result in test_steps(root, device, output, index):
                    run['phase'] = phase
                    print(f'Simulator {device}: {phase}', flush=True)
                    print(f'\n=== {phase}: {json.dumps(command)} ===', file=stream, flush=True)
                    completed = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
                    run['exit_code'] = completed.returncode
                    run['phases'].append({'phase': phase, 'exit_code': completed.returncode,
                                          'result': result, 'command': command})
                    if hashes != source_hashes(root):
                        raise ValueError('Build inputs changed during testing; no subsequent session was started.')
                    if completed.returncode:
                        break
            run['completed'] = len(run['phases']) == len(TEST_SESSIONS) + 1 and run['exit_code'] == 0
        except BaseException as error:
            run['error_type'] = type(error).__name__
            raise
        finally:
            unchanged = hashes == source_hashes(root)
            receipt = {'version': 2, 'xcode': version, 'base_revision': revision, 'source_sha256': hashes,
                       'inputs_unchanged': unchanged,
                       'test_targets': [target for _, target in TEST_SESSIONS], 'runs': runs,
                       'scope': 'Synthetic simulator tests; physical devices and VoiceOver not accepted.'}
            (output / 'test-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if not unchanged:
            raise ValueError('Build inputs changed during testing; retain these logs and run again on stable inputs.')
        if run['exit_code']:
            text = log.read_text()
            print(text[-10000:], file=sys.stderr)
            summary = failure_summary(text)
            print(f'Failure diagnostics from {log.name}:', file=sys.stderr)
            print('\n'.join(summary) if summary else 'No test failure lines found; see the log and xcresult.', file=sys.stderr)
            raise SystemExit(run['exit_code'])
    print(f'Passed {len(runs)} simulator runs. Evidence: {output}', flush=True)


if __name__ == '__main__':
    main()
