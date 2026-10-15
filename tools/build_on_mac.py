"""Build one committed Strike companion revision on a Mac over existing SSH.

Transfers only allowlisted Git source. Never syncs a working directory, credentials,
libraries or dependencies, and never changes an existing remote checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

INPUTS = ['native/StrikeCompanion', 'tools/build_macos_companion.py']
ARTIFACT = 'Strike-Companion-macOS-arm64.zip'
SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
PREPARE = '''set -eu
umask 077
mkdir -p "$HOME/Developer/Builds/strike-companion"
mkdir "$HOME/Developer/Builds/strike-companion/$1"
'''
BUILD = '''set -eu
umask 077
cd "$HOME/Developer/Builds/strike-companion/$1"
exec >build.log 2>&1
printf '%s  source.tar\n' "$3" | shasum -a 256 -c -
tar -xf source.tar
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
python3 tools/build_macos_companion.py --output artifacts --revision "$2"
'''


def valid_host(value):
    # One existing SSH-config alias/hostname. No options, user/port syntax or shell.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
        raise ValueError('Use an SSH hostname or configured alias, such as mac-mini.')
    return value


def verify_receipt(folder, revision):
    receipt = json.loads((folder / 'build-receipt.json').read_text(encoding='utf-8'))
    artifact = folder / ARTIFACT
    if (receipt.get('revision') != revision or receipt.get('artifact') != ARTIFACT
            or receipt.get('contracts') != 'passed' or receipt.get('architecture') != 'arm64'
            or receipt.get('bytes') != artifact.stat().st_size
            or receipt.get('sha256') != hashlib.sha256(artifact.read_bytes()).hexdigest()):
        raise ValueError('Artifact receipt/revision/checksum verification failed; do not use this build.')
    return receipt


def execute(args):
    host = valid_host(args.host)
    root = Path(__file__).resolve().parent.parent
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options',
                                        args.revision + '^{commit}'], cwd=root, text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Could not resolve a full Git commit.')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip():
        raise ValueError('Commit or isolate local changes first; only committed source is transferred.')
    tree = subprocess.check_output(['git', 'ls-tree', '-r', revision, '--', *INPUTS], cwd=root, text=True)
    if not tree or any(not line.startswith('100644 ') and not line.startswith('100755 ') for line in tree.splitlines()):
        raise ValueError('Companion build inputs must be ordinary committed files, without symlinks/submodules.')
    for required in ['tools/build_macos_companion.py', 'native/StrikeCompanion/Sources/StrikeCompanion.swift']:
        if not any(line.endswith('\t' + required) for line in tree.splitlines()):
            raise ValueError('Selected revision does not contain the companion build inputs.')
    run_id = revision[:12] + '-' + uuid.uuid4().hex[:12]
    folder = (args.output or root / 'dist/remote-mac' / run_id).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    archive = folder / 'source.tar'
    subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(archive), revision, '--', *INPUTS],
                   cwd=root, check=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    remote = 'Developer/Builds/strike-companion/' + run_id
    print(f'Building {revision} on {host}; remote directory ~/{remote}', flush=True)
    subprocess.run(['ssh', *SSH_OPTIONS, host, 'bash -s -- ' + run_id], input=PREPARE,
                   text=True, check=True, timeout=45)
    subprocess.run(['scp', *SSH_OPTIONS, str(archive), host + ':' + remote + '/source.tar'],
                   check=True, timeout=120)
    failure = None
    try:
        subprocess.run(['ssh', *SSH_OPTIONS, host, f'bash -s -- {run_id} {revision} {digest}'],
                       input=BUILD, text=True, check=True, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        failure = error
    # Always attempt log retrieval, including when compiler/tests fail.
    log_copy = subprocess.run(['scp', *SSH_OPTIONS, host + ':' + remote + '/build.log', str(folder / 'build.log')],
                              timeout=45)
    if failure:
        raise RuntimeError(f'Mac build failed; inspect {folder / "build.log"} or ~/{remote}/build.log. No retry or cleanup was performed.') from failure
    log_copy.check_returncode()
    for name in [ARTIFACT, 'build-receipt.json']:
        subprocess.run(['scp', *SSH_OPTIONS, host + ':' + remote + '/artifacts/' + name, str(folder / name)],
                       check=True, timeout=120)
    receipt = verify_receipt(folder, revision)
    print(f'Verified {folder / ARTIFACT}\nSHA-256: {receipt["sha256"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='mac-mini')
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--output', type=Path, help='New local output directory; refuses existing paths')
    args = parser.parse_args()
    execute(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f'Build failed: {error}', file=sys.stderr)
        sys.exit(1)
