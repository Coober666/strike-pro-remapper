// test_similar.mjs — parity test: the JS k-NN ranking (web/similar.js) must match
// the Python _knn_rank field-for-field (key order + distance to 3 decimals) over the
// full factory fingerprint corpus.
//
// Prereqs (CI runs both):
//   python tools/dump_similar_expected.py   → tests/expected/similar_expected.json
//   (factory_fingerprints.json is committed at repo root — no library/SD needed)
//
// Run:  node web/test_similar.mjs
// Exits non-zero on the first query whose neighbour order or distances diverge.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { knnRank } from './similar.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const FACTORY_FP_PATH = join(ROOT, 'factory_fingerprints.json');
const EXPECTED_PATH = join(ROOT, 'tests', 'expected', 'similar_expected.json');

const N_NEIGHBOURS = 10;

function main() {
  let factory;
  try {
    factory = JSON.parse(readFileSync(FACTORY_FP_PATH, 'utf8'));
  } catch (e) {
    console.error(`Cannot read ${FACTORY_FP_PATH}: ${e.message}`);
    process.exit(2);
  }

  let expected;
  try {
    expected = JSON.parse(readFileSync(EXPECTED_PATH, 'utf8'));
  } catch (e) {
    console.error(`Cannot read ${EXPECTED_PATH}\n` +
      'Run: python tools/dump_similar_expected.py');
    process.exit(2);
  }

  // Same corpus construction as the Python dumper: every factory entry with feats.
  const corpus = Object.entries(factory)
    .filter(([, e]) => e && e.feats)
    .map(([rel, e]) => [rel, e.feats]);

  const failures = [];
  let checked = 0;

  for (const [query, expNeighbours] of Object.entries(expected)) {
    checked++;
    let got;
    try {
      got = knnRank(query, corpus, N_NEIGHBOURS);
    } catch (e) {
      failures.push(`${query}: JS threw ${e.message}`);
      continue;
    }
    const gotPairs = got.map(([key, dist]) => [key, dist]);

    if (gotPairs.length !== expNeighbours.length) {
      failures.push(
        `${query}: result count ${gotPairs.length} !== expected ${expNeighbours.length}`
      );
      continue;
    }

    let mismatch = null;
    for (let i = 0; i < expNeighbours.length; i++) {
      const [expKey, expDist] = expNeighbours[i];
      const [gotKey, gotDist] = gotPairs[i];
      if (gotKey !== expKey) {
        mismatch = `neighbour[${i}] key "${gotKey}" !== expected "${expKey}"`;
        break;
      }
      if (Math.abs(gotDist - expDist) > 1e-9) {
        mismatch = `neighbour[${i}] (${gotKey}) dist ${gotDist} !== expected ${expDist}`;
        break;
      }
    }

    if (mismatch) {
      failures.push(`${query}:\n  ${mismatch}`);
    } else {
      console.log(`  ok  ${query}  (${gotPairs.length} neighbours)`);
    }
  }

  if (failures.length) {
    console.error(`\nFAIL — ${failures.length}/${checked} quer${failures.length === 1 ? 'y' : 'ies'} diverged from Python:\n`);
    for (const f of failures) console.error(f + '\n');
    process.exit(1);
  }
  console.log(`\nPASS — ${checked}/${checked} queries rank byte-identical in JS and Python.`);
}

main();
