#!/usr/bin/env node
// Deterministic contracts for the cross-platform Python resolver.

import assert from 'node:assert/strict';

import { pythonCandidates, resolvePython } from './python.mjs';

const override = 'C:\\Program Files\\Python\\python.exe';
const overrideAttempts = [];
assert.deepEqual(resolvePython({
  env: { PYTHON: override },
  platform: 'win32',
  probe(candidate) {
    overrideAttempts.push(candidate.command);
    return true;
  },
}), { command: override, args: [] });
assert.deepEqual(overrideAttempts, [override]);
console.log('  ok   PYTHON override is authoritative and preserves spaces');

assert.deepEqual(
  pythonCandidates({ env: {}, platform: 'win32' }),
  [
    { command: 'py', args: ['-3'] },
    { command: 'python', args: [] },
    { command: 'python3', args: [] },
  ],
);
assert.deepEqual(
  pythonCandidates({ env: {}, platform: 'darwin' }),
  [
    { command: 'python3', args: [] },
    { command: 'python', args: [] },
  ],
);
console.log('  ok   platform fallback order covers Windows and macOS/Linux');

const attempts = [];
assert.deepEqual(resolvePython({
  env: {},
  platform: 'win32',
  probe(candidate) {
    attempts.push(candidate.command);
    if (candidate.command === 'py') throw new Error('missing');
    return candidate.command === 'python';
  },
}), { command: 'python', args: [] });
assert.deepEqual(attempts, ['py', 'python']);
console.log('  ok   failed and throwing probes advance to the next candidate');

assert.throws(
  () => resolvePython({ env: { PYTHON: '/missing/python' }, probe: () => false }),
  /PYTHON is set to.*could not run/,
);
console.log('  ok   an invalid explicit override fails clearly');

assert.throws(
  () => resolvePython({ env: {}, platform: 'darwin', probe: () => false }),
  /No usable Python interpreter found \(tried: python3, python\)/,
);
console.log('  ok   exhausting fallbacks reports every attempted interpreter');

console.log('\nall Python resolver contracts passed');
