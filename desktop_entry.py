"""Frozen GUI and private console-helper entry point."""
import os
from pathlib import Path
import sys

if Path(sys.executable).stem == 'StrikeHelper':
    from strike_remapper.desktop_worker import main
else:
    # Windowed Windows applications have no console streams.
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    from launch_editor import main

if __name__ == '__main__':
    if Path(sys.executable).stem != 'StrikeHelper' and len(sys.argv) == 3 and sys.argv[1] == '--check-launcher':
        import json
        from strike_remapper.packaged_check import check_launcher
        target = Path(sys.argv[2]).resolve()
        try:
            result = check_launcher(target)
        except Exception as exc:
            target.mkdir(exist_ok=True)
            (target / 'error.txt').write_text(str(exc), encoding='utf-8')
            raise SystemExit(1)
        (target / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    else:
        main()
