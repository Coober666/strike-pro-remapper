// User-assigned names only; no manufacturer defaults and no MIDI output.
export const MAX_PROFILES=25, MAX_MAPPINGS=128, MAX_PROFILE_BYTES=128*1024;
const KEY='drum-midi-profiles-v1';
const tooLarge=raw => raw.length > MAX_PROFILE_BYTES || new TextEncoder().encode(raw).byteLength > MAX_PROFILE_BYTES;
export function emptyProfile(name='My drums') {
  return {format:'drum-midi-profile',version:1,name,mappings:[]};
}
export function validateProfile(value) {
  const fail=() => { throw new Error('Invalid pad profile. Use a version 1 profile with a name and up to 128 unique channel/note mappings.'); };
  if (!value || value.format !== 'drum-midi-profile' || value.version !== 1 ||
      typeof value.name !== 'string' || !value.name.trim() || value.name.length > 80 || /[\r\n\t]/.test(value.name) ||
      !Array.isArray(value.mappings) || value.mappings.length > MAX_MAPPINGS) fail();
  const seen=new Set();
  const mappings=value.mappings.map(m => {
    if (!m || !Number.isInteger(m.channel) || m.channel < 1 || m.channel > 16 ||
        !Number.isInteger(m.note) || m.note < 0 || m.note > 127 ||
        typeof m.label !== 'string' || !m.label.trim() || m.label.length > 80 || /[\r\n\t]/.test(m.label)) fail();
    const key=`${m.channel}:${m.note}`;
    if (seen.has(key)) fail();
    seen.add(key); return {channel:m.channel,note:m.note,label:m.label.trim()};
  });
  return {...emptyProfile(value.name.trim()),mappings:mappings.sort((a,b) => a.channel-b.channel || a.note-b.note)};
}
export function padLabel(profile, channel, note) {
  return profile?.mappings.find(m => m.channel === channel && m.note === note)?.label || '';
}
export function assignPad(profile, channel, note, label) {
  return validateProfile({...profile,mappings:[...profile.mappings.filter(m => m.channel !== channel || m.note !== note),{channel,note,label}]});
}
export function readProfiles(storage=localStorage) {
  const raw=storage.getItem(KEY);
  if (!raw) return [];
  if (tooLarge(raw)) throw new Error('Saved pad profiles are too large.');
  const profiles=JSON.parse(raw);
  if (!Array.isArray(profiles) || profiles.length > MAX_PROFILES) throw new Error('Invalid saved pad profiles.');
  const clean=profiles.map(validateProfile);
  if (new Set(clean.map(p => p.name)).size !== clean.length) throw new Error('Duplicate saved profile names.');
  return clean;
}
export function writeProfiles(profiles, storage=localStorage) {
  if (profiles.length > MAX_PROFILES) throw new Error('This browser already has 25 profiles. Export and delete one first.');
  const clean=profiles.map(validateProfile), raw=JSON.stringify(clean);
  if (new Set(clean.map(p => p.name)).size !== clean.length) throw new Error('Duplicate saved profile names.');
  if (tooLarge(raw)) throw new Error('Saved pad profiles exceed 128 KB. Export and delete one first.');
  storage.setItem(KEY,raw);
}
