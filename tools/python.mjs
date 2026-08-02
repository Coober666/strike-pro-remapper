#!/usr/bin/env node
// Resolve and run Python consistently from Node-based tooling.

import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const PROBE_TIMEOUT_MS = 5000;

export function pythonCandidates({ env = process.env, platform = process.platform } = {}) {
  const override = env.PYTHON?.trim();
  if (override) return [{ command: override, args: [] }];
  return platform === 'win32'
    ? [
        // Override a script's python3 shebang; the Windows launcher may otherwise
        // redirect it to an inaccessible Microsoft Store execution alias.
        { command: 'py', args: ['-3'] },
        { command: 'python', args: [] },
        { command: 'python3', args: [] },
      ]
    : [
        { command: 'python3', args: [] },
        { command: 'python', args: [] },
      ];
}

function defaultProbe(candidate) {
  const result = spawnSync(candidate.command, [...candidate.args, '-c', 'import sys'], {
    stdio: 'ignore',
    timeout: PROBE_TIMEOUT_MS,
    windowsHide: true,
  });
  return !result.error && result.status === 0;
}

export function resolvePython(options = {}) {
  const env = options.env ?? process.env;
  const candidates = pythonCandidates({ env, platform: options.platform });
  const probe = options.probe ?? defaultProbe;

  for (const candidate of candidates) {
    try {
      if (probe(candidate)) return candidate;
    } catch {
      // A failed probe is equivalent to an unavailable candidate.
    }
  }

  if (env.PYTHON?.trim()) {
    throw new Error(`PYTHON is set to ${JSON.stringify(env.PYTHON.trim())}, but that executable could not run`);
  }
  const attempted = candidates
    .map(candidate => [candidate.command, ...candidate.args].join(' '))
    .join(', ');
  throw new Error(`No usable Python interpreter found (tried: ${attempted})`);
}

export function runPython(args, options = {}) {
  const python = resolvePython(options);
  const result = spawnSync(python.command, [...python.args, ...args], {
    cwd: options.cwd ?? process.cwd(),
    env: options.env ?? process.env,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.signal) {
    throw new Error(`Python terminated by signal ${result.signal}`);
  }
  return result.status ?? 1;
}

const isMain = process.argv[1]
  && pathToFileURL(resolve(process.argv[1])).href === import.meta.url;

if (isMain) {
  if (process.argv.length < 3) {
    console.error('usage: node tools/python.mjs <script> [args...]');
    process.exitCode = 2;
  } else {
    try {
      process.exitCode = runPython(process.argv.slice(2));
    } catch (error) {
      console.error(error.message);
      process.exitCode = 1;
    }
  }
}
