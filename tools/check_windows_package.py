"""Verify/extract a Windows ZIP and exercise its runtime with Python removed from PATH."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def check(archive):
    with tempfile.TemporaryDirectory(prefix='strike-package-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                (root / name).resolve().relative_to(root.resolve())
            bundle.extractall(root)
        folder = root / 'Strike Remapper'
        manifest = json.loads((folder / 'PACKAGE-MANIFEST.json').read_text('utf-8'))
        expected = manifest['files']
        actual = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in folder.rglob('*') if p.is_file() and p.name != 'PACKAGE-MANIFEST.json'}
        if actual != expected:
            raise ValueError('Package file hashes do not match')
        for guide in ('README.txt', 'Windows-start.txt', 'Host-and-recovery.txt',
                      'iPad-and-iPhone.txt', 'MIDI-toolkit.txt', 'Device-checks.txt'):
            if not (folder / 'Help' / guide).is_file():
                raise ValueError('Missing bundled help: ' + guide)
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(('PYTHON', 'TCL', 'TK', 'VIRTUAL_ENV'))}
        environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        environment['PYTHONNOUSERSITE'] = '1'
        helper = folder / '_internal/StrikeHelper.exe'
        results = {}
        for mode, args in (('probe', []), ('smoke', [str(root / 'disposable-library')])):
            result = subprocess.run([str(helper), mode, *args], env=environment, cwd=root,
                                    capture_output=True, text=True, encoding='utf-8', timeout=90,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(mode + ' failed: ' + result.stderr + result.stdout)
            results[mode] = json.loads(result.stdout)
        if not results['probe']['frozen'] or not Path(results['probe']['prefix']).is_relative_to(folder):
            raise ValueError('Runtime escaped the extracted application')
        if results['probe']['midi'] != '1.5.8':
            raise ValueError('Unexpected MIDI dependency')
        launcher_root = root / 'launcher-check'
        launched = subprocess.run([str(folder / 'Strike Remapper.exe'), '--check-launcher', str(launcher_root)],
                                  env=environment, cwd=root, timeout=45,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        if launched.returncode:
            error = launcher_root / 'error.txt'
            raise RuntimeError('Windowed launcher failed: ' + (error.read_text('utf-8') if error.exists() else str(launched.returncode)))
        results['gui'] = json.loads((launcher_root / 'result.json').read_text('utf-8'))
        # The application bundle must remain byte-for-byte unchanged by the check.
        after = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in folder.rglob('*') if p.is_file() and p.name != 'PACKAGE-MANIFEST.json'}
        if after != actual:
            raise ValueError('Application bundle changed during execution')
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    check(parser.parse_args().archive)
