"""Small allowlisted support reports: no paths, hostnames, tokens or kit content."""
import json
from pathlib import Path
import platform
import re
import subprocess


def identity(root):
    root = Path(root)
    result = {'product': 'Strike Remapper', 'channel': 'source beta',
              'revision': 'unknown', 'working_tree_changed': None}
    manifest = root / 'BETA-MANIFEST.json'
    if manifest.is_file():
        try:
            with manifest.open('rb') as handle:
                data = handle.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                return result
            value = json.loads(data)
            if value.get('format') in ('strike-source-beta', 'strike-windows-beta') and re.fullmatch(r'[0-9a-f]{40}', value.get('revision', '')):
                if value['format'] == 'strike-windows-beta':
                    result['channel'] = 'Windows beta'
                result.update(revision=value['revision'], working_tree_changed=value.get('workingTreeChanged') is not False)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return result
    # Do not accidentally identify a parent checkout as this application.
    if (root / '.git').exists():
        try:
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True,
                                               stderr=subprocess.DEVNULL, timeout=2).strip()
            if re.fullmatch(r'[0-9a-f]{40}', revision):
                changed = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'],
                                                  cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=2)
                result.update(revision=revision, working_tree_changed=bool(changed))
        except (OSError, subprocess.SubprocessError):
            pass
    return result


def report(root, state):
    return {'format': 'strike-support-report', 'version': 1, 'application': identity(root),
            'host': {'os': platform.system(), 'python': platform.python_version()},
            'editor': {'kit_open': bool(state.get('kit_path')), 'unsaved_changes': bool(state.get('dirty')),
                       'pads': len(state.get('pads', [])), 'undo_steps': len(state.get('history', []))},
            'scope': 'No library paths, kit names, audio, MIDI data, network addresses or pairing credentials included. Card and driver status are not probed.'}
