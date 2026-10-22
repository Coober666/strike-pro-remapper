"""Package selected public guides as text files readable without a Markdown app."""
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parent.parent
GUIDES = {
    'WINDOWS_BETA.md': 'Windows-start.txt',
    'HOST_LAUNCHER.md': 'Host-and-recovery.txt',
    'WIFI_EDITOR.md': 'iPad-and-iPhone.txt',
    'MIDI_TOOLKIT.md': 'MIDI-toolkit.txt',
    'TRIGGER_COACH.md': 'Trigger-coach.txt',
    'SETLISTS.md': 'Setlists.txt',
    'KIT_BALANCE.md': 'Kit-balance.txt',
    'HANDS_ON_ACCEPTANCE.md': 'Device-checks.txt',
    'RELEASE_CHECKLIST.md': 'Release-checklist.txt',
    'BETA_START.md': 'Source-start.txt',
    'FACTORY_SD_ACTIVATION.md': 'Factory-card.txt',
    'IPAD_FACTORY_CONTROLLER.md': 'Factory-controller.txt',
    'MAC_HARDWARE_ACCEPTANCE_2026-10-14.md': 'Mac-hardware-evidence.txt',
}
IMAGES = ('midi-toolkit.png', 'wifi-midi-ipad.png')


def readable(markdown, revision):
    """Keep prose/code as plain text; point related guides at their packaged names."""
    base = f'https://github.com/Coober666/strike-pro-remapper/blob/{revision}/docs/'

    def link(match):
        label, target = match.group(1), match.group(2)
        parts = urlsplit(target)
        if target.startswith('#'):
            return label + ' (section: ' + target[1:].replace('-', ' ') + ')'
        if not parts.scheme and not parts.netloc:
            if parts.path in GUIDES:
                target = GUIDES[parts.path]
                if parts.fragment:
                    target += ', section: ' + parts.fragment.replace('-', ' ')
            elif parts.path not in IMAGES:
                target = urljoin(base, target)
        return label + ' (' + target + ')'

    lines, code = [], False
    for line in markdown.splitlines():
        if line.startswith('```'):
            code = not code
            continue
        if not code:
            line = re.sub(r'^#{1,6} ', '', line)
            line = re.sub(r'!?\[([^\]\n]+)\]\(([^)\n]+)\)', link, line)
            line = re.sub(r'`([^`\n]+)`', r'\1', line)
            line = re.sub(r'\*\*([^*\n]+)\*\*', r'\1', line)
        lines.append(line)
    return '\n'.join(lines) + '\n'


def write_help(folder, revision, root=ROOT):
    """The allowlist excludes private evidence, captures and developer instructions."""
    help_dir = Path(folder) / 'Help'
    help_dir.mkdir()
    ref = revision if re.fullmatch(r'[0-9a-f]{40}', revision) else 'main'
    for source, name in GUIDES.items():
        content = (root / 'docs' / source).read_text(encoding='utf-8')
        (help_dir / name).write_text(readable(content, ref), encoding='utf-8')
    for name in IMAGES:
        shutil.copyfile(root / 'docs' / name, help_dir / name)
    (help_dir / 'README.txt').write_text(
        'STRIKE REMAPPER HELP\n\n'
        'Double-click a .txt guide to read it in Notepad. No internet connection or\n'
        'Markdown app is needed. Related guide filenames refer to this Help folder.\n'
        'Screenshots are included as PNG files. Optional web links need internet.\n\n'
        'Start with Windows-start.txt. For iPad/iPhone pairing, use iPad-and-iPhone.txt.\n'
        'Host-and-recovery.txt covers stopping, recovery, backups and upgrades.\n'
        'MIDI-toolkit.txt covers recording, browser storage, profiles and exports.\n'
        'Trigger-coach.txt explains observations, review thresholds and next exercises.\n'
        'Device-checks.txt describes tests still requiring people or real hardware.\n'
        'Source-start.txt is for the separate Python source package.\n\n'
        f'Build revision: {revision}\n'
        'These files are generated from the public repository guides for this build.\n',
        encoding='utf-8')
