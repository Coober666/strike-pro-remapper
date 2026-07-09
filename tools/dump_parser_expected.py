#!/usr/bin/env python3
"""
dump_parser_expected.py — dump the Python parsers' output for the synthetic fixtures
to JSON, so the JS port (web/*.js) can be checked byte/field-exact against it.

Produces tests/fixtures/parsers_expected.json:

  { "skt": { "<name>.skt": {kit_raw(hex), instruments, tail(hex), pads:[_pad_view]} },
    "sin": { "<name>.sin": {parse_sin, all_wavs, first_wav} } }

Run `python tools/make_fixtures.py` first. Consumed by web/test_parsers.mjs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strike_remap as sr

FIX = ROOT / 'tests' / 'fixtures'
OUT = FIX / 'parsers_expected.json'


def _pad_view(pads, instruments):
    # _pad_view is a Handler method but pure in its args; call it unbound.
    return sr.Handler._pad_view(None, pads, instruments)


def dump_skt(path: Path) -> dict:
    kit_raw, pads, instruments, tail = sr.parse_skt(path.read_bytes())
    return {
        'kit_raw': bytes(kit_raw).hex(),
        'instruments': instruments,
        'tail': bytes(tail).hex(),
        'pads': _pad_view(pads, instruments),
    }


def dump_sin(path: Path) -> dict:
    data = path.read_bytes()
    return {
        'parse_sin': sr.parse_sin(data),
        'all_wavs': sr.parse_sin_all_wavs(data),
        'first_wav': sr.parse_sin_first_wav(data),
        'blocks': {k.decode('ascii', 'replace'): list(v)
                   for k, v in sr._sin_blocks(data).items()},
    }


def main():
    if not FIX.is_dir():
        sys.exit('fixtures missing — run `python tools/make_fixtures.py` first')
    out = {'skt': {}, 'sin': {}}
    for p in sorted(FIX.glob('*.skt')):
        out['skt'][p.name] = dump_skt(p)
    for p in sorted(FIX.glob('*.sin')):
        out['sin'][p.name] = dump_sin(p)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True), encoding='utf-8')
    print(f'wrote {OUT} ({len(out["skt"])} skt, {len(out["sin"])} sin)')


if __name__ == '__main__':
    main()
