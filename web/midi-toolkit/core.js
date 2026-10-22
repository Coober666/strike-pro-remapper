import {validateProfile, padLabel} from './profiles.js';
import {sessionTags, EXERCISES} from './metadata.js';
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
    createdAt:new Date().toISOString(), durationMs:0, segments:[0], captureStatus:'complete', tags:[], notesText:'', exercise:'', events:[]};
}
export function validateSession(value) {
  const fail = reason => { throw new Error('Invalid session: ' + reason); };
  if (!value || value.format !== 'drum-midi-session' || value.version !== 1) fail('expected a version 1 drum MIDI session JSON file.');
  for (const [key, max] of [['name', 120], ['source', 160], ['createdAt', 40]]) {
    if (typeof value[key] !== 'string' || !value[key].trim() || value[key].length > max) fail('bad ' + key + '.');
  }
  if (!Number.isFinite(Date.parse(value.createdAt))) fail('bad creation date.');
  if (typeof value.synthetic !== 'boolean') fail('missing demo/source marker.');
  if (value.captureStatus !== undefined && !['complete','partial'].includes(value.captureStatus)) fail('bad capture status.');
  if (!Number.isFinite(value.durationMs) || value.durationMs < 0 || value.durationMs > MAX_DURATION) fail('duration exceeds 20 minutes.');
  if (!Array.isArray(value.events) || value.events.length > MAX_EVENTS) fail('too many events (maximum 50,000).');
  if (value.notesText !== undefined && (typeof value.notesText !== 'string' || value.notesText.length > 2000)) fail('notes exceed 2,000 characters.');
  if (value.exercise !== undefined && (typeof value.exercise !== 'string' || (value.exercise !== '' && !Object.hasOwn(EXERCISES,value.exercise)))) fail('unknown capture exercise.');
  const tags=sessionTags(value.tags);
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
    tags, notesText:value.notesText || '', exercise:value.exercise || '',
    durationMs:value.durationMs, segments:[...segments], captureStatus:value.captureStatus || 'complete', events,
    ...(value.padMap === undefined ? {} : {padMap:validateProfile(value.padMap)})};
}
export function matchesFocus(data, focus='') {
  if (!focus) return true;
  const m=message(data);
  return !!m && [8,9,10].includes(m.kind) && `${m.channel}:${data[1]}` === focus;
}
export function summarize(session, until=Infinity, focus='') {
  const groups = new Map(), histogram = Array(16).fill(0), controllers = new Map();
  let hits = 0, count = 0, segment = 0;
  for (const [index,e] of session.events.entries()) {
    while (index >= (session.segments?.[segment+1] ?? Infinity)) segment++;
    if (e.t > until) break;
    const m = message(e.data);
    if (!m || !matchesFocus(e.data,focus)) continue;
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
export function compare(current, reference, focus='') {
  const a = summarize(current,Infinity,focus).notes, b = summarize(reference,Infinity,focus).notes;
  const key = n => `${n.channel}:${n.note}`, old = new Map(b.map(n => [key(n), n]));
  const keys = new Set([...a.map(key), ...b.map(key)]), now = new Map(a.map(n => [key(n), n]));
  return [...keys].map(k => ({key:k, current:now.get(k) || null, reference:old.get(k) || null}));
}
function csvCell(value) {
  let text = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
// Review thresholds are transparent prompts, not calibrated fault classifiers.
export function triggerAdvice(session, reference=null, focus='') {
  const stats=summarize(session,Infinity,focus), counts=new Map(), pairs=new Map();
  let segment=0, previous=null;
  const last=new Map();
  for (const [index,e] of session.events.entries()) {
    if (index >= (session.segments?.[segment+1] ?? Infinity)) {
      while (index >= (session.segments?.[segment+1] ?? Infinity)) segment++;
      last.clear(); previous=null;
    }
    const m=message(e.data);
    if (m?.type !== 'Note on') continue;
    const key=`${m.channel}:${e.data[1]}`;
    const c=counts.get(key) || {rapid:0,top:0,zeroGap:0};
    const gap=last.has(key) ? e.t-last.get(key) : null;
    if (gap !== null && gap <= 30) c.rapid++;
    if (gap === 0) c.zeroGap++;
    if (e.data[2] >= 120) c.top++;
    counts.set(key,c); last.set(key,e.t);
    // Adjacent positive note-ons only: linear work even for dense imported takes.
    if (previous && previous.key !== key && previous.channel === m.channel && e.t-previous.t <= 12) {
      const keys=[previous.key,key].sort();
      if (!focus || keys.includes(focus)) {
        const pairKey=keys.join('/'), p=pairs.get(pairKey) || {keys,count:0,minMs:Infinity,maxMs:0};
        p.count++; p.minMs=Math.min(p.minMs,e.t-previous.t); p.maxMs=Math.max(p.maxMs,e.t-previous.t);
        pairs.set(pairKey,p);
      }
    }
    previous={key,channel:m.channel,t:e.t};
  }
  const comparable=reference && !session.synthetic && !reference.synthetic &&
    session.captureStatus !== 'partial' && reference.captureStatus !== 'partial' &&
    !!session.exercise && session.exercise === reference.exercise;
  const old=new Map(reference ? summarize(reference,Infinity,focus).notes.map(n => [`${n.channel}:${n.note}`,n]) : []);
  const notes=stats.notes.map(n => {
    const key=`${n.channel}:${n.note}`, c=counts.get(key), before=old.get(key);
    const sufficient=n.hits >= 20;
    const observations=[`${n.hits} received hits; velocity ${n.min}-${n.max}, mean ${n.mean.toFixed(1)}.`,
      `${c.top}/${n.hits} hits at velocity 120-127; ${c.rapid} same-note intervals at most 30 ms (${c.zeroGap} at identical timestamps).`];
    const next=[];
    if (!sufficient) next.push('Collect at least 20 separate hits on this pad for a repeatable review. This is a practical minimum, not statistical confidence.');
    else if (session.captureStatus === 'partial') next.push('Repeat a complete take before drawing conclusions; this capture may be missing events.');
    else {
      if (c.top/n.hits >= .25) next.push('Many hits are near the top of the MIDI range. Repeat soft and firm single-hit exercises; if soft playing also reaches the top, compare the module velocity curve and sensitivity with its manual. No setting value is inferred here.');
      if (c.rapid >= 3) next.push(session.exercise === 'rolls' ?
        'Short intervals are expected in rolls. Use separate single hits to investigate unwanted repeats.' :
        'Repeat slow, separate single hits and listen for unwanted repeats. These intervals can also be flams, rolls or duplicate routing; confirm what you played before changing retrigger settings.');
      if (!next.length) next.push('No review threshold was crossed. This does not prove trigger health; compare another take with the same pad and playing exercise.');
    }
    let comparison='Choose a saved reference with the same exercise and channel/note for a controlled comparison.';
    if (reference) {
      comparison=before ? `Current/reference hits: ${n.hits}/${before.hits}; mean velocity change ${(n.mean-before.mean).toFixed(1)}. ` : 'This channel/note is absent from the reference. ';
      comparison+=comparable && sufficient && before?.hits >= 20 ?
        'Both takes meet the 20-hit review minimum. Confirm the same physical pad, technique and routing; this is not an improvement score.' :
        'Exploratory comparison only: use complete, non-demo takes with the same selected exercise and at least 20 hits each. Exercise selection does not prove how either take was played.';
    }
    return {key,label:padLabel(session.padMap,n.channel,n.note),hits:n.hits,sufficient,...c,observations,next,comparison};
  });
  const correlations=[...pairs.values()].filter(p => p.count >= 3).sort((a,b) => b.count-a.count || a.keys.join().localeCompare(b.keys.join()));
  return {notes,correlations,scope:session.synthetic ? 'Synthetic demo: illustrates review prompts, not hardware evidence.' :
    session.captureStatus === 'partial' ? 'Partial take: received events only; repeat a complete take before diagnosis.' :
      'Recorded/imported MIDI: observations depend on playing, routing and timestamp accuracy.',
    limits:'20 hits is a review minimum, not statistical confidence. Timing windows (30 ms repeats, 12 ms adjacent different notes) are review heuristics, not fault thresholds. Pause boundaries are never crossed. MIDI alone cannot prove missed physical hits, crosstalk or faulty settings. No module settings are written.'};
}
export function coachReport(session, reference=null, focus='') {
  const review=triggerAdvice(session,reference,focus), lines=['Trigger Coach — observations and next checks',review.scope,review.limits];
  if (!review.notes.length) lines.push('No note-on hits in this analysis focus.');
  for (const n of review.notes) lines.push('',`${n.key}${n.label ? ' ['+n.label+']' : ''} — ${n.sufficient ? '20-hit review minimum met' : 'More hits needed'}`,...n.observations,...n.next,n.comparison);
  lines.push('', 'Adjacent different-note events (same channel, at most 12 ms; at least 3 occurrences):');
  for (const p of review.correlations.slice(0,20)) lines.push(`${p.keys.join(' + ')}: ${p.count} adjacent pairs, gap ${p.minMs.toFixed(1)}-${p.maxMs.toFixed(1)} ms. Intentional simultaneous playing and multiple zones can do this. Repeat an isolated-pad exercise and check routing before considering crosstalk settings.`);
  if (!review.correlations.length) lines.push('None met this review threshold; this does not rule out crosstalk.');
  if (review.correlations.length > 20) lines.push(`Showing 20 of ${review.correlations.length} candidate pairs; narrow the analysis focus for others.`);
  return lines.join('\n');
}
export function exportCSV(session) {
  const rows = [['time_ms', 'segment', 'type', 'channel', 'data_1', 'data_2', 'input', 'synthetic', 'capture_status', 'pad_name']];
  let segment=0;
  for (const [index,e] of session.events.entries()) {
    while (index >= (session.segments?.[segment+1] ?? Infinity)) segment++;
    const m = message(e.data);
    rows.push([e.t, segment+1, m.type, m.channel, e.data[1], e.data[2] ?? '', session.source, session.synthetic, session.captureStatus || 'complete', [8,9,10].includes(m.kind) ? padLabel(session.padMap,m.channel,e.data[1]) : '']);
  }
  return rows.map(r => r.map(csvCell).join(',')).join('\r\n');
}
export function report(session, reference=null, focus='') {
  const s = summarize(session,Infinity,focus);
  const lines = ['Drum MIDI session report', session.name, `Input: ${session.source}`, `Created: ${session.createdAt}`,
    `Source: ${session.synthetic ? 'Synthetic demo' : 'Recorded/imported MIDI'}`, `Active duration: ${(session.durationMs/1000).toFixed(2)} s`,
    `Capture status: ${session.captureStatus || 'complete'} (partial takes may be missing MIDI events)`,
    `Analysis focus: ${focus ? 'channel:note '+focus : 'all channel messages'}; full-take duration retained`,
    `Tags: ${(session.tags || []).join(', ') || 'None'}`,
    `Notes: ${session.notesText || 'None'}`,
    `Exercise: ${EXERCISES[session.exercise]?.name || 'Free capture'} (user-selected; completion is not measured)`,
    ...(EXERCISES[session.exercise] ? ['Instructions: '+EXERCISES[session.exercise].prompt] : []),
    `Pad profile: ${session.padMap?.name || 'None'} (user-assigned names)`,
    `Channel messages: ${s.count}; note-on hits: ${s.hits}`, '', 'Channel / note: hits, mean velocity, range, standard deviation, shortest repeated-note interval'];
  for (const n of s.notes) lines.push(`Ch ${n.channel} / ${n.note}${padLabel(session.padMap,n.channel,n.note) ? ' ['+padLabel(session.padMap,n.channel,n.note)+']' : ''}: ${n.hits}, ${n.mean.toFixed(1)}, ${n.min}–${n.max}, ${n.std.toFixed(1)}, ${n.minGapMs === null ? 'n/a' : n.minGapMs.toFixed(1)+' ms'}`);
  for (const c of s.controllers) lines.push(`Ch ${c.channel} CC ${c.controller}: ${c.count} messages, range ${c.min}–${c.max}, last ${c.last}`);
  if (reference) {
    lines.push('', `Comparison with: ${reference.name} (${(reference.durationMs/1000).toFixed(2)} s${reference.synthetic ? ', synthetic demo' : ''}${reference.captureStatus === 'partial' ? ', partial take' : ''})`, 'Channel:note — mean velocity change (current minus reference)');
    for (const r of compare(session, reference,focus)) lines.push(`${r.key} [current: ${padLabel(session.padMap,...r.key.split(':').map(Number)) || 'unnamed'}; reference: ${padLabel(reference.padMap,...r.key.split(':').map(Number)) || 'unnamed'}]: ${r.current && r.reference ? (r.current.mean-r.reference.mean).toFixed(1) : 'not present in both captures'}`);
  }
  lines.push('', coachReport(session,reference,focus), '', 'Velocity is MIDI data, not measured audio loudness. Pause gaps are excluded from captured time.',
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
