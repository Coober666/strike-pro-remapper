import { existsSync, readFileSync, unlinkSync } from 'node:fs';
import path from 'node:path';

const pidFile = path.resolve('.build', 'browser-server.pid');

export default async function globalTeardown() {
  if (!existsSync(pidFile)) return;
  const pid = Number(readFileSync(pidFile, 'utf8'));
  try {
    process.kill(pid, 'SIGTERM');
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
  } finally {
    unlinkSync(pidFile);
  }

  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      process.kill(pid, 0);
    } catch {
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`browser test server process ${pid} did not stop`);
}
