#!/usr/bin/env python3
"""Extract the embedded editor script to a temporary file for JS tooling."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / '.build' / 'embedded.js'


def main():
    spec = importlib.util.spec_from_file_location('strike_remap', ROOT / 'strike_remap.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    scripts = re.findall(r'<script>(.*?)</script>', app.HTML, re.S)
    if not scripts:
        raise SystemExit('no embedded <script> block found')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text('\n'.join(scripts), encoding='utf-8')
    print(f'wrote {OUTPUT.relative_to(ROOT)} ({len(scripts)} script block(s))')


if __name__ == '__main__':
    main()
