"""Commands shared by the source host and the bundled Windows runtime."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
UTILITIES = ('hex_explorer.py', 'sin_inspector.py', 'make_metal_kit.py')


def worker_command(mode, *args):
    if getattr(sys, 'frozen', False):
        return [str(Path(sys._MEIPASS) / 'StrikeHelper.exe'), mode, *map(str, args)]
    return [sys.executable, '-m', 'strike_remapper.desktop_worker', mode, *map(str, args)]


def hidden_process():
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}


def validate_library(root):
    if getattr(sys, 'frozen', False):
        application = Path(sys.executable).resolve().parent
        if application.name == '_internal':
            application = application.parent
        if root == application or application in root.parents:
            raise ValueError('Choose a library outside the application folder, so upgrades keep your files.')
