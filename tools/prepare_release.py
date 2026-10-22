"""Prepare unchanged CI packages for a beta release. Never creates/publishes a release."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

REPO = 'Coober666/strike-pro-remapper'
JOBS = {'test (ubuntu-latest)', 'test (macos-latest)',
        'source-backup-windows (3.10)', 'source-backup-windows (3.11)',
        'browser', 'windows-host', 'source-beta', 'windows-beta'}


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True, encoding='utf-8')


def validate_run(run, jobs):
    if (run.get('repository', {}).get('full_name') != REPO or
            run.get('path') != '.github/workflows/ci.yml' or
            run.get('event') != 'push' or run.get('head_branch') != 'main' or
            run.get('status') != 'completed' or run.get('conclusion') != 'success' or
            not re.fullmatch(r'[0-9a-f]{40}', run.get('head_sha', ''))):
        raise ValueError('Select a successful completed main-branch push CI run from this repository.')
    for name in JOBS:
        matches = [j for j in jobs if j.get('name') == name]
        if len(matches) != 1 or matches[0].get('conclusion') != 'success':
            raise ValueError('Required job did not pass: ' + name)
    return run['head_sha']


def verify_package(path, revision, kind):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.with_suffix('.sha256.txt').read_text().strip() != digest + '  ' + path.name:
        raise ValueError('Package checksum mismatch: ' + path.name)
    prefix, manifest_name = (('Strike Remapper/', 'PACKAGE-MANIFEST.json') if kind == 'windows'
                             else ('strike-remapper-beta/', 'BETA-MANIFEST.json'))
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len({n.casefold() for n in names}) != len(names):
            raise ValueError('Duplicate archive entries')
        for info in archive.infolist():
            relative = info.filename.removeprefix(prefix)
            if (not info.filename.startswith(prefix) or not relative or '\\' in relative or
                    ':' in relative or '..' in PurePosixPath(relative).parts or
                    relative.startswith('/') or info.is_dir() or
                    (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe archive entry')
        manifest = json.loads(archive.read(prefix + manifest_name))
        if (manifest.get('format') != 'strike-' + kind + '-beta' or manifest.get('version') != 1 or
                manifest.get('revision') != revision or manifest.get('workingTreeChanged') is not False):
            raise ValueError('Package identity mismatch')
        files = manifest['files']
        if set(names) != {prefix + n for n in files} | {prefix + manifest_name}:
            raise ValueError('Package manifest inventory mismatch')
        for name, expected in files.items():
            with archive.open(prefix + name) as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise ValueError('Payload checksum mismatch: ' + name)
    return digest


def prepare(source, windows, revision, tag, run_id, output):
    if not re.fullmatch(r'beta-[0-9]{8}\.[1-9][0-9]*', tag):
        raise ValueError('Use a beta tag such as beta-20261014.1.')
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not str(run_id).isdigit():
        raise ValueError('Invalid build identity')
    # Verify both before creating any deliverables. Never rebuild or modify ZIP bytes.
    packages = [('source', source), ('windows', windows)]
    checks = [(kind, path, verify_package(path, revision, kind)) for kind, path in packages]
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for kind, path, digest in checks:
        name = f'Strike-Remapper-{tag}-' + ('Windows-x64.zip' if kind == 'windows' else 'Mac-Linux-Source.zip')
        shutil.copyfile(path, output / name)
        records.append({'file': name, 'sha256': digest, 'original': path.name})
    (output / 'SHA256SUMS.txt').write_text(''.join(r['sha256'] + '  ' + r['file'] + '\n' for r in records), encoding='utf-8')
    evidence = {'tag': tag, 'revision': revision, 'run_id': int(run_id), 'packages': records}
    (output / 'BUILD.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    (output / 'START-HERE.txt').write_text(f'''Strike Remapper {tag}

Windows 64-bit: download the Windows-x64 ZIP, extract the whole folder,
then open Strike Remapper.exe. Python is bundled. Read START-HERE.txt inside.

Mac / Linux: download Mac-Linux-Source.zip and extract the whole folder.
Python 3.10+ is required; the optional host window needs Tk.
Mac: open launch-host.command. Linux: run python3 launch_editor.py.
If Tk is unavailable, follow docs/HOST_LAUNCHER.md for the terminal host.

iPad / iPhone: connect to the editor running on your USB-connected computer
over Wi-Fi. Follow docs/WIFI_EDITOR.md in the source ZIP or Help in Windows.
This download is not an iOS app.

Choose a separate library folder. Begin with an empty library or a backup copy.
Open the editor, then Drum MIDI toolkit > Try a demo for a module-free first test.
Keep your original library and SD card backed up. Updates never replace libraries.
Read the included beta guide before connecting or deploying to a module.

Unsigned beta: OS security prompts are possible. This is not a signed installer.
Only open a download whose source you trust; no security bypass is required here.
Physical platform/module acceptance is still incomplete. See the included guides.

SHA256SUMS.txt covers both ZIPs; BUILD.json records their original CI names.
Windows: Get-FileHash .\\<download-name>.zip -Algorithm SHA256
Mac: shasum -a 256 <download-name>.zip
Linux: sha256sum <download-name>.zip
Compare the result with SHA256SUMS.txt before extracting.

Revision: {revision}
Verified CI: https://github.com/{REPO}/actions/runs/{run_id}
''', encoding='utf-8')
    (output / 'RELEASE-NOTES.md').write_text(f'''# Strike Remapper {tag}

Unsigned beta from revision `{revision}`. [Passing CI](https://github.com/{REPO}/actions/runs/{run_id}).

Download **Windows-x64.zip** for Windows with Python/Tk/MIDI bundled, or
**Mac-Linux-Source.zip** for Mac/Linux with Python 3.10+ installed. Extract the
whole ZIP and read **START-HERE.txt**. iPad/iPhone use the computer's Wi-Fi editor.
GitHub's automatically generated Source code archives are not these prepared packages.

The packages are unchanged from CI; names are shortened for download. Checksums
and exact build provenance are attached. Keep your library outside the app folder
and back it up before upgrading. Read the included guides for platform limitations.

## Maintainer review before publication

Replace this section with the changes since the previous beta and the exact
acceptance status for this revision. Review all attached files and test the
downloads. CI passing does not establish physical mobile, USB or listening acceptance.
This workflow creates a draft only; publication requires a separate decision.
''', encoding='utf-8')
    return evidence


def fetch(run_id, tag, output):
    if not str(run_id).isdigit():
        raise ValueError('CI run ID must be numeric')
    run = json.loads(gh('api', f'repos/{REPO}/actions/runs/{run_id}'))
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100'))
    revision = validate_run(run, [job for page in pages for job in page['jobs']])
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100'))
    artifacts = [a for page in pages for a in page['artifacts']]
    with tempfile.TemporaryDirectory(prefix='strike-release-') as directory:
        paths = {}
        for kind in ('source', 'windows'):
            name = f'strike-{kind}-beta-{revision}'
            matches = [a for a in artifacts if a['name'] == name and not a['expired']]
            if len(matches) != 1:
                raise ValueError('Expected exactly one unexpired CI artifact: ' + name)
            destination = Path(directory) / kind
            gh('run', 'download', str(run_id), '--repo', REPO, '--name', name, '--dir', str(destination))
            zips = list(destination.glob('*.zip'))
            if len(zips) != 1:
                raise ValueError('Expected one inner application ZIP')
            paths[kind] = zips[0]
        return prepare(paths['source'], paths['windows'], revision, tag, run_id, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(fetch(args.run_id, args.tag, args.output), indent=2))
