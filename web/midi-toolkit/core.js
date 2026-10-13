// Pure channel-message capture/analysis. No device access, audio, or MIDI output.
export const MAX_EVENTS = 50000;
export const MAX_DURATION = 20 * 60 * 1000;
export const MAX_FILE_BYTES = 8 * 1024 * 1024;
export function message(data) {
  if (!Array.isArray(data) && !(data instanceof Uint8Array)) return null;
  const bytes = Array.from(data);
  const status = bytes[0], kind = status >> 4;
  if (!Number.isInteger(status) || status < 0x80 || status >= 0xf0) return null;
  if (bytes.length !== ([0xc, 0xd].includes(kind) ? 2 : 3)) return null;
  if (bytes.slice(1).some(v => !Number.isInteger(v) || v < 0 || v > 127)) return null;
  return {bytes, channel:(status & 15) + 1, kind,
    type:kind === 9 ? (bytes[2] ? 'Note on' : 'Note off') :
      ({8:'Note off', 10:'Poly pressure', 11:'Control change', 12:'Program change', 13:'Channel pressure', 14:'Pitch bend'})[kind]};
}
export function newSession(name='Untitled capture', source='Unknown input', synthetic=false) {
  return {format:'drum-midi-session', version:1, name, source, synthetic,
    createdAt:new Date().toISOString(), durationMs:0, segments:[0], events:[]};
}
export function validateSession(value) {
  const fail = reason => { throw new Error('Invalid session: ' + reason); };
  if (!value || value.format !== 'drum-midi-session' || value.version !== 1) fail('expected a version 1 drum MIDI session JSON file.');
  for (const [key, max] of [['name', 120], ['source', 160], ['createdAt', 40]]) {
    if (typeof value[key] !== 'string' || !value[key].trim() || value[key].length > max) fail('bad ' + key + '.');
  }
  if (!Number.isFinite(Date.parse(value.createdAt))) fail('bad creation date.');
  if (typeof value.synthetic !== 'boolean') fail('missing demo/source marker.');
  if (!Number.isFinite(value.durationMs) || value.durationMs < 0 || value.durationMs > MAX_DURATION) fail('duration exceeds 20 minutes.');
  if (!Array.isArray(value.events) || value.events.length > MAX_EVENTS) fail('too many events (maximum 50,000).');
  const segments=value.segments ?? [0];
  if (!Array.isArray(segments) || !segments.length || segments.length > MAX_EVENTS+1 || segments[0] !== 0 ||
      segments.some((n,i) => !Number.isInteger(n) || n < 0 || n > value.events.length || (i && n <= segments[i-1]))) fail('bad pause boundaries.');
  let previous = 0;
  const events = value.events.map(e => {
    if (!e || !Number.isFinite(e.t) || e.t < previous || e.t > value.durationMs) fail('event times must be ordered and within the duration.');
    const parsed = message(e.data);
    if (!parsed) fail('only complete MIDI channel messages are supported; no SysEx or system messages.');
    previous = e.t;
    return {t:e.t, data:parsed.bytes};
  });
  return {...newSession(value.name.trim(), value.source.trim(), value.synthetic), createdAt:value.createdAt,
    durationMs:value.durationMs, segments:[...segments], events};
}
export function summarize(session, until=Infinity) {
  const groups = new Map(), histogram = Array(16).fill(0), controllers = new Map();
  let hits = 0, count = 0, segment = 0;
  for (const [index,e] of session.events.entries()) {
    while (index >= (session.segments?.[segment+1] ?? Infinity)) segment++;
    if (e.t > until) break;
    const m = message(e.data);
    if (!m) continue;
    count++;
    if (m.kind === 11) {
      const key = `${m.channel}:${e.data[1]}`, value = e.data[2];
      const c = controllers.get(key) || {channel:m.channel, controller:e.data[1], count:0, min:127, max:0, last:0};
      c.count++; c.min = Math.min(c.min, value); c.max = Math.max(c.max, value); c.last = value;
      controllers.set(key, c);
    }
    if (m.type !== 'Note on') continue;
    hits++; const velocity = e.data[2]; histogram[Math.floor(velocity / 8)]++;
    const key = `${m.channel}:${e.data[1]}`;
    const g = groups.get(key) || {channel:m.channel, note:e.data[1], values:[], gaps:[], last:null};
    if (g.last !== null && g.segment === segment) g.gaps.push(e.t - g.last);
    g.last = e.t; g.segment=segment; g.values.push(velocity); groups.set(key, g);
  }
  const notes = [...groups.values()].map(g => {
    const sum = g.values.reduce((a,b) => a+b, 0), mean = sum / g.values.length;
    const sorted = [...g.values].sort((a,b) => a-b), gaps = [...g.gaps].sort((a,b) => a-b);
    return {channel:g.channel, note:g.note, hits:g.values.length, mean,
      min:sorted[0], max:sorted.at(-1), p10:sorted[Math.floor((sorted.length-1)*.1)],
      p90:sorted[Math.floor((sorted.length-1)*.9)],
      std:Math.sqrt(g.values.reduce((s,v) => s+(v-mean)**2, 0)/g.values.length),
      minGapMs:gaps[0] ?? null, medianGapMs:gaps.length ? gaps[Math.floor(gaps.length/2)] : null};
  }).sort((a,b) => a.channel-b.channel || a.note-b.note);
  return {hits, count, histogram, notes, controllers:[...controllers.values()].sort((a,b) => a.channel-b.channel || a.controller-b.controller)};
}
export function compare(current, reference) {
  const a = summarize(current).notes, b = summarize(reference).notes;
  const key = n => `${n.channel}:${n.note}`, old = new Map(b.map(n => [key(n), n]));
  const keys = new Set([...a.map(key), ...b.map(key)]), now = new Map(a.map(n => [key(n), n]));
  return [...keys].map(k => ({key:k, current:now.get(k) || null, reference:old.get(k) || null}));
}
function csvCell(value) {
  let text = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
export function exportCSV(session) {
  const rows = [['time_ms', 'segment', 'type', 'channel', 'data_1', 'data_2', 'input', 'synthetic']];
  let segment=0;
  for (const [index,e] of session.events.entries()) {
    while (index >= (session.segments?.[segment+1] ?? Infinity)) segment++;
    const m = message(e.data);
    rows.push([e.t, segment+1, m.type, m.channel, e.data[1], e.data[2] ?? '', session.source, session.synthetic]);
  }
  return rows.map(r => r.map(csvCell).join(',')).join('\r\n');
}
export function report(session, reference=null) {
  const s = summarize(session);
  const lines = ['Drum MIDI session report', session.name, `Input: ${session.source}`, `Created: ${session.createdAt}`,
    `Source: ${session.synthetic ? 'Synthetic demo' : 'Recorded/imported MIDI'}`, `Active duration: ${(session.durationMs/1000).toFixed(2)} s`,
    `Channel messages: ${s.count}; note-on hits: ${s.hits}`, '', 'Channel / note: hits, mean velocity, range, standard deviation, shortest repeated-note interval'];
  for (const n of s.notes) lines.push(`Ch ${n.channel} / ${n.note}: ${n.hits}, ${n.mean.toFixed(1)}, ${n.min}–${n.max}, ${n.std.toFixed(1)}, ${n.minGapMs === null ? 'n/a' : n.minGapMs.toFixed(1)+' ms'}`);
  for (const c of s.controllers) lines.push(`Ch ${c.channel} CC ${c.controller}: ${c.count} messages, range ${c.min}–${c.max}, last ${c.last}`);
  if (reference) {
    lines.push('', `Comparison with: ${reference.name} (${(reference.durationMs/1000).toFixed(2)} s${reference.synthetic ? ', synthetic demo' : ''})`, 'Channel:note — mean velocity change (current minus reference)');
    for (const r of compare(session, reference)) lines.push(`${r.key}: ${r.current && r.reference ? (r.current.mean-r.reference.mean).toFixed(1) : 'not present in both captures'}`);
  }
  lines.push('', 'Velocity is MIDI data, not measured audio loudness. Pause gaps are excluded from captured time.',
    'Repeated-note gaps never cross a recorded pause boundary.',
    'Counts depend on duration and playing. Notes are not automatically identified as physical pads.',
    'Short intervals can be intentional playing. MIDI alone cannot prove missed hits, crosstalk, or a trigger-setting fault.',
    'Replay is a visual review; this toolkit does not send MIDI or modify a module.');
  return lines.join('\n');
}
export function demoSession() {
  const s = newSession('Demo · steady groove', 'Synthetic drum MIDI', true);
  for (let i=0; i<64; i++) {
    const t = i*250, v = 66 + (i*7)%28;
    s.events.push({t, data:[0x99,42,v]}, {t:t+30, data:[0x89,42,0]});
    if (i%4 === 0) s.events.push({t, data:[0x99,36,98]}, {t:t+45, data:[0x89,36,0]});
    if (i%4 === 2) s.events.push({t, data:[0x99,38,84+(i%7)]}, {t:t+45, data:[0x89,38,0]});
    if (i%8 === 0) s.events.push({t, data:[0xb9,4,(i*5)%128]});
  }
  s.events.sort((a,b) => a.t-b.t); s.durationMs=16000; return s;
}
