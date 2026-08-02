#!/usr/bin/env python3
"""Run the real app against a deterministic throwaway library for Playwright."""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import strike_remap as app  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()

    test_root = ROOT / '.build' / 'browser-library'
    shutil.rmtree(test_root, ignore_errors=True)
    kits = test_root / 'kits'
    instruments = test_root / 'instruments'
    kits.mkdir(parents=True)
    instruments.mkdir(parents=True)

    fixture = ROOT / 'tests' / 'fixtures' / 'synthetic_kit.skt'
    if not fixture.is_file():
        raise SystemExit('missing synthetic fixtures; run python tools/make_fixtures.py')
    shutil.copy2(fixture, kits / "John's Test Kit.skt")

    # Keep browser tests independent from the developer's library and hardware.
    app.set_library_root(test_root)
    app.get_volumes = lambda: (None, None)

    server = app._Server(('127.0.0.1', args.port), app.Handler)
    print(f'browser test server listening on http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
