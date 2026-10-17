"""Build/test the iPhone/iPad companion with installed Xcode simulators only.

No downloads, signing setup, physical devices, library reads or publication.
Supply installed simulator UUIDs with --device (repeat for iPhone and iPad).
Without --device, choose an iPhone/iPad pair from the newest installed iOS runtime
supported by the selected Xcode simulator SDK. Never mix runtime versions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def simulator_ids():
    inventory = json.loads(subprocess.check_output(
        ['xcrun', 'simctl', 'list', 'devices', 'available', '--json'], text=True))
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


def source_hashes(root):
    inputs = [path for folder in ('native/StrikeCompanion', 'native/StrikeCompanioniOS')
              for path in (root / folder).rglob('*')
              if path.is_file() and not any(part in ('.build', '.swiftpm', 'xcuserdata') for part in path.parts)]
    inputs.append(Path(__file__).resolve())
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(inputs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New directory; never overwrites')
    parser.add_argument('--device', action='append', help='Installed simulator UUID; repeat to test more devices')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use macOS with full Xcode and installed iOS simulators.')
    root = Path(__file__).resolve().parent.parent
    devices = args.device or simulator_ids()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = subprocess.check_output(['xcodebuild', '-version'], text=True).strip()
    hashes = source_hashes(root)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    runs = []
    for index, device in enumerate(devices, 1):
        log = output / f'simulator-{index}.log'
        result = output / f'simulator-{index}.xcresult'
        command = ['xcodebuild', 'test', '-project', str(root / 'native/StrikeCompanioniOS/StrikeCompanion.xcodeproj'),
                   '-scheme', 'StrikeCompanion', '-destination', f'platform=iOS Simulator,id={device}',
                   '-derivedDataPath', str(output / 'DerivedData'), '-resultBundlePath', str(result),
                   '-parallel-testing-enabled', 'NO', 'CODE_SIGNING_ALLOWED=NO']
        print(f'Testing simulator {device}; log: {log}', flush=True)
        with log.open('w') as stream:
            completed = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
        runs.append({'device': device, 'exit_code': completed.returncode, 'log': log.name, 'result': result.name})
        unchanged = hashes == source_hashes(root)
        receipt = {'xcode': version, 'base_revision': revision, 'source_sha256': hashes,
                   'inputs_unchanged': unchanged, 'runs': runs,
                   'scope': 'Synthetic simulator tests; physical devices and VoiceOver not accepted.'}
        (output / 'test-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if not unchanged:
            raise ValueError('Build inputs changed during testing; retain these logs and run again on stable inputs.')
        if completed.returncode:
            print(log.read_text()[-10000:], file=sys.stderr)
            raise SystemExit(completed.returncode)
    print(f'Passed {len(runs)} simulator runs. Evidence: {output}', flush=True)


if __name__ == '__main__':
    main()
