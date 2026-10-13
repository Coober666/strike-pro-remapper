import {validateSession, MAX_EVENTS} from './core.js';
export const MAX_ARCHIVE_BYTES=32*1024*1024, MAX_ARCHIVE_EVENTS=200000;
export function validateArchive(value) {
  if (!value || value.format !== 'drum-midi-session-backup' || value.version !== 1 || !Array.isArray(value.sessions) || !value.sessions.length || value.sessions.length > 25) throw new Error('Invalid backup: expected 1–25 MIDI sessions.');
  let count=0;
  for (const s of value.sessions) {
    if (!Array.isArray(s?.events) || s.events.length > MAX_EVENTS) throw new Error('Invalid backup session.');
    count+=s.events.length;
    if (count > MAX_ARCHIVE_EVENTS) throw new Error('Backup exceeds 200,000 events. Export smaller groups of sessions.');
  }
  return {format:'drum-midi-session-backup',version:1,sessions:value.sessions.map(validateSession)};
}
export function archiveJSON(sessions) {
  const text=JSON.stringify(validateArchive({format:'drum-midi-session-backup',version:1,sessions}));
  if (new TextEncoder().encode(text).byteLength > MAX_ARCHIVE_BYTES) throw new Error('Backup exceeds 32 MB. Export fewer sessions at a time.');
  return text;
}
