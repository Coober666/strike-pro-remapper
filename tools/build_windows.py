"""Build an unsigned Windows x64 folder ZIP with Python, Tk and input MIDI."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build(output, require_clean=False):
    from strike_remapper.support import identity
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Build on Windows x64 with Python 3.11 x64.')
    if sys.version_info[:2] != (3, 11):
        raise ValueError('Use Python 3.11 for the pinned MIDI wheel.')
    source = identity(ROOT)
    if require_clean and (source['revision'] == 'unknown' or source['working_tree_changed'] is not False):
        raise ValueError('A clean Git checkout is required.')
    if output.exists():
        raise FileExistsError(output)
    staging = ROOT / '.build'
    staging.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='windows-', dir=staging) as temporary:
        scratch = Path(temporary)
        info = {'format': 'strike-windows-beta', 'version': 1,
                'revision': source['revision'], 'workingTreeChanged': source['working_tree_changed'],
                'python': platform.python_version(), 'architecture': 'x64',
                'dependencies': {name: importlib.metadata.version(name)
                                 for name in ('pyinstaller', 'python-rtmidi')}}
        manifest = scratch / 'BETA-MANIFEST.json'
        manifest.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
        datas = [(str(ROOT / name), '.') for name in
                 ('factory_catalog.json', 'factory_fingerprints.json', 'LICENSE')]
        datas += [(str(manifest), '.')]
        for directory in ('web/midi-toolkit', 'web/wifi-editor', 'web/factory-controller'):
            datas += [(str(p), directory) for p in (ROOT / directory).iterdir() if p.suffix in ('.js', '.css', '.html')]
        datas += [(str(ROOT / 'tools' / name), 'tools') for name in
                  ('hex_explorer.py', 'sin_inspector.py', 'make_metal_kit.py')]
        # Include runtime licenses, independent of the developer machine's layout.
        python_license = Path(sys.base_prefix) / 'LICENSE.txt'
        if not python_license.is_file():
            raise FileNotFoundError('Python runtime LICENSE.txt')
        datas.append((str(python_license), 'licenses/python'))
        for component in ('tcl8.6', 'tk8.6'):
            license_file = Path(sys.base_prefix) / 'tcl' / component / 'license.terms'
            if not license_file.is_file() and component == 'tcl8.6':
                license_file = ROOT / 'packaging/licenses/tcl-license.terms'
            if not license_file.is_file():
                raise FileNotFoundError('Missing Tcl/Tk license: ' + component)
            datas.append((str(license_file), 'licenses/' + component))
        datas += [(str(p), 'licenses/vendor') for p in (ROOT / 'strike_remapper/vendor').glob('*.md')]
        for package in ('python-rtmidi', 'pyinstaller'):
            distribution = importlib.metadata.distribution(package)
            licenses = [f for f in distribution.files if 'license' in str(f).lower() or 'copying' in str(f).lower()]
            if not licenses:
                raise ValueError('Missing dependency license: ' + package)
            datas += [(str(distribution.locate_file(f)), 'licenses/' + package) for f in licenses]
        spec = scratch / 'windows.spec'
        spec.write_text(
            "from PyInstaller.utils.hooks import collect_submodules, copy_metadata\n"
            f"a = Analysis([{str(ROOT / 'desktop_entry.py')!r}], pathex=[{str(ROOT)!r}], "
            f"datas={datas!r} + copy_metadata('python-rtmidi'), "
            "hiddenimports=collect_submodules('strike_remapper') + ['rtmidi', 'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox'])\n"
            "pyz = PYZ(a.pure)\n"
            "gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Strike Remapper', console=False)\n"
            "helper = EXE(pyz, a.scripts, [], exclude_binaries=True, name='StrikeHelper', console=True, contents_directory='.')\n"
            "app = COLLECT(gui, helper, a.binaries, a.datas, name='Strike Remapper')\n",
            encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(scratch / 'dist'), '--workpath', str(scratch / 'work'), str(spec)], check=True)
        folder = scratch / 'dist/Strike Remapper'
        (folder / 'StrikeHelper.exe').rename(folder / '_internal/StrikeHelper.exe')
        shutil.copyfile(ROOT / 'docs/WINDOWS_BETA.md', folder / 'START-HERE.txt')
        shutil.copyfile(ROOT / 'LICENSE', folder / 'LICENSE.txt')
        info['files'] = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(folder.rglob('*')) if p.is_file()}
        (folder / 'PACKAGE-MANIFEST.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as handle, zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    archive.write(path, 'Strike Remapper/' + path.relative_to(folder).as_posix())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.sha256.txt').write_text(digest + '  ' + output.name + '\n', encoding='utf-8')
    print(f'Built {output}: {output.stat().st_size / 1024 / 1024:.1f} MB, revision {source["revision"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-clean', action='store_true')
    args = parser.parse_args()
    build(args.output.resolve(), args.require_clean)
