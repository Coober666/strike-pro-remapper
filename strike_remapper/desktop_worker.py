"""Private subprocess entry point; frozen builds only run named operations."""
import json
from pathlib import Path
import runpy
import sys

from strike_remapper.runtime import ROOT, UTILITIES, validate_library


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    mode, *args = sys.argv[1:]
    if mode in ('midi-input', 'factory-midi'):
        module = 'strike_remapper.' + mode.replace('-', '_')
        sys.argv = [module, *args]
        runpy.run_module(module, run_name='__main__')
    elif mode == 'utility':
        library, name, *arguments = args
        if name not in UTILITIES:
            raise ValueError('Unknown bundled utility')
        import strike_remap as app
        root = Path(library).resolve()
        validate_library(root)
        app.set_library_root(root)
        sys.argv = [name, *arguments]
        runpy.run_path(str(ROOT / 'tools' / name), run_name='__main__')
    elif mode == 'probe' and not args:
        import importlib.metadata
        import rtmidi
        import tkinter
        window = tkinter.Tk()
        window.withdraw()
        window.update()
        window.destroy()
        print(json.dumps({'frozen': bool(getattr(sys, 'frozen', False)),
                          'prefix': sys.prefix, 'python': sys.version.split()[0],
                          'midi': importlib.metadata.version('python-rtmidi'),
                          'apis': rtmidi.get_compiled_api(), 'tk': tkinter.TkVersion}))
    elif mode == 'smoke' and len(args) == 1:
        from strike_remapper.packaged_check import check
        print(json.dumps(check(Path(args[0]))))
    else:
        raise ValueError('Unknown helper operation')


if __name__ == '__main__':
    main()
