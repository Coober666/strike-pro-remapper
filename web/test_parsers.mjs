// test_parsers.mjs — parity test: the JS parsers (web/skt.js, web/sin.js) must match
// the Python parsers field-for-field on the synthetic fixtures.
//
// Prereqs (CI runs both):
//   python tools/make_fixtures.py            → tests/fixtures/*.skt, *.sin
//   python tools/dump_parser_expected.py     → tests/fixtures/parsers_expected.json
//
// Run:  node web/test_parsers.mjs
// Exits non-zero on the first field that diverges.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { parseSkt } from './skt.js';
import { parseSin, parseSinAllWavs, parseSinFirstWav, sinBlocks } from './sin.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, '..', 'tests', 'fixtures');
const EXPECTED_PATH = join(FIX, 'parsers_expected.json');

function hex(u8) {
  return Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString('hex');
}

// Build the same canonical structure the Python dumper emits, from the JS parsers.
function jsSkt(name) {
  const buf = readFileSync(join(FIX, name));
  const r = parseSkt(buf);
  return {
    kit_raw: hex(r.kit_raw),
    instruments: r.instruments,
    tail: hex(r.tail),
    pads: r.pads,
  };
}

function jsSin(name) {
  const buf = readFileSync(join(FIX, name));
  const blocks = sinBlocks(buf);
  return {
    parse_sin: parseSin(buf),
    all_wavs: parseSinAllWavs(buf),
    first_wav: parseSinFirstWav(buf),
    blocks: Object.fromEntries(Object.entries(blocks).map(([k, v]) => [k, [...v]])),
  };
}

// Deep structural equality that reports the path of the first mismatch (key order agnostic).
function firstDiff(a, b, path = '') {
  if (a === b) return null;
  const ta = typeofX(a), tb = typeofX(b);
  if (ta !== tb) return `${path}: type ${ta} !== ${tb} (${fmt(a)} vs ${fmt(b)})`;
  if (ta === 'array') {
    if (a.length !== b.length) return `${path}: array length ${a.length} !== ${b.length}`;
    for (let i = 0; i < a.length; i++) {
      const d = firstDiff(a[i], b[i], `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (ta === 'object') {
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    if (ka.join(',') !== kb.join(',')) {
      return `${path}: keys differ\n  js:  ${ka.join(',')}\n  py:  ${kb.join(',')}`;
    }
    for (const k of ka) {
      const d = firstDiff(a[k], b[k], path ? `${path}.${k}` : k);
      if (d) return d;
    }
    return null;
  }
  return `${path}: ${fmt(a)} !== ${fmt(b)}`;
}

function typeofX(v) {
  if (Array.isArray(v)) return 'array';
  if (v === null) return 'null';
  return typeof v;
}
function fmt(v) {
  const s = JSON.stringify(v);
  return s.length > 80 ? s.slice(0, 77) + '...' : s;
}

function main() {
  let expected;
  try {
    expected = JSON.parse(readFileSync(EXPECTED_PATH, 'utf8'));
  } catch (e) {
    console.error(`Cannot read ${EXPECTED_PATH}\n` +
      'Run: python tools/make_fixtures.py && python tools/dump_parser_expected.py');
    process.exit(2);
  }

  const failures = [];
  let checked = 0;

  for (const [name, exp] of Object.entries(expected.skt)) {
    checked++;
    let got;
    try { got = jsSkt(name); }
    catch (e) { failures.push(`skt ${name}: JS threw ${e.message}`); continue; }
    const d = firstDiff(got, exp);
    if (d) failures.push(`skt ${name}:\n  ${d}`);
    else console.log(`  ok  skt  ${name}  (${exp.pads.length} pads, ${exp.instruments.length} instruments)`);
  }

  for (const [name, exp] of Object.entries(expected.sin)) {
    checked++;
    let got;
    try { got = jsSin(name); }
    catch (e) { failures.push(`sin ${name}: JS threw ${e.message}`); continue; }
    const d = firstDiff(got, exp);
    if (d) failures.push(`sin ${name}:\n  ${d}`);
    else console.log(`  ok  sin  ${name}  (${exp.parse_sin.mappings.length} mappings)`);
  }

  if (failures.length) {
    console.error(`\nFAIL — ${failures.length} fixture(s) diverged from Python:\n`);
    for (const f of failures) console.error(f + '\n');
    process.exit(1);
  }
  console.log(`\nPASS — ${checked} fixtures parse byte/field-identical in JS and Python.`);
}

main();
