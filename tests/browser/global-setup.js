import { closeSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';

import { resolvePython } from '../../tools/python.mjs';

const buildDir = path.resolve('.build');
const pidFile = path.join(buildDir, 'browser-server.pid');
const logFile = path.join(buildDir, 'browser-server.log');
const port = 8767;

export default async function globalSetup() {
  mkdirSync(buildDir, { recursive: true });
  const python = resolvePython();
  const log = openSync(logFile, 'w');
  const server = spawn(python.command, [
    ...python.args,
    'tools/browser_test_server.py',
    '--port',
    String(port),
  ], {
    cwd: process.cwd(),
    detached: false,
    stdio: ['ignore', log, log],
    windowsHide: true
  });
  closeSync(log);
  writeFileSync(pidFile, String(server.pid));
  server.unref();

  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(`browser test server exited early:\n${readFileSync(logFile, 'utf8')}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/start`);
      if (response.ok) return;
    } catch {
      // The server has not bound its port yet.
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  server.kill();
  throw new Error(`browser test server did not become ready:\n${readFileSync(logFile, 'utf8')}`);
}
