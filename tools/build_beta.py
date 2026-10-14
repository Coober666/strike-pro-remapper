"""Build a portable source beta ZIP; excludes user libraries and development state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PREFIX = 'strike-remapper-beta/'
START = '''Strike Remapper source beta

Extract this whole folder before launching. Python 3.10+ is required;
the host window also needs Tk. This is an unsigned testing package.

Windows: open launch-host.bat.
Mac: open launch-host.command, or run python3 launch_editor.py here.
Linux desktop: run python3 launch_editor.py here.

Choose a separate library folder, then Open editor.
Start with an empty library or a copy. Keep your original library backed up.
For a module-free walkthrough, open Drum MIDI toolkit and Try a demo.

Read docs/BETA_START.md for the full walkthrough, mobile Wi-Fi setup,
backup boundaries and upgrade steps. Read docs/HOST_LAUNCHER.md for
Python/Tk setup or a terminal-only host. Real hardware acceptance is pending.

Application identity and file hashes are in BETA-MANIFEST.json.
'''
FILES = ('strike_remap.py', 'launch_editor.py', 'launch.bat', 'launch.command',
         'launch-host.bat', 'launch-host.command', 'requirements-midi.txt', 'LICENSE',
         'README.md', 'FORMAT.md', 'factory_catalog.json', 'factory_fingerprints.json',
         'tools/hex_explorer.py', 'tools/sin_inspector.py', 'tools/make_metal_kit.py')
GLOBS = ('strike_remapper/*.py', 'strike_remapper/vendor/*.py',
         'strike_remapper/vendor/*.md', 'web/midi-toolkit/*.js', 'web/midi-toolkit/*.html',
         'web/midi-toolkit/*.css', 'web/wifi-editor/*.js', 'web/wifi-editor/*.html',
         'web/wifi-editor/*.css', 'web/factory-controller/*.js', 'web/factory-controller/*.html',
         'web/factory-controller/*.css', 'docs/*.md', 'docs/*.png')


def build(output, root=ROOT):
    root = root.resolve()
    paths = {root / name for name in FILES}
    for pattern in GLOBS:
        paths.update(root.glob(pattern))
    content = {}
    for path in sorted(paths):
        # Never follow a linked source folder outside the selected application.
        path.resolve().relative_to(root)
        if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
            raise ValueError(f'Linked package source is not supported: {path.name}')
        data = path.read_bytes()
        name = path.relative_to(root).as_posix()
        if name.endswith('.command'):
            data = data.replace(b'\r\n', b'\n')
        content[name] = data
    content['START-HERE.txt'] = START.encode('utf-8')
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        changed = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=root, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, changed = 'unknown', True
    manifest = {'format': 'strike-source-beta', 'version': 1, 'revision': revision,
                'workingTreeChanged': changed, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in content.items()}}
    content['BETA-MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects earlier artifacts from accidental replacement.
    with output.open('xb') as handle, zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            entry = zipfile.ZipInfo(PREFIX + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if name.endswith('.command') else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--require-clean', action='store_true', help='Reject unknown or modified source trees')
    args = parser.parse_args()
    if args.require_clean:
        from strike_remapper.support import identity
        source = identity(ROOT)
        if source['revision'] == 'unknown' or source['working_tree_changed'] is not False:
            parser.error('A clean Git checkout is required for an automated beta.')
    result = build(args.output)
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    with args.output.with_suffix('.sha256.txt').open('x', encoding='utf-8') as handle:
        handle.write(checksum + '  ' + args.output.name + '\n')
    print(f'Built {args.output} ({len(result["files"])} files), source {result["revision"]}')
    print('Source beta: Python required; unsigned; physical acceptance pending.')
