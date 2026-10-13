import {MAX_EVENTS, MAX_DURATION, MAX_FILE_BYTES, newSession, validateSession, message, summarize, compare, demoSession, exportCSV, report} from './core.js';
import {listSessions, readSession, saveSession, deleteSession} from './storage.js';
import {HostTake} from './host.js';
import {PadProfiles} from './profile-ui.js';
import {padLabel} from './profiles.js';
const $ = id => document.getElementById(id);
let current = newSession(), savedId = null, dirty = false, mode = 'ready', access = null, selected = null;
let elapsed = 0, started = 0, playhead = 0, playing = false, playStart = 0, playFrom = 0, reference = null;
let lastDraw = 0, drawNeeded = true, storageBusy = false;
const setStatus = (text, error=false) => { $('status').textContent=text; $('status').classList.toggle('error', error); };
const active = () => ['recording','paused','syncing'].includes(mode);
const hostMode = () => $('capture-source').value === 'host';
const hostAvailable = document.documentElement.dataset.hostMidi === 'true';
let profiles=null;
const host = new HostTake((session, state) => {
  if (session) {
    const name=current.name, padMap=current.padMap, offset=current.events.length;
    current={...session, ...(padMap ? {padMap} : {})};
    if (state === 'recording' && mode === 'recording') profiles?.consume(current.events.slice(offset));
    savedId=null; dirty=true;
    if (name !== 'Untitled capture') current.name=name;
    $('name').value=current.name; elapsed=current.durationMs; playhead=current.durationMs;
    $('seek').max=String(Math.max(1,current.durationMs));
  }
  if (state) mode=['recording','paused','syncing'].includes(state) ? state : 'ready';
  drawNeeded=true; controls();
  if (state && state !== 'recording') render();
},setStatus);
const time = () => Math.min(MAX_DURATION, elapsed + (mode === 'recording' ? performance.now()-started : 0));
function controls() {
  const busy=storageBusy || host.busy, held=hostMode() && !!host.id;
  $('record').disabled = active() || !selected || selected.state !== 'connected' || busy || held;
  $('pause').disabled = !['recording','paused'].includes(mode) || busy;
  const pauseLabel=mode === 'paused' ? 'Resume' : 'Pause';
  if ($('pause').textContent !== pauseLabel) $('pause').textContent=pauseLabel;
  $('stop').disabled = !active() || busy; $('connect').disabled = active() || busy || held;
  $('input').disabled = active() || (!hostMode() && !access) || busy || held;
  $('capture-source').disabled=active() || busy || held;
  for (const id of ['demo','import']) $(id).disabled = active() || busy || held;
  for (const id of ['save','json','csv','report','play','seek']) $(id).disabled = active() || !current.events.length || busy;
  $('compare').disabled = active() || storageBusy;
  $('name').disabled = storageBusy;
  $('state').textContent = mode === 'syncing' ? 'Receiving host take' : mode === 'recording' ? 'Recording' : mode === 'paused' ? 'Paused' : dirty ? 'Not saved' : savedId ? 'Saved in this browser' : 'Ready';
  const playLabel=playing ? 'Pause replay' : 'Replay visually';
  if ($('play').textContent !== playLabel) $('play').textContent=playLabel;
  for (const b of $('sessions').querySelectorAll('button')) b.disabled = active() || busy || held;
  $('host-recovery').hidden=!held;
  $('host-recover').disabled=busy || active();
  $('host-release').disabled=busy || active() || !host.connected;
  $('host-forget').disabled=busy || active() || host.connected;
  $('setup-check').disabled=busy || active() || held;
  profiles?.controls(mode,busy);
}
async function confirmAction(text, title='Replace this session?') {
  $('confirm-title').textContent=title;
  $('confirm-text').textContent=text; $('confirm').returnValue='cancel'; $('confirm').showModal();
  return new Promise(resolve => { $('confirm').addEventListener('close', () => resolve($('confirm').returnValue === 'ok'), {once:true}); });
}
async function canReplace() { return !dirty || await confirmAction('This session has changes that are not saved. Save or export it first to keep them, or continue to replace it.'); }
async function replaceSession(loader, id=null, notice='Session loaded.') {
  if (active() || storageBusy) return;
  storageBusy=true; controls();
  try {
    const session=validateSession(await loader());
    if (await canReplace()) { useSession(session,id); setStatus(notice); }
  } catch (e) { setStatus(e.message,true); }
  finally { storageBusy=false; controls(); }
}
function useSession(session, id=null) {
  current = validateSession(session); profiles.unsaved=false; profiles.refresh(); savedId=id; dirty=!id; mode='ready'; playing=false; playhead=0; elapsed=current.durationMs;
  $('name').value=current.name; $('seek').max=String(Math.max(1,current.durationMs)); $('seek').value='0';
  drawNeeded=true; controls(); render();
}
function onMessage(event) {
  if (mode !== 'recording') return;
  const parsed = message(event.data);
  if (!parsed) return;
  const stamp=event.timeStamp, now=performance.now();
  const usableStamp=Number.isFinite(stamp) && stamp >= 0 && stamp <= now+100;
  if (usableStamp && stamp < started) return; // queued before Record/Resume
  const t = Math.max(current.events.at(-1)?.t || 0, usableStamp ? elapsed+stamp-started : time());
  if (current.events.length >= MAX_EVENTS || t >= MAX_DURATION) { stopCapture('Capture limit reached. Save or export this session.'); return; }
  current.events.push({t:Math.round(t*1000)/1000, data:parsed.bytes});
  profiles.consume(current.events.slice(-1));
  current.durationMs=Math.max(t, current.events.at(-1).t); dirty=true; drawNeeded=true;
  if (current.events.length === MAX_EVENTS) stopCapture('Capture limit reached. Save or export this session.');
}
function stopCapture(reason='Capture stopped. Save this session or export a copy.') {
  elapsed=time(); current.durationMs=Math.max(elapsed,current.events.at(-1)?.t || 0);
  mode='ready'; dirty=true; playhead=current.durationMs; $('seek').max=String(Math.max(1,current.durationMs));
  drawNeeded=true; controls(); render(); setStatus(reason);
}
function inputsChanged() {
  if (hostMode()) return;
  let disconnected = false;
  if (selected && selected.state === 'disconnected') {
    disconnected = true;
    if (active()) stopCapture('MIDI input disconnected. The captured events are kept; reconnect and start a new take.');
    selected.removeEventListener('midimessage', onMessage); selected=null;
  }
  const chosen = selected?.id || $('input').value;
  $('input').replaceChildren(new Option('Choose a MIDI input', ''));
  for (const input of access.inputs.values()) if (input.state === 'connected') $('input').add(new Option(input.name || 'Unnamed MIDI input', input.id));
  $('input').value=chosen; controls();
  if (!active() && !disconnected) setStatus($('input').options.length > 1 ? 'Choose an input, then Record. Capture stays in this browser.' : 'No MIDI inputs found. Connect a module or MIDI interface; this list updates automatically.');
}
$('connect').onclick=async () => {
  if (storageBusy) return;
  storageBusy=true; controls();
  $('connect').disabled=true;
  try {
    if (hostMode()) {
      const inputs=await host.inputs();
      $('input').replaceChildren(new Option('Choose a host MIDI input',''));
      for (const port of inputs) $('input').add(new Option(port.name,port.id));
      selected=null;
      setStatus(inputs.length ? 'Choose the input plugged into the Wi-Fi host, then Record.' : 'No host MIDI inputs found. Connect the module to the host, then refresh inputs.');
      return;
    }
    if (!navigator.requestMIDIAccess || !window.isSecureContext) throw new Error('Live MIDI is unavailable here. Use a supporting browser on the USB computer at localhost. Import JSON or try the demo on this device.');
    if (!access) { access=await navigator.requestMIDIAccess({sysex:false}); access.addEventListener('statechange',inputsChanged); }
    inputsChanged();
  } catch (e) { setStatus('MIDI connection failed: '+e.message, true); }
  finally { storageBusy=false; controls(); }
};
$('input').onchange=() => {
  if (selected?.removeEventListener) selected.removeEventListener('midimessage',onMessage);
  if (hostMode()) { selected=$('input').value ? {id:$('input').value,state:'connected'} : null; controls(); return; }
  selected=access?.inputs.get($('input').value) || null;
  if (selected) selected.addEventListener('midimessage',onMessage);
  controls();
};
$('record').onclick=async () => {
  if (!selected || selected.state !== 'connected' || (current.events.length && !await canReplace())) return;
  const padMap=current.padMap ? structuredClone(current.padMap) : undefined;
  profiles.cancel();
  if (hostMode()) {
    current={...newSession(), ...(padMap ? {padMap} : {})}; savedId=null; dirty=true; reference=null; playing=false; $('compare').value='';
    await host.start(selected.id); return;
  }
  current={...newSession('Capture '+new Date().toLocaleTimeString(),(selected.name || 'Unnamed MIDI input').slice(0,160)), ...(padMap ? {padMap} : {})};
  savedId=null; dirty=true; reference=null; $('compare').value=''; elapsed=0; started=performance.now(); mode='recording'; playing=false; playhead=0;
  $('name').value=current.name; drawNeeded=true; controls(); render(); setStatus('Recording channel messages. Hit a pad to see its note and velocity.');
};
$('pause').onclick=() => {
  if (hostMode()) { void host.command(mode === 'paused' ? 'resume' : 'pause'); return; }
  if (mode === 'recording') { elapsed=time(); mode='paused'; current.durationMs=Math.max(elapsed,current.events.at(-1)?.t || 0); setStatus('Paused. Incoming MIDI is ignored until you resume.'); }
  else if (mode === 'paused') {
    if (current.segments.at(-1) !== current.events.length) current.segments.push(current.events.length);
    started=performance.now(); mode='recording'; setStatus('Recording resumed. The pause gap is excluded.');
  }
  controls(); drawNeeded=true;
};
$('stop').onclick=() => hostMode() ? void host.command('stop') : stopCapture();
$('host-recover').onclick=() => { playing=false; void host.command('poll'); };
$('host-release').onclick=async () => {
  if (await confirmAction('Release the temporary copy on the host? Events received in this page remain available to save or export.', 'Release host copy?')) await host.command('discard');
};
$('host-forget').onclick=async () => {
  if (await confirmAction('Forget this connection? Keep the received events here. An unreachable host may still hold its take until it expires; this does not stop or delete it remotely.', 'Forget host connection?')) host.forget();
};
function captureSupport() {
  $('setup-panel').hidden=!hostMode();
  const liveAvailable=!!navigator.requestMIDIAccess && window.isSecureContext;
  $('support').textContent=hostMode() ? 'Plug the module into the host computer. Host timestamps keep Wi-Fi delay out of the measurements. Hiding this page stops capture; recover it when you return.' :
    liveAvailable ? 'Connect a MIDI input on this computer. No kit needs to be loaded.' : 'Live MIDI is unavailable in this browser/context. Use the Wi-Fi host option on a paired page, or import JSON here.';
  $('connect').hidden=!hostMode() && !liveAvailable;
  $('connect').textContent=hostMode() ? 'Refresh host inputs' : 'Connect MIDI input';
}
$('capture-source').onchange=() => {
  if (selected?.removeEventListener) selected.removeEventListener('midimessage',onMessage);
  selected=null; $('input').replaceChildren(new Option('No input selected','')); captureSupport(); controls();
};
$('name').oninput=() => { current.name=$('name').value.trim() || 'Untitled capture'; dirty=true; controls(); };
$('demo').onclick=() => replaceSession(demoSession,null,'Synthetic demo loaded. Save it to compare with another session.');
$('import').onchange=async () => {
  const file=$('import').files[0]; $('import').value=''; if (!file) return;
  await replaceSession(async () => {
    if (file.size > MAX_FILE_BYTES) throw new Error('File is too large (maximum 8 MB).');
    return JSON.parse(await file.text());
  },null,'Imported locally. Save this session to keep it in this browser.');
};
async function refreshSaved() {
  try {
    const sessions=await listSessions(), compareId=$('compare').value;
    $('sessions').replaceChildren(); $('compare').replaceChildren(new Option('Choose a reference', ''));
    for (const item of sessions) {
      const row=document.createElement('div'); row.className='session';
      const open=document.createElement('button'); open.textContent=item.name;
      open.onclick=() => replaceSession(() => readSession(item.id),item.id,'Saved session loaded.');
      const meta=document.createElement('small'); meta.textContent=`${item.count.toLocaleString()} messages${item.synthetic ? ' · Synthetic demo' : ''}${item.captureStatus === 'partial' ? ' · Partial take' : ''}`;
      const remove=document.createElement('button'); remove.className='delete'; remove.textContent='Delete'; remove.setAttribute('aria-label','Delete '+item.name);
      remove.onclick=async () => {
        if (!await confirmAction(`Delete “${item.name}” from this browser? Export it first if you need a backup.`, 'Delete saved session?')) return;
        try { await deleteSession(item.id); if (savedId === item.id) { savedId=null; dirty=true; } if ($('compare').value === item.id) reference=null; await refreshSaved(); render(); }
        catch (e) { setStatus('Could not delete: '+e.message,true); }
      };
      row.append(open,meta,remove); $('sessions').append(row); $('compare').add(new Option(item.name,item.id));
    }
    if (!sessions.length) $('sessions').textContent='No saved sessions yet.';
    $('compare').value=compareId; controls();
  } catch (e) { setStatus('Browser storage is unavailable. You can still capture/import and export JSON. '+e.message,true); }
}
$('save').onclick=async () => {
  storageBusy=true; controls();
  try { savedId=await saveSession(current,savedId); dirty=false; await refreshSaved(); setStatus('Saved in this browser. Export JSON to keep a portable backup.'); }
  catch (e) { setStatus('Session was not saved. Export JSON to keep it. '+e.message,true); }
  finally { storageBusy=false; controls(); }
};
$('compare').onchange=async () => {
  const id=$('compare').value;
  try { const loaded=id ? await readSession(id) : null; if ($('compare').value === id) { reference=loaded; renderComparison(); } }
  catch (e) { reference=null; renderComparison(); setStatus(e.message,true); }
};
function download(body,type,suffix) {
  const link=document.createElement('a'), url=URL.createObjectURL(new Blob([body],{type}));
  link.href=url; link.download=(current.name.replace(/[^a-z0-9 _-]/gi,'_').slice(0,80) || 'midi-session')+suffix;
  link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
$('json').onclick=() => download(JSON.stringify(validateSession(current),null,2),'application/json','.json');
$('csv').onclick=() => download(exportCSV(current),'text/csv;charset=utf-8','.csv');
$('report').onclick=() => download(report(current,reference),'text/plain;charset=utf-8','-report.txt');
function stopReplay() { playing=false; controls(); }
$('play').onclick=() => {
  if (playing) { stopReplay(); return; }
  if (playhead >= current.durationMs) playhead=0;
  playFrom=playhead; playStart=performance.now(); playing=true; controls();
};
$('seek').oninput=() => { stopReplay(); playhead=Number($('seek').value); renderPlayhead(); };
$('speed').onchange=() => { playFrom=playhead; playStart=performance.now(); };
function cell(row,text,tag='td') { const el=document.createElement(tag); el.textContent=String(text); row.append(el); }
function renderComparison() {
  $('comparison').replaceChildren();
  if (!reference) { $('comparison').textContent='Save another capture to compare the same channel and note.'; return; }
  const table=document.createElement('table'), caption=document.createElement('caption');
  caption.textContent=`Reference: ${reference.name} · ${(reference.durationMs/1000).toFixed(2)} s${reference.synthetic ? ' · Synthetic demo' : ''}${reference.captureStatus === 'partial' ? ' · Partial take' : ''}`; table.append(caption);
  const head=document.createElement('tr'); ['Channel / note · current / reference names','Current hits','Reference hits','Mean velocity change'].forEach(t => cell(head,t,'th')); table.append(head);
  const pairs=compare(current,reference);
  for (const r of pairs.slice(0,128)) {
    const row=document.createElement('tr'); [`${r.key} · ${padLabel(current.padMap,...r.key.split(':').map(Number)) || 'unnamed'} / ${padLabel(reference.padMap,...r.key.split(':').map(Number)) || 'unnamed'}`,r.current?.hits ?? '—',r.reference?.hits ?? '—',r.current && r.reference ? (r.current.mean-r.reference.mean).toFixed(1) : 'Not in both'].forEach(t => cell(row,t)); table.append(row);
  }
  $('comparison').append(table);
  if (pairs.length > 128) {
    const note=document.createElement('p'); note.textContent='Showing the first 128 channel/note pairs; export the report for all.'; $('comparison').append(note);
  }
}
function renderPlayhead() {
  $('seek').value=String(playhead); $('cursor-time').textContent=(playhead/1000).toFixed(2)+' s';
  const line=$('play-line'); if (line) { const x=40+($('timeline').viewBox.baseVal.width-60)*playhead/Math.max(1,current.durationMs); line.setAttribute('x1',x); line.setAttribute('x2',x); }
  const events=current.events.filter(e => e.t <= playhead).slice(-6);
  $('replay-events').textContent=events.length ? events.map(e => {
    const m=message(e.data); return `${(e.t/1000).toFixed(3)} s   Ch ${m.channel}   ${m.type}   ${e.data.slice(1).join(' / ')}${[8,9,10].includes(m.kind) && padLabel(current.padMap,m.channel,e.data[1]) ? '   '+padLabel(current.padMap,m.channel,e.data[1]) : ''}`;
  }).join('\n') : 'No events at this position.';
}
function render() {
  const stats=summarize(current);
  $('hits').textContent=stats.hits.toLocaleString(); $('events').textContent=current.events.length.toLocaleString();
  $('notes').textContent=String(stats.notes.length); $('duration').textContent=(current.durationMs/1000).toFixed(2)+' s';
  $('origin').textContent=current.events.length ? `${current.captureStatus === 'partial' ? 'Partial take · ' : ''}${current.synthetic ? 'Synthetic demo · ' : ''}${current.source} · ${current.createdAt}` : 'No events yet. Record an input, import a JSON session, or try the demo.';
  const svg=$('timeline'); svg.replaceChildren(); const ns='http://www.w3.org/2000/svg';
  const width=Math.max(260,svg.clientWidth), right=width-20;
  svg.setAttribute('viewBox',`0 0 ${width} 180`);
  const add=(tag,attrs) => { const e=document.createElementNS(ns,tag); for (const [k,v] of Object.entries(attrs)) e.setAttribute(k,String(v)); svg.append(e); return e; };
  for (const v of [1,32,64,96,127]) {
    add('line',{x1:40,x2:right,y1:160-v,y2:160-v,stroke:'#29352b','stroke-width':1});
    add('text',{x:5,y:164-v,fill:'#aab3a8','font-size':11}).textContent=v;
  }
  add('text',{x:40,y:176,fill:'#aab3a8','font-size':11}).textContent='0 s';
  add('text',{x:right,y:176,fill:'#aab3a8','font-size':11,'text-anchor':'end'}).textContent=(current.durationMs/1000).toFixed(2)+' s';
  const hits=current.events.filter(e => message(e.data)?.type === 'Note on'), stride=Math.max(1,Math.ceil(hits.length/1000));
  for (let i=0;i<hits.length;i+=stride) {
    const dot=add('circle',{cx:40+hits[i].t/Math.max(1,current.durationMs)*(right-40),cy:160-hits[i].data[2],r:2.8,fill:'#d8b567',opacity:.8});
    const title=document.createElementNS(ns,'title'); title.textContent=`Ch ${(hits[i].data[0]&15)+1}, note ${hits[i].data[1]}, velocity ${hits[i].data[2]} at ${(hits[i].t/1000).toFixed(3)} s`; dot.append(title);
  }
  add('line',{id:'play-line',x1:40,x2:40,y1:10,y2:160,stroke:'#87bc96','stroke-width':2});
  $('histogram').replaceChildren(); const high=Math.max(1,...stats.histogram);
  stats.histogram.forEach((count,i) => { const bar=document.createElement('div'); bar.style.height=(count/high*100)+'%'; bar.title=`Velocity ${Math.max(1,i*8)}–${i*8+7}: ${count} hits`; const n=document.createElement('span'); n.textContent=count || ''; bar.append(n); $('histogram').append(bar); });
  $('histogram').setAttribute('aria-label',stats.histogram.map((n,i) => `Velocity ${Math.max(1,i*8)} to ${i*8+7}: ${n} hits`).join('; '));
  $('note-rows').replaceChildren();
  for (const n of stats.notes.slice(0,128)) { const row=document.createElement('tr'); [`${n.channel} / ${n.note}${padLabel(current.padMap,n.channel,n.note) ? ' · '+padLabel(current.padMap,n.channel,n.note) : ''}`,n.hits,n.mean.toFixed(1),`${n.min}–${n.max}`,n.std.toFixed(1),n.minGapMs === null ? '—' : n.minGapMs.toFixed(1)+' ms'].forEach(t => cell(row,t)); $('note-rows').append(row); }
  $('table-note').textContent=(stats.notes.length > 128 ? 'Showing the first 128 channel/note pairs; export a report for all. ' : '')+'Note numbers do not identify physical pads. Short gaps may be intentional playing.';
  $('controllers').textContent=stats.controllers.length ? stats.controllers.slice(0,128).map(c => `Ch ${c.channel} CC ${c.controller}: ${c.count} messages · ${c.min}–${c.max} · last ${c.last}`).join('\n') : 'None observed.';
  if (stats.controllers.length > 128) $('controllers').textContent+='\nShowing the first 128 pairs; export the report for all.';
  renderPlayhead(); renderComparison(); controls(); drawNeeded=false;
}
setInterval(() => {
  const now=performance.now();
  if (mode === 'recording' && !hostMode()) { current.durationMs=time(); playhead=current.durationMs; drawNeeded=true; if (current.durationMs >= MAX_DURATION) stopCapture('20-minute capture limit reached. Save or export this session.'); }
  if (playing) { playhead=Math.min(current.durationMs,playFrom+(now-playStart)*Number($('speed').value)); renderPlayhead(); if (playhead >= current.durationMs) stopReplay(); }
  if (drawNeeded && now-lastDraw >= 500) { lastDraw=now; render(); }
},100);
window.addEventListener('resize',() => { drawNeeded=true; });
window.addEventListener('beforeunload',e => { if (dirty || active()) { e.preventDefault(); e.returnValue=''; } });
$('host-option').hidden=!hostAvailable;
if (hostAvailable) $('capture-source').value='host';
document.addEventListener('visibilitychange',() => { if (document.hidden && hostMode()) host.suspend(); });
window.addEventListener('pagehide',() => { if (hostMode()) host.suspend(); });
profiles=new PadProfiles(() => current, padMap => { current.padMap=padMap; dirty=true; drawNeeded=true; controls(); },confirmAction,download);
let setupReport=null;
$('setup-check').onclick=async () => {
  storageBusy=true; controls(); $('setup-result').textContent='Checking the host MIDI environment…'; $('setup-export').disabled=true;
  try {
    setupReport=await host.fetch('/wifi/midi/setup');
    $('setup-result').textContent=`${setupReport.message}\n${setupReport.system} · Python ${setupReport.python} · python-rtmidi ${setupReport.package || 'not installed'}\n${setupReport.inputs.length} input(s) visible${setupReport.inputs.length ? ': '+setupReport.inputs.map(p => p.name).join(', ') : ''}${setupReport.detail ? '\n'+setupReport.detail : ''}`;
    $('setup-export').disabled=false;
  } catch (e) { setupReport=null; $('setup-result').textContent='Host setup check failed: '+e.message+' Check that the host is running and this browser is still paired.'; }
  finally { storageBusy=false; controls(); }
};
$('setup-export').onclick=() => { if (setupReport) download(JSON.stringify(setupReport,null,2),'application/json','-host-setup.json'); };
captureSupport();
render(); void refreshSaved();
if (hostAvailable && host.id) setStatus('A host take may be available from this tab. Choose Recover host take to retrieve it.');
