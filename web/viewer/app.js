
// ── Live loop constants ───────────────────────────────────────────────────────
const LOOP_ROWS = [
  {id:'K1H', label:'KICK'},
  {id:'S1H', label:'SNARE'},
  {id:'H1B', label:'HH'},
  {id:'H1E', label:'HH-O'},
  {id:'T1H', label:'TOM 1'},
  {id:'T2H', label:'TOM 2'},
  {id:'T3H', label:'TOM 3'},
  {id:'T4H', label:'TOM 4'},
  {id:'C1B', label:'CRASH'},
  {id:'R1B', label:'RIDE'},
];

const LOOP_PRESETS = {
  simple44: {
    K1H: [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],
    S1H: [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
    H1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  metal: {
    K1H: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
    S1H: [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
    R1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  halftime: {
    K1H: [1,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
    S1H: [0,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0],
    H1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  blank: {},
};

// ── LiveLoop class ────────────────────────────────────────────────────────────
class LiveLoop {
  constructor() {
    this.ctx        = null;
    this.masterGain = null;
    this.bufCache   = {};  // sinRel → Promise<AudioBuffer|null>
    this.pattern    = {};  // padId → bool[16]
    this.muted      = new Set();
    this.bpm        = 100;
    this.curStep    = -1;
    this._step      = 0;
    this._nextTime  = 0;
    this._timer     = null;
    this.running    = false;

    // Restore persisted state
    try {
      const s = JSON.parse(localStorage.getItem('loop_state') || '{}');
      if (s.bpm)     this.bpm = s.bpm;
      if (s.pattern) this.pattern = s.pattern;
      if (s.muted)   this.muted = new Set(s.muted);
    } catch(e) {}

    // Fill any missing rows with blank arrays
    for (const row of LOOP_ROWS) {
      if (!this.pattern[row.id]) this.pattern[row.id] = Array(16).fill(0);
    }
  }

  _initCtx() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.value = parseFloat(document.getElementById('loop-vol').value || '0.8');
      this.masterGain.connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
  }

  setBpm(v) {
    this.bpm = Math.max(40, Math.min(240, v));
    this._saveState();
  }

  setVolume(v) {
    if (this.masterGain) this.masterGain.gain.value = v;
  }

  loadPattern(name, save = true) {
    const preset = LOOP_PRESETS[name] || {};
    for (const row of LOOP_ROWS) {
      this.pattern[row.id] = (preset[row.id] || Array(16).fill(0)).slice();
    }
    if (save) this._saveState();
    renderLoopGrid();
  }

  toggleStep(padId, step) {
    if (!this.pattern[padId]) this.pattern[padId] = Array(16).fill(0);
    this.pattern[padId][step] ^= 1;
    this._saveState();
    renderLoopGrid();
  }

  toggleMute(padId) {
    if (this.muted.has(padId)) this.muted.delete(padId);
    else this.muted.add(padId);
    this._saveState();
    renderLoopGrid();
  }

  start() {
    this._initCtx();
    this._step     = 0;
    this._nextTime = this.ctx.currentTime + 0.05;
    this.running   = true;
    this._schedule();
    this._timer = setInterval(() => this._schedule(), 25);
    document.getElementById('loop-play-btn').classList.add('playing');
    document.getElementById('loop-play-btn').innerHTML = '&#9632; Stop';
    if (pads.length) this.prefetchAll();
  }

  stop() {
    this.running = false;
    clearInterval(this._timer);
    this._timer  = null;
    this.curStep = -1;
    const btn = document.getElementById('loop-play-btn');
    if (btn) { btn.classList.remove('playing'); btn.innerHTML = '&#9654; Play'; }
    renderLoopGrid();
  }

  _schedule() {
    const LOOKAHEAD = 0.1;
    while (this.running && this._nextTime < this.ctx.currentTime + LOOKAHEAD) {
      this._fireStep(this._step, this._nextTime);
      this._nextTime += 60 / this.bpm / 4;
      this._step = (this._step + 1) % 16;
    }
  }

  _fireStep(step, when) {
    // Schedule visual indicator
    const delay = Math.max(0, (when - this.ctx.currentTime) * 1000 - 15);
    setTimeout(() => { this.curStep = step; renderLoopStepHighlight(); }, delay);

    for (const row of LOOP_ROWS) {
      if (!this.pattern[row.id]?.[step]) continue;
      if (this.muted.has(row.id)) continue;
      const p = pads.find(pd => pd.id === row.id);
      if (!p?.layer_a_path) continue;
      const gain = (p.la_level ?? 95) / 127;
      this._play(p.layer_a_path, when, gain);
    }
  }

  _play(sinRel, when, gain) {
    this._getBuffer(sinRel).then(buf => {
      if (!buf || !this.running) return;
      const src = this.ctx.createBufferSource();
      const gn  = this.ctx.createGain();
      src.buffer = buf;
      gn.gain.value = Math.min(1, Math.max(0, gain));
      src.connect(gn);
      gn.connect(this.masterGain);
      src.start(Math.max(when, this.ctx.currentTime));
    }).catch(() => {});
  }

  _getBuffer(sinRel) {
    if (!this.bufCache[sinRel]) {
      this.bufCache[sinRel] = fetch('/api/wav?sin=' + encodeURIComponent(sinRel))
        .then(r => r.ok ? r.arrayBuffer() : null)
        .then(ab => ab ? this.ctx.decodeAudioData(ab) : null)
        .catch(() => null);
    }
    return this.bufCache[sinRel];
  }

  invalidate(sinRel) { delete this.bufCache[sinRel]; }

  prefetchAll() {
    if (!this.ctx) return;
    for (const p of pads) {
      if (p.layer_a_path) this._getBuffer(p.layer_a_path);
      if (p.layer_b_path) this._getBuffer(p.layer_b_path);
    }
  }

  _saveState() {
    try {
      localStorage.setItem('loop_state', JSON.stringify({
        bpm:     this.bpm,
        pattern: this.pattern,
        muted:   [...this.muted],
      }));
    } catch(e) {}
  }
}

let liveLoop       = null;
let loopPanelOpen  = false;
try { loopPanelOpen = localStorage.getItem('loopPanelOpen') === '1'; } catch(e) {}

function toggleLoopPanel() {
  loopPanelOpen = !loopPanelOpen;
  document.getElementById('loop-body').style.display = loopPanelOpen ? '' : 'none';
  document.getElementById('loop-toggle-arrow').textContent = loopPanelOpen ? '▾' : '▸';
  if (loopPanelOpen && !liveLoop) {
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }
  try { localStorage.setItem('loopPanelOpen', loopPanelOpen ? '1' : '0'); } catch(e) {}
}

function loopToggle() {
  if (!liveLoop) {
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }
  if (liveLoop.running) liveLoop.stop();
  else liveLoop.start();
}

function renderLoopGrid() {
  const el = document.getElementById('loop-grid');
  if (!el) return;
  el.innerHTML = LOOP_ROWS.map(row => {
    const steps   = liveLoop?.pattern[row.id] || Array(16).fill(0);
    const isMuted = liveLoop?.muted.has(row.id);
    const lblCls  = 'loop-row-lbl' + (isMuted ? ' muted' : '');
    const cells   = [];
    for (let i = 0; i < 16; i++) {
      if (i > 0 && i % 4 === 0) cells.push('<span class="loop-beat-gap"></span>');
      const on  = steps[i];
      const cur = liveLoop?.curStep === i;
      let cls = 'loop-step' + (on ? ' on' : '') + (cur ? ' cur' : '');
      cells.push(`<button class="${cls}" data-step="${i}" onclick="liveLoop.toggleStep('${row.id}',${i})"></button>`);
    }
    return `<div class="loop-row">
      <span class="${lblCls}" onclick="liveLoop&&liveLoop.toggleMute('${row.id}')" title="Click to mute">${row.label}</span>
      <div class="loop-steps">${cells.join('')}</div>
    </div>`;
  }).join('');
}

function renderLoopStepHighlight() {
  const el = document.getElementById('loop-grid');
  if (!el) return;
  el.querySelectorAll('.loop-step.cur').forEach(b => b.classList.remove('cur'));
  const idx = liveLoop?.curStep ?? -1;
  if (idx >= 0) {
    el.querySelectorAll(`.loop-step[data-step="${idx}"]`).forEach(b => b.classList.add('cur'));
  }
}

// ── Theme ─────────────────────────────────────────────────────────────────────
let themeLight = false;
try { themeLight = localStorage.getItem('strike_theme') === 'light'; } catch(e) {}
function applyTheme() {
  document.body.dataset.theme = themeLight ? 'light' : 'dark';
  const btn = document.getElementById('theme-btn');
  if (btn) { btn.title = themeLight ? 'Switch to dark' : 'Switch to light'; btn.textContent = themeLight ? '☀' : '☾'; }
}
function toggleTheme() {
  themeLight = !themeLight;
  try { localStorage.setItem('strike_theme', themeLight ? 'light' : 'dark'); } catch(e) {}
  applyTheme();
}

// ── Favorites & recently used ─────────────────────────────────────────────────
let favorites  = new Set();
let recentInst = [];
try { favorites  = new Set(JSON.parse(localStorage.getItem('strike_favorites') || '[]')); } catch(e) {}
try { recentInst = JSON.parse(localStorage.getItem('strike_recent') || '[]');            } catch(e) {}

function toggleFavorite(rel) {
  if (favorites.has(rel)) favorites.delete(rel); else favorites.add(rel);
  try { localStorage.setItem('strike_favorites', JSON.stringify([...favorites])); } catch(e) {}
  renderInstruments();
}
function addToRecent(rel) {
  recentInst = [rel, ...recentInst.filter(r => r !== rel)].slice(0, 20);
  try { localStorage.setItem('strike_recent', JSON.stringify(recentInst)); } catch(e) {}
}
function clearRecent() {
  recentInst = [];
  try { localStorage.setItem('strike_recent', '[]'); } catch(e) {}
  renderInstruments();
}

// ── Undo history labels ───────────────────────────────────────────────────────
let undoLabels   = [];
let undoHistOpen = false;

function toggleUndoHistory() {
  undoHistOpen = !undoHistOpen;
  const panel = document.getElementById('undo-hist-panel');
  if (undoHistOpen) {
    renderUndoHistory();
    panel.style.display = '';
    setTimeout(() => document.addEventListener('click', _closeUndoHistOnce, {once:true, capture:true}), 0);
  } else {
    panel.style.display = 'none';
  }
}
function _closeUndoHistOnce(e) {
  if (document.getElementById('undo-hist-panel')?.contains(e.target)) return;
  undoHistOpen = false;
  const p = document.getElementById('undo-hist-panel');
  if (p) p.style.display = 'none';
}
function renderUndoHistory() {
  const panel = document.getElementById('undo-hist-panel');
  if (!panel) return;
  if (!undoLabels.length) {
    panel.innerHTML = '<div class="undo-hist-item" style="cursor:default;color:#666;">No history</div>';
    return;
  }
  panel.innerHTML = undoLabels.map((lbl, i) =>
    `<div class="undo-hist-item" onclick="undoToStep(${i})">&#x21A9;${i > 0 ? ` (${i+1}&times;)` : ''} ${escHtml(lbl || 'Change')}</div>`
  ).join('');
}
async function undoToStep(idx) {
  document.getElementById('undo-hist-panel').style.display = 'none';
  undoHistOpen = false;
  for (let i = 0; i <= idx && undoCount > 0; i++) await undoLast();
}

// ── Instrument browser prefs ──────────────────────────────────────────────────
let instSort    = 'az';
let instMtimes  = {};
let hoverPreview = false;
let autoPreview  = false;
try { instSort     = localStorage.getItem('strike_instSort') || 'az'; } catch(e) {}
try { hoverPreview = localStorage.getItem('strike_hoverPreview') === 'true'; } catch(e) {}
try { autoPreview  = localStorage.getItem('strike_autoPreview') === 'true'; } catch(e) {}

function savePref(key, value) {
  try { localStorage.setItem('strike_' + key, String(value)); } catch(e) {}
}

let selectedPad    = null;   // {id, layer} — active assignment target
let selectedMapPad = null;   // id string — pad shown in detail panel
let selectedGroup  = null;   // group key — controls patch panel highlight + detail view

let brokenPaths   = new Set(); // sin_rel paths not found in avail
let batchMode     = false;
let batchSelected = new Set(); // pad IDs selected for batch apply

// Tags
let instTags     = {};  // {sin_rel: [tag, ...]} loaded from /api/tags
let activeTagFilter = null;  // tag string currently filtering the browser

// Drum-map zoom state (viewBox in SVG units)
const SVG_DEF_W = 700, SVG_DEF_H = 320;
let svgView = {x: 0, y: 0, w: SVG_DEF_W, h: SVG_DEF_H};
function applySvgView() {
  const svg = document.getElementById('drum-svg');
  if (svg) svg.setAttribute('viewBox', `${svgView.x} ${svgView.y} ${svgView.w} ${svgView.h}`);
}

// Layer blend preview AudioContext (shared, lazy-created)
let _blendCtx = null;

let kits           = [];
let pads           = [];
let avail          = {};
let kitName        = '';
let libSavePath    = '';
let sdSavePath     = '';
let state_kitPath  = '';
let expandedCats   = new Set();
let undoCount      = 0;

// Audio preview state
let previewAudio   = null;
let previewRel     = null;
let previewVol     = 1;
let previewVelGain = 1;
try { previewVol     = parseFloat(localStorage.getItem('strike_previewVol') ?? '1') || 1; } catch(e) {}
try { previewVelGain = (parseFloat(localStorage.getItem('strike_previewVel') ?? '127') || 127) / 127; } catch(e) {}

// ── Waveform thumbnails ───────────────────────────────────────────────────────
const _waveObserver = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (!e.isIntersecting) return;
    const canvas = e.target;
    _waveObserver.unobserve(canvas);
    if (canvas.dataset.loaded) return;
    canvas.dataset.loaded = '1';
    fetch('/api/waveform?sin=' + encodeURIComponent(canvas.dataset.sin))
      .then(r => r.json())
      .then(d => { if (d.peaks) drawWaveform(canvas, d.peaks); })
      .catch(() => {});
  });
}, {rootMargin: '120px'});

function drawWaveform(canvas, peaks) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, mid = H / 2;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#4a8060';
  ctx.lineWidth = 1;
  ctx.beginPath();
  peaks.forEach((p, i) => {
    const x = (i / peaks.length) * W;
    const h = p * mid * 0.92;
    ctx.moveTo(x, mid - h);
    ctx.lineTo(x, mid + h);
  });
  ctx.stroke();
}

function attachWaveObservers() {
  document.querySelectorAll('.waveform-canvas:not([data-loaded])').forEach(c => _waveObserver.observe(c));
}

// ── MIDI monitor ──────────────────────────────────────────────────────────────
let midiAccess  = null;
let midiActive  = false;
const midiFlashTimers = {};  // {padId: timeoutId}

async function toggleMidi() {
  if (midiActive) {
    midiActive = false;
    updateMidiBtn();
    setMsg('MIDI monitor off');
    return;
  }
  if (!navigator.requestMIDIAccess) {
    setMsg('Web MIDI requires Chrome or Edge', true);
    return;
  }
  try {
    midiAccess = await navigator.requestMIDIAccess({ sysex: false });
    midiActive = true;
    for (const input of midiAccess.inputs.values()) input.onmidimessage = handleMidiMessage;
    midiAccess.onstatechange = e => {
      if (e.port.type === 'input' && e.port.state === 'connected')
        e.port.onmidimessage = handleMidiMessage;
    };
    updateMidiBtn();
    setMsg('MIDI active — hit a pad');
  } catch(e) {
    setMsg('MIDI access denied: ' + e.message, true);
  }
}

function handleMidiMessage(e) {
  if (!midiActive || e.data.length < 3) return;
  const [status, note, velocity] = e.data;
  if ((status & 0xf0) === 0x90 && velocity > 0) {
    // Build note → pad_id map on the fly (respects user-edited MIDI notes)
    let matched = false;
    for (const p of pads) {
      if (p.midi_note === note) {
        flashPad(p.id, velocity);
        const sinRel = p.layer_a_path || p.layer_b_path;
        if (sinRel) previewInstrument(sinRel);
        matched = true;
        break;
      }
    }
    setMsg(`MIDI note ${note} vel ${velocity}${matched ? '' : ' — no pad matched'}`);
  }
}

function flashPad(padId, velocity) {
  const g = document.querySelector(`#drum-svg [data-pid="${CSS.escape(padId)}"]`);
  if (!g) return;
  // Restart animation by removing + re-adding the class
  g.classList.remove('midi-hit');
  void g.getBoundingClientRect();  // force reflow
  g.classList.add('midi-hit');
  // Remove class after animation so it can fire again on the next hit
  if (midiFlashTimers[padId]) clearTimeout(midiFlashTimers[padId]);
  midiFlashTimers[padId] = setTimeout(() => {
    g.classList.remove('midi-hit');
    delete midiFlashTimers[padId];
  }, 500);
}

function updateMidiBtn() {
  const btn = document.getElementById('midi-btn');
  if (!btn) return;
  btn.textContent = midiActive ? '● MIDI' : 'MIDI';
  btn.style.color  = midiActive ? '#00ee77' : '';
  btn.title = midiActive ? 'MIDI active — click to stop' : 'Enable MIDI monitor (Chrome/Edge only)';
}

// ── Virtual module mode ───────────────────────────────────────────────────────
// Play the kit being edited straight from the drum pads (or number keys) with no
// SD write / module reload. MIDI note-on → match pad by midi_note → resolve Layer
// A/B by velocity → play the right samples via Web Audio, honoring velocity zones,
// round-robin/random cycling, xfade, per-layer level+pan, semitone+fine pitch,
// mute-group choke (open/closed hi-hat), and Mono/Poly. Decay is APPROXIMATED with
// a gain envelope and velocity→loudness is a fixed curve; module FX and the
// velocity→filter/pitch/decay response curves are NOT simulated (see button title).
// Buffers are pre-decoded so the hit path never fetches/decodes when warm.
const VM_PRELOAD_LIMIT = 100 * 1024 * 1024;  // decode everything up front under 100 MB
const VM_KEYS = '1234567890';                // keyboard fallback → first 10 manifest pads
let vmActive     = false;
let vmManifest   = null;
let vmCtx        = null;          // one persistent AudioContext
let vmBuffers    = new Map();     // wav_url → AudioBuffer | Promise<AudioBuffer>
let vmVoices     = [];            // live voices: {padId, layer, muteGrp, gain, src}
let vmRR         = new Map();     // "padId:layer:band" → next round-robin index
let vmHH         = 127;           // last hi-hat pedal value (CC#4); 127 = fully open
let vmRev        = -1;            // last manifest rev seen (for the /api/selected poll hook)
let vmDecodeDone = 0, vmDecodeTotal = 0;
let vmMidiWired  = false;

async function toggleVirtualModule() {
  if (vmActive) { vmStop(); return; }
  let m;
  try {
    m = await (await fetch('/api/kit_playback')).json();
  } catch(e) { setMsg('Virtual module: manifest fetch failed', true); return; }
  if (!m || m.error) { setMsg('Virtual module: ' + (m && m.error || 'no kit loaded'), true); return; }
  vmManifest = m; vmRev = m.rev;
  vmActive = true;
  try {
    if (!vmCtx) vmCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (vmCtx.state === 'suspended') await vmCtx.resume();
  } catch(e) { vmActive = false; setMsg('Virtual module: no Web Audio', true); return; }
  updateVmBtn();
  vmWireMidi();
  await vmPreload();
  updateVmBtn();
}

function vmStop() {
  vmActive = false;
  for (const v of vmVoices.slice()) { try { v.src.stop(); } catch(e){} }
  vmVoices = [];
  updateVmBtn();
  setMsg('Virtual module off');
}

function updateVmBtn() {
  const btn = document.getElementById('vmod-btn');
  const wrap = document.getElementById('vm-vel-wrap');
  if (!btn) return;
  if (!vmActive) {
    btn.textContent = 'Virtual'; btn.style.color = '';
    if (wrap) wrap.style.display = 'none';
  } else if (vmDecodeTotal && vmDecodeDone < vmDecodeTotal) {
    btn.textContent = `VM ${vmDecodeDone}/${vmDecodeTotal}`; btn.style.color = '#ffb020';
    if (wrap) wrap.style.display = 'none';
  } else {
    btn.textContent = '● VM'; btn.style.color = '#00ee77';
    if (wrap) wrap.style.display = 'inline-flex';
  }
  btn.title =
    'Virtual module — play the kit being edited from the pads or number keys (1–0).\n' +
    'Simulated: velocity zones, round-robin/random, A/B xfade, level, pan, pitch, mute-group choke, Mono/Poly.\n' +
    'Approximated: decay (gain envelope), velocity loudness curve, hi-hat pedal position.\n' +
    'NOT simulated: module FX (reverb/FX1/FX2/EQ), velocity→filter/pitch/decay curves, filter, loop, gate time.';
}

function vmAllUrls() {
  const urls = new Set();
  if (vmManifest) for (const p of vmManifest.pads)
    for (const key of ['a', 'b']) {
      const lyr = p.layers[key];
      if (lyr && lyr.mappings) for (const mp of lyr.mappings) if (mp.wav_url) urls.add(mp.wav_url);
    }
  return [...urls];
}

async function vmPreload() {
  const urls = vmAllUrls();
  vmDecodeTotal = urls.length; vmDecodeDone = 0;
  if (vmManifest.total_bytes > VM_PRELOAD_LIMIT) {
    // Large kit: decode lazily on first hit; don't block the toggle.
    vmDecodeTotal = 0;
    setMsg(`Virtual module ready — lazy decode (${(vmManifest.total_bytes / 1048576) | 0} MB kit)`);
    return;
  }
  for (const u of urls) {
    if (!vmActive) return;
    try { await vmGetBuffer(u); } catch(e){}
    vmDecodeDone++;
    if (vmDecodeDone % 4 === 0) updateVmBtn();
  }
  setMsg('Virtual module ready — hit a pad or press 1–0');
}

function vmGetBuffer(url) {
  const cached = vmBuffers.get(url);
  if (cached) return Promise.resolve(cached);   // AudioBuffer or in-flight Promise
  const pr = fetch(url)
    .then(r => { if (!r.ok) throw new Error('wav ' + r.status); return r.arrayBuffer(); })
    .then(ab => vmCtx.decodeAudioData(ab))
    .then(buf => { vmBuffers.set(url, buf); return buf; })
    .catch(err => { vmBuffers.delete(url); throw err; });
  vmBuffers.set(url, pr);
  return pr;
}

// Candidate mappings for a velocity, with hi-hat pedal filtering + pedal-function exclusion.
function vmCandidates(lyr, vel) {
  let cands = lyr.mappings.filter(m =>
    m.wav_url && vel >= m.vmin && vel <= m.vmax && m.rr !== 254);  // 254 = 0xFE pedal-function
  if (cands.length > 1) {
    const hh = cands.filter(m => vmHH >= m.hh_min && vmHH <= m.hh_max);
    if (hh.length) cands = hh;   // fall back to ignoring hh ranges when nothing matches
  }
  return cands;
}

function vmPick(padId, key, cands, cycleRandom) {
  if (cands.length === 1) return cands[0];
  const sorted = cands.slice().sort((a, b) => a.rr - b.rr);
  if (cycleRandom === 1) return sorted[Math.floor(Math.random() * sorted.length)];
  const band = `${padId}:${key}:${sorted[0].vmin}-${sorted[0].vmax}`;
  const n = vmRR.get(band) || 0;
  vmRR.set(band, (n + 1) % sorted.length);
  return sorted[n % sorted.length];
}

function vmChoke(v) {
  const now = vmCtx.currentTime;
  try {
    v.gain.gain.cancelScheduledValues(now);
    v.gain.gain.setValueAtTime(v.gain.gain.value, now);
    v.gain.gain.linearRampToValueAtTime(0, now + 0.01);   // ~10 ms fade, no click
    v.src.stop(now + 0.012);
  } catch(e){}
}

// Core hit path. `pad` is a manifest pad (has .layers); `velocity` 1–127.
function vmTrigger(pad, velocity) {
  if (!vmActive || !vmCtx || !pad) return;
  const vel = Math.max(1, Math.min(127, velocity | 0));
  const dbg = { padId: pad.id, vel, layers: [] };

  // Choke live voices: any same non-zero mute group, plus this pad's own voices in Mono.
  const choked = [];
  for (const v of vmVoices.slice()) {
    if ((pad.mute_grp && v.muteGrp === pad.mute_grp) ||
        (pad.play_mode === 0 && v.padId === pad.id)) {
      vmChoke(v);
      const i = vmVoices.indexOf(v); if (i >= 0) vmVoices.splice(i, 1);
      choked.push(v.padId + ':' + v.layer);
    }
  }

  for (const key of ['a', 'b']) {
    const lyr = pad.layers[key];
    if (!lyr || lyr.error || !lyr.skt) continue;
    if (vel < lyr.skt.vel_min || vel > lyr.skt.vel_max) continue;   // layer velocity window / xfade
    const cands = vmCandidates(lyr, vel);
    if (!cands.length) { dbg.layers.push({ layer: key, mappingIdx: null, reason: 'no zone' }); continue; }
    const m = vmPick(pad.id, key, cands, lyr.cycle_random);
    const gain = (lyr.skt.level / 127) * ((lyr.sin.level || 127) / 127) * Math.pow(vel / 127, 1.5);
    const pan  = Math.max(-50, Math.min(50, (lyr.skt.pan || 0) + (lyr.sin.pan || 0))) / 50;
    const rate = Math.pow(2, ((lyr.sin.semi + lyr.skt.pitch) + (lyr.sin.fine + lyr.skt.fine) / 100) / 12);
    const decay = Math.min(lyr.skt.decay, 99);
    dbg.layers.push({ layer: key, mappingIdx: m.idx, wavUrl: m.wav_url, gain, pan, rate, decay, choked });
    vmPlay(m.wav_url, { padId: pad.id, layer: key, muteGrp: pad.mute_grp, gain, pan, rate, decay });
  }
  flashPad(pad.id, vel);
  window.vmLastHit = dbg;
}

function vmPlay(url, opt) {
  const start = (buf) => {
    if (!vmActive || !buf) return;
    const src = vmCtx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = opt.rate;
    const gain = vmCtx.createGain();
    gain.gain.value = opt.gain;
    src.connect(gain);
    if (vmCtx.createStereoPanner) {
      const pan = vmCtx.createStereoPanner();
      pan.pan.value = opt.pan;
      gain.connect(pan); pan.connect(vmCtx.destination);
    } else {
      gain.connect(vmCtx.destination);
    }
    if (opt.decay < 99) {   // approximate decay: exponential-ish tail via time constant
      const tau = 0.04 + (opt.decay / 99) * 2.5;   // 0 → ~40 ms, ~99 → ~2.5 s
      gain.gain.setTargetAtTime(0.0001, vmCtx.currentTime + 0.005, tau);
    }
    const voice = { padId: opt.padId, layer: opt.layer, muteGrp: opt.muteGrp, gain, src };
    vmVoices.push(voice);
    src.onended = () => { const i = vmVoices.indexOf(voice); if (i >= 0) vmVoices.splice(i, 1); };
    src.start();
  };
  const cached = vmBuffers.get(url);
  if (cached && !(cached instanceof Promise)) start(cached);   // warm → zero-latency
  else vmGetBuffer(url).then(start).catch(() => {});           // cold (lazy kit) → decode then play
}

function vmWireMidi() {
  if (vmMidiWired || !navigator.requestMIDIAccess) return;   // keyboard fallback works regardless
  const wire = (access) => {
    for (const input of access.inputs.values()) input.addEventListener('midimessage', vmOnMidi);
    access.addEventListener('statechange', e => {
      if (e.port.type === 'input' && e.port.state === 'connected') {
        e.port.removeEventListener('midimessage', vmOnMidi);
        e.port.addEventListener('midimessage', vmOnMidi);
      }
    });
    vmMidiWired = true;
  };
  // Reuse the monitor's MIDIAccess if present (addEventListener stacks with its onmidimessage).
  if (midiAccess) wire(midiAccess);
  else navigator.requestMIDIAccess({ sysex: false })
        .then(a => { if (!midiAccess) midiAccess = a; wire(a); })
        .catch(() => {});
}

function vmOnMidi(e) {
  if (!vmActive || !e.data || e.data.length < 2) return;
  const cmd = e.data[0] & 0xf0, d1 = e.data[1], d2 = e.data[2] || 0;
  if (cmd === 0xB0 && d1 === 4) { vmHH = d2; return; }   // CC#4 = hi-hat pedal position
  if (cmd === 0x90 && d2 > 0) {
    const pad = vmManifest && vmManifest.pads.find(p => p.midi_note === d1);
    if (pad) vmTrigger(pad, d2);
  }
}

// Keyboard fallback: number keys 1–0 fire the first 10 manifest pads at the slider velocity.
document.addEventListener('keydown', e => {
  if (!vmActive || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
  const i = VM_KEYS.indexOf(e.key);
  if (i < 0 || !vmManifest || !vmManifest.pads[i]) return;
  const velEl = document.getElementById('vm-vel');
  vmTrigger(vmManifest.pads[i], parseInt(velEl && velEl.value || '100', 10));
});

async function vmRefreshManifest() {
  try {
    const m = await (await fetch('/api/kit_playback')).json();
    if (!m || m.error) return;
    vmManifest = m;
    if (m.total_bytes <= VM_PRELOAD_LIMIT)   // warm any newly-referenced samples
      for (const u of vmAllUrls()) if (!vmBuffers.has(u)) vmGetBuffer(u).catch(() => {});
  } catch(e){}
}

// ── Trigger settings backup (SysEx over Web MIDI) ─────────────────────────────
// The module's trigger config (per-input sensitivity, scan time, xTalk, MIDI
// mapping) lives in firmware, not on the SD card. Its Send function emits it as
// one 236-byte SysEx message (F0 00 00 0E …). We capture that dump, save/load it
// as .syx, and can replay it verbatim to restore. Byte 27 = xTalk RCV is the
// only mapped field so far.
const TRIG_ALESIS_HEADER = [0xF0, 0x00, 0x00, 0x0E];
const TRIG_KNOWN_BYTES = {27: 'xTalk RCV'};
let trigAccess = null;   // MIDIAccess with sysex permission (separate from the monitor's)
let trigDump = null;     // Uint8Array — last captured or loaded dump
let trigDumpSource = ''; // 'captured' | 'loaded: <filename>'
let trigOtherMsgs = 0;   // non-Alesis SysEx seen while listening

function showTrigModal() {
  closeAllPopovers();
  renderTrigModal();
  document.getElementById('trig-modal').classList.add('open');
}

async function trigConnect() {
  if (!navigator.requestMIDIAccess) {
    setMsg('Web MIDI requires Chrome or Edge', true);
    return;
  }
  try {
    trigAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch (e) {
    setMsg('SysEx access denied: ' + e.message, true);
    return;
  }
  // addEventListener (not onmidimessage=) so we coexist with the MIDI monitor
  for (const input of trigAccess.inputs.values()) input.addEventListener('midimessage', trigOnMsg);
  trigAccess.onstatechange = e => {
    if (e.port.type === 'input' && e.port.state === 'connected') {
      e.port.removeEventListener('midimessage', trigOnMsg);
      e.port.addEventListener('midimessage', trigOnMsg);
    }
    renderTrigModal();
  };
  renderTrigModal();
  setMsg('Listening for SysEx — press Send on the module');
}

function trigOnMsg(e) {
  if (!e.data || e.data[0] !== 0xF0) return;
  const isAlesis = TRIG_ALESIS_HEADER.every((b, i) => e.data[i] === b);
  if (isAlesis && e.data[e.data.length - 1] === 0xF7) {
    trigDump = new Uint8Array(e.data);
    trigDumpSource = 'captured';
    setMsg(`Captured trigger settings dump (${trigDump.length} bytes)`);
  } else {
    trigOtherMsgs++;
  }
  renderTrigModal();
}

function trigSave() {
  if (!trigDump) return;
  const d = new Date();
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([trigDump], {type: 'application/octet-stream'}));
  a.download = `strike-trigger-settings-${stamp}.syx`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function trigLoad(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes[0] !== 0xF0 || bytes[bytes.length - 1] !== 0xF7) {
    setMsg('Not a SysEx file (must start F0 and end F7)', true);
    return;
  }
  trigDump = bytes;
  trigDumpSource = 'loaded: ' + file.name;
  renderTrigModal();
  setMsg(`Loaded ${file.name} (${bytes.length} bytes)`);
}

async function trigRestore() {
  if (!trigDump || !trigAccess) return;
  const sel = document.getElementById('trig-out-sel');
  const out = sel && trigAccess.outputs.get(sel.value);
  if (!out) { setMsg('No MIDI output selected', true); return; }
  const isAlesis = TRIG_ALESIS_HEADER.every((b, i) => trigDump[i] === b);
  const warn = isAlesis ? '' : '\n\n⚠ This dump does NOT have the Alesis header — sending it to the module is untested.';
  if (!await appConfirm(`Send ${trigDump.length} bytes of SysEx to "${out.name}"?\nThis overwrites the module's current trigger settings with the ${trigDumpSource} dump.${warn}`, 'Send')) return;
  out.send(trigDump);
  setMsg(`Sent ${trigDump.length} bytes to ${out.name}`);
}

function trigHexView(bytes) {
  const rows = [];
  for (let off = 0; off < bytes.length; off += 16) {
    const cells = [];
    for (let i = off; i < Math.min(off + 16, bytes.length); i++) {
      const h = bytes[i].toString(16).padStart(2, '0');
      cells.push(TRIG_KNOWN_BYTES[i]
        ? `<span class="known" title="byte ${i}: ${TRIG_KNOWN_BYTES[i]} = ${bytes[i]}">${h}</span>` : h);
    }
    rows.push(off.toString().padStart(4, ' ') + '  ' + cells.join(' '));
  }
  return rows.join('\n');
}

function renderTrigModal() {
  const body = document.getElementById('trig-body');
  if (!body) return;
  const connected = !!trigAccess;
  const ins  = connected ? [...trigAccess.inputs.values()] : [];
  const outs = connected ? [...trigAccess.outputs.values()] : [];
  const strikeOut = outs.find(o => /strike/i.test(o.name)) || outs[0];
  const isAlesis = trigDump && TRIG_ALESIS_HEADER.every((b, i) => trigDump[i] === b);
  body.innerHTML = `
    <div style="font-size:.74rem;color:#9ab;line-height:1.5;">
      Trigger settings (sensitivity, scan time, xTalk, trigger→MIDI mapping) live in the module's
      firmware — not on the SD card. This backs them up via MIDI SysEx and can restore them later.
      <b>Chrome/Edge only; module connected via USB.</b>
      Capture and save are read-only and always safe. <b>Restore to module is experimental</b> —
      it replays a captured dump verbatim; capture a known-good .syx backup first and only
      restore dumps taken from your own module.
    </div>
    ${!connected ? `
      <button class="btn-primary" style="margin-top:10px;align-self:flex-start;" onclick="trigConnect()">Connect MIDI (SysEx)</button>`
    : `
      <div style="font-size:.72rem;color:#88a;margin-top:8px;">
        Inputs: ${ins.length ? ins.map(i => escHtml(i.name)).join(', ') : '<span style="color:#c66;">none — is the module connected?</span>'}
      </div>
      <div style="margin-top:8px;padding:8px;background:#0d2030;border:1px solid #1a5080;border-radius:4px;font-size:.74rem;color:#aac;">
        <b>To capture:</b> on the module press <b>SAVE</b> → <b>Send</b> (trigger settings send).
        The dump appears below automatically.${trigOtherMsgs ? ` <span style="color:#667;">(${trigOtherMsgs} non-Alesis SysEx message(s) ignored)</span>` : ''}
      </div>
      ${trigDump ? `
        <div style="margin-top:10px;font-size:.74rem;">
          <b style="color:${isAlesis ? '#7c6' : '#c96'};">${isAlesis ? '✓ Alesis trigger dump' : '⚠ SysEx (non-Alesis header)'}</b>
          — ${trigDump.length} bytes, ${escHtml(trigDumpSource)}${trigDump.length !== 236 && isAlesis ? ' <span style="color:#c96;">(expected 236)</span>' : ''}
          ${isAlesis && trigDump.length > 27 ? ` · <b>xTalk RCV = ${trigDump[27]}</b> <span style="color:#667;">(byte 27 — only mapped field so far)</span>` : ''}
        </div>
        <div class="trig-hex" style="margin-top:6px;max-height:180px;overflow-y:auto;">${trigHexView(trigDump)}</div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center;">
          <button class="btn-secondary" onclick="trigSave()">&#x1F4BE; Save .syx</button>
          <select id="trig-out-sel" class="midi-select" style="max-width:200px;">
            ${outs.map(o => `<option value="${escHtml(o.id)}"${strikeOut && o.id === strikeOut.id ? ' selected' : ''}>${escHtml(o.name)}</option>`).join('')}
          </select>
          <button class="btn-primary" onclick="trigRestore()" ${outs.length ? '' : 'disabled'}>&#x2B06; Restore to module</button>
        </div>`
      : '<div style="margin-top:10px;font-size:.74rem;color:#667;">No dump captured yet.</div>'}
      <label class="btn-secondary" style="margin-top:10px;align-self:flex-start;font-size:.72rem;cursor:pointer;">
        &#x1F4C2; Load .syx file&#x2026;
        <input type="file" accept=".syx,.bin" style="display:none;" onchange="if(this.files[0])trigLoad(this.files[0]);this.value=''">
      </label>`}
    <div style="font-size:.65rem;color:#667;margin-top:8px;">Restore replays the module's own bytes verbatim — no values are modified. Editing individual settings needs the remaining ~200 bytes mapped (see PLANNED.md).</div>`;
}

function updatePlayButtons() {
  // Update all play buttons in-place without re-rendering the list (preserves scroll)
  document.querySelectorAll('.play-btn[data-rel]').forEach(btn => {
    const r = btn.getAttribute('data-rel');
    const playing = r === previewRel;
    btn.className   = 'play-btn' + (playing ? ' playing' : '');
    btn.title       = playing ? 'Stop preview' : 'Preview sound';
    btn.innerHTML   = playing ? '&#9632;' : '&#9654;';
  });
}

function previewInstrument(rel) {
  if (window.VIEWER) return;  // viewer-mode: no audio in v1 (/api/wav 404s)
  // Toggle: clicking the currently-playing instrument stops it
  if (previewAudio) {
    previewAudio.pause();
    previewAudio.src = '';
    previewAudio = null;
    const wasRel = previewRel;
    previewRel = null;
    updatePlayButtons();
    if (wasRel === rel) return;  // same item → just stop
  }
  previewRel   = rel;
  previewAudio = new Audio('/api/preview?sin=' + encodeURIComponent(rel));
  previewAudio.volume = previewVol * previewVelGain;
  previewAudio.onended = () => {
    previewAudio = null; previewRel = null; updatePlayButtons();
  };
  previewAudio.onerror = () => {
    setMsg('Preview unavailable — mount the preset SD card to enable audio', true);
    previewAudio = null; previewRel = null; updatePlayButtons();
  };
  updatePlayButtons();  // flip button to ■ immediately
  previewAudio.play().catch(() => {});
}

function stopPreview() {
  if (previewAudio) { previewAudio.pause(); previewAudio.src = ''; previewAudio = null; }
  if (previewRel) { previewRel = null; updatePlayButtons(); }
}

// Patch panel collapse state (persisted in localStorage)
let patchCollapsed = false;
try { patchCollapsed = localStorage.getItem('patchCollapsed') === '1'; } catch(e) {}
function applyPatchPanelState() {
  const panel = document.getElementById('patch-panel');
  const arrow = document.getElementById('patch-toggle-arrow');
  if (panel) panel.style.display = patchCollapsed ? 'none' : '';
  if (arrow) arrow.textContent = patchCollapsed ? '▸' : '▾';
}
function togglePatchPanel() {
  patchCollapsed = !patchCollapsed;
  try { localStorage.setItem('patchCollapsed', patchCollapsed ? '1' : '0'); } catch(e) {}
  applyPatchPanelState();
}

// Pad layout overrides persisted in localStorage: {padId: {cx?,cy?,rx?,ry?,type?,lbl?}}
let padOverrides = {};
try { padOverrides = JSON.parse(localStorage.getItem('strike_pad_overrides') || '{}'); } catch(e) {}

// Drag state
let dragState = null;  // {id, origCx, origCy, startX, startY, moved}

// ── Pad layout: [id, type, cx, cy, rx, ry, label] ──────────────────────────
// Back-to-front order so rims/edges render behind head counterparts.
const PAD_DEFS = [
  ['K1H','kick',   362,272, 76,27,'KICK'],
  ['S1R','rim',    165,208, 58,21,''],
  ['S1H','snare',  165,208, 50,18,'SNR'],
  ['T1R','rim',    262,157, 48,18,''],
  ['T1H','tom',    262,157, 41,15,'T1'],
  ['T2R','rim',    365,140, 51,19,''],
  ['T2H','tom',    365,140, 44,16,'T2'],
  ['T3R','rim',    468,155, 48,18,''],
  ['T3H','tom',    468,155, 41,15,'T3'],
  ['T4R','rim',    567,198, 60,22,''],
  ['T4H','floor',  567,198, 52,19,'T4'],
  ['H1E','cym-e',   83, 92, 55,12,''],
  ['H1B','cymbal',  83, 92, 38, 8,'HH'],
  ['H1F','hfoot',   63,293, 22, 9,'HHF'],
  ['C1E','cym-e',  210, 58, 63,13,''],
  ['C1B','cymbal', 210, 58, 43, 9,'C1'],
  ['C2E','cym-e',  380, 42, 70,14,''],
  ['C2B','cymbal', 380, 42, 47,10,'C2'],
  ['C3E','cym-e',  530, 55, 60,13,''],
  ['C3B','cymbal', 530, 55, 40, 9,'C3'],
  ['R1E','cym-e',  630, 88, 70,14,''],
  ['R1B','cymbal', 630, 88, 48,10,'RD'],
  ['R1D','bell',   630, 88, 18, 5,''],
];

// Default rx,ry per type — applied when user changes a pad's shape type
const PAD_TYPE_SIZES = {
  'kick':  [76,27], 'snare': [50,18], 'rim':   [52,20],
  'tom':   [41,15], 'floor': [52,19], 'cymbal':[45,10],
  'cym-e': [62,14], 'bell':  [18, 5], 'hfoot': [22, 9],
};

// Companion zones that must move together (share same physical position)
const PAD_COMPANIONS = {
  'S1H':['S1R'],         'S1R':['S1H'],
  'T1H':['T1R'],         'T1R':['T1H'],
  'T2H':['T2R'],         'T2R':['T2H'],
  'T3H':['T3R'],         'T3R':['T3H'],
  'T4H':['T4R'],         'T4R':['T4H'],
  'H1B':['H1E'],         'H1E':['H1B'],
  'C1B':['C1E'],         'C1E':['C1B'],
  'C2B':['C2E'],         'C2E':['C2B'],
  'C3B':['C3E'],         'C3E':['C3B'],
  'R1B':['R1E','R1D'],   'R1E':['R1B','R1D'],   'R1D':['R1E','R1B'],
};

// When you change a pad's shape type, what should each companion become?
// null = leave the companion alone (bell/hfoot never auto-change).
function companionTypeFor(mainType, compOrigType) {
  if (compOrigType === 'bell' || compOrigType === 'hfoot') return null;
  const drums = new Set(['kick','snare','tom','floor','rim']);
  if (drums.has(mainType))   return 'rim';
  if (mainType === 'cymbal') return 'cym-e';
  if (mainType === 'cym-e')  return 'cymbal';
  return null;
}

// Drum shell finishes and cymbal tones — applied as a CSS filter on the sprite <use>,
// so one drum recolors without touching the shared sprite defs. `swatch` = a representative
// colour for the picker UI. Chrome/mesh are desaturated so hue-rotate leaves them alone.
const DRUM_FINISHES = {
  'red':     {name:'Red Sparkle',    swatch:'#c22a3a', filter:''},
  'black':   {name:'Black',          swatch:'#26282e', filter:'saturate(.12) brightness(.55)'},
  'white':   {name:'White',          swatch:'#e9ebef', filter:'saturate(.16) brightness(1.75)'},
  'silver':  {name:'Silver Sparkle', swatch:'#aeb3bd', filter:'saturate(.28) brightness(1.4)'},
  'blue':    {name:'Blue Sparkle',   swatch:'#2f6fcf', filter:'hue-rotate(210deg) saturate(1.05)'},
  'green':   {name:'Emerald',        swatch:'#2b9d4c', filter:'hue-rotate(120deg) saturate(.95)'},
  'purple':  {name:'Purple',         swatch:'#7a3fcf', filter:'hue-rotate(275deg) saturate(1.05)'},
  'amber':   {name:'Amber',          swatch:'#d98a2b', filter:'hue-rotate(-28deg) saturate(1.1) brightness(1.05)'},
  'natural': {name:'Natural Wood',   swatch:'#a5713f', filter:'hue-rotate(-18deg) saturate(.55) brightness(1.15)'},
};
const CYM_FINISHES = {
  'brass':     {name:'Brass',       swatch:'#d8a932', filter:''},
  'bronze':    {name:'Dark Bronze', swatch:'#9c7526', filter:'hue-rotate(-8deg) saturate(.9) brightness(.8)'},
  'brilliant': {name:'Brilliant',   swatch:'#f0d878', filter:'saturate(.8) brightness(1.25)'},
  'black':     {name:'Black',       swatch:'#2a2c30', filter:'saturate(.15) brightness(.5)'},
};
// Which finish set applies to a pad type (hfoot = chrome, no finish).
function finishSetFor(type) {
  if (['kick','snare','tom','floor','rim'].includes(type)) return DRUM_FINISHES;
  if (['cymbal','cym-e','bell'].includes(type))            return CYM_FINISHES;
  return null;
}

const PAD_COLORS = {
  'kick':   {fill:'#16191f', stroke:'#5a6373'},
  'snare':  {fill:'#16191f', stroke:'#5f6878'},
  'rim':    {fill:'#12151c', stroke:'#49536a'},
  'tom':    {fill:'#15181f', stroke:'#525c6e'},
  'floor':  {fill:'#14171d', stroke:'#4c5566'},
  'cymbal': {fill:'#221c02', stroke:'#caa030'},
  'cym-e':  {fill:'#1a1400', stroke:'#a8841c'},
  'bell':   {fill:'#2a2002', stroke:'#ecc045'},
  'hfoot':  {fill:'#1a1408', stroke:'#8a6c1c'},
};

// GM drum note labels for the MIDI note picker
const GM_DRUMS_JS = {
  35:'Ac. Bass Dr.', 36:'Bass Drum 1', 37:'Side Stick', 38:'Ac. Snare', 39:'Hand Clap',
  40:'Elec. Snare', 41:'Lo Floor Tom', 42:'Closed HH', 43:'Hi Floor Tom', 44:'Pedal HH',
  45:'Lo Tom', 46:'Open HH', 47:'Lo-Mid Tom', 48:'Hi-Mid Tom', 49:'Crash Cym. 1',
  50:'Hi Tom', 51:'Ride Cym. 1', 52:'Chinese Cym.', 53:'Ride Bell', 54:'Tambourine',
  55:'Splash Cym.', 56:'Cowbell', 57:'Crash Cym. 2', 58:'Vibraslap',
  59:'Ride Cym. 2', 60:'Hi Bongo', 61:'Lo Bongo',
};

// Category accent colors for instrument browser folders
const CAT_COLORS = {
  'Kicks':'#c04030', 'Kick':'#c04030',
  'Snares':'#3878c8', 'Snare':'#3878c8',
  'Toms':'#289850', 'Tom':'#289850',
  'HiHats':'#b09020', 'Hi-Hat':'#b09020', 'HiHat':'#b09020', 'Hi Hats':'#b09020',
  'Cymbals':'#b06820', 'Cymbal':'#b06820', 'Crashes':'#b06820', 'Crash':'#b06820',
  'Rides':'#986030', 'Ride':'#986030',
  'Percussion':'#7060a8', 'Perc':'#7060a8',
  'Claps':'#909840', 'Clap':'#909840',
  'Sticks':'#506878', 'Fills':'#507888',
};
function catColor(cat) {
  if (CAT_COLORS[cat]) return CAT_COLORS[cat];
  const key = Object.keys(CAT_COLORS).find(k => cat.toLowerCase().includes(k.toLowerCase()));
  return key ? CAT_COLORS[key] : '#3a4a5a';
}

// Build map of sin_rel → [{id, layer}] for all currently assigned pads in the loaded kit
function buildInUseMap() {
  const m = {};
  for (const p of pads) {
    if (p.layer_a_path) { (m[p.layer_a_path] = m[p.layer_a_path] || []).push({id:p.id, layer:'A'}); }
    if (p.layer_b_path) { (m[p.layer_b_path] = m[p.layer_b_path] || []).push({id:p.id, layer:'B'}); }
  }
  return m;
}

// Physical jack groups — each group key maps to a label, jack label, and list of pad IDs
const PAD_GROUPS = {
  'KICK':    {label:'Kick',    jackLabel:'01 KICK',    pads:['K1H','K2H']},
  'SNARE':   {label:'Snare',   jackLabel:'02 SNARE',   pads:['S1H','S1R']},
  'TOM 1':   {label:'Tom 1',   jackLabel:'03 TOM 1',   pads:['T1H','T1R']},
  'TOM 2':   {label:'Tom 2',   jackLabel:'04 TOM 2',   pads:['T2H','T2R']},
  'TOM 3':   {label:'Tom 3',   jackLabel:'05 TOM 3',   pads:['T3H','T3R']},
  'TOM 4':   {label:'Tom 4',   jackLabel:'06 TOM 4',   pads:['T4H','T4R']},
  'HI-HAT':  {label:'Hi-Hat',  jackLabel:'07 HI-HAT',  pads:['H1B','H1E','H1F']},
  'CRASH 1': {label:'Crash 1', jackLabel:'08 CRASH 1', pads:['C1B','C1E']},
  'RIDE 1':  {label:'Ride 1',  jackLabel:'09 RIDE 1',  pads:['R1B','R1E']},
  'RIDE 2':  {label:'Ride 2',  jackLabel:'10 RIDE 2',  pads:['R1D']},
  'CRASH 2': {label:'Crash 2', jackLabel:'11 CRASH 2', pads:['C2B','C2E']},
  'CRASH 3': {label:'Crash 3', jackLabel:'12 CRASH 3', pads:['C3B','C3E']},
};
// Reverse lookup: padId → group key
const PAD_TO_GROUP = {};
for (const [k, g] of Object.entries(PAD_GROUPS)) for (const pid of g.pads) PAD_TO_GROUP[pid] = k;

// Patch panel rows: each entry is [groupKey, displayNumber, label]
// Top row = cymbal inputs (07-12); bottom row = drum inputs (01-06) + HH control
const JACK_ROWS = [
  [['HI-HAT', '07','HH'],      ['CRASH 1','08','CRASH 1'], ['RIDE 1','09','RIDE 1'],
   ['RIDE 2',  '10','RIDE 2'],  ['CRASH 2','11','CRASH 2'], ['CRASH 3','12','CRASH 3']],
  [['KICK',   '01','KICK'],    ['SNARE',  '02','SNARE'],    ['TOM 1', '03','TOM 1'],
   ['TOM 2',  '04','TOM 2'],   ['TOM 3',  '05','TOM 3'],    ['TOM 4', '06','TOM 4'],
   ['HI-HAT', '',  'HH CTRL']],
];

// Return [id, type, cx, cy, rx, ry, lbl] with any user overrides applied
function effectivePadDef(id) {
  const base = PAD_DEFS.find(d => d[0] === id);
  if (!base) return null;
  const [, bt, bcx, bcy, brx, bry, blbl] = base;
  const ov = padOverrides[id] || {};
  return [id,
    ov.type !== undefined ? ov.type : bt,
    ov.cx   !== undefined ? ov.cx   : bcx,
    ov.cy   !== undefined ? ov.cy   : bcy,
    ov.rx   !== undefined ? ov.rx   : brx,
    ov.ry   !== undefined ? ov.ry   : bry,
    ov.lbl  !== undefined ? ov.lbl  : blbl];
}

function savePadOverrides() {
  try { localStorage.setItem('strike_pad_overrides', JSON.stringify(padOverrides)); } catch(e) {}
  updateLayoutBadge();
}

function updateLayoutBadge() {
  const count = Object.keys(padOverrides).length;
  const btn   = document.getElementById('reset-layout-btn');
  if (!btn) return;
  if (count) {
    btn.textContent   = 'Reset layout ●';
    btn.style.color   = '#e0b060';
    btn.style.borderColor = '#604020';
    btn.title = count + ' pad(s) customized — positions & shapes are auto-saved in this browser. Click to restore defaults.';
  } else {
    btn.textContent   = 'Reset layout';
    btn.style.color   = '';
    btn.style.borderColor = '';
    btn.title = 'Restore all pads to default positions and shapes.';
  }
}

// Live setter for rotation / finish from the panel sliders + swatches. redrawPanel=false
// keeps a slider from being torn out mid-drag; the swatch picker passes true to restyle.
function setPadShape(id, key, value, redrawPanel) {
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id][key] = value;
  savePadOverrides();
  renderDrumMap();
  if (redrawPanel) renderPadDetail();
}

// Resize by scale relative to the pad type's default footprint (keeps the perspective ratio).
function setPadSize(id, scale) {
  const d = effectivePadDef(id);
  if (!d) return;
  const def = PAD_TYPE_SIZES[d[1]] || [d[4], d[5]];
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id].rx = Math.max(10, Math.round(def[0] * scale));
  padOverrides[id].ry = Math.max(4,  Math.round(def[1] * scale));
  savePadOverrides();
  renderDrumMap();
}

function setPadOverride(id, key, value) {
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id][key] = value;
  if (key === 'type') {
    // Resize this pad to match its new type
    const sz = PAD_TYPE_SIZES[value];
    if (sz) { padOverrides[id].rx = sz[0]; padOverrides[id].ry = sz[1]; }
    // Sync every companion: rim becomes cym-e when turned into a cymbal, and vice versa
    for (const cid of (PAD_COMPANIONS[id] || [])) {
      const cBase    = PAD_DEFS.find(d => d[0] === cid);
      if (!cBase) continue;
      const newCType = companionTypeFor(value, cBase[1]);
      if (newCType) {
        if (!padOverrides[cid]) padOverrides[cid] = {};
        padOverrides[cid].type = newCType;
        const sz2 = PAD_TYPE_SIZES[newCType];
        if (sz2) { padOverrides[cid].rx = sz2[0]; padOverrides[cid].ry = sz2[1]; }
      }
    }
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function toggleMirrorPad(id) {
  if (!padOverrides[id]) padOverrides[id] = {};
  if (padOverrides[id].mirror) {
    delete padOverrides[id].mirror;
    if (!Object.keys(padOverrides[id]).length) delete padOverrides[id];
    setMsg('Mirror pad removed');
  } else {
    padOverrides[id].mirror = {dx: 150, dy: 0};
    setMsg('Mirror pad added — drag it anywhere; it is the same zone (shared settings)');
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function resetPadOverride(id) {
  delete padOverrides[id];
  // Reset companion cx/cy so they don't stay misaligned
  for (const cid of (PAD_COMPANIONS[id] || [])) {
    if (padOverrides[cid]) {
      delete padOverrides[cid].cx;
      delete padOverrides[cid].cy;
      if (!Object.keys(padOverrides[cid]).length) delete padOverrides[cid];
    }
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function resetAllOverrides() {
  padOverrides = {};
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

// ── Save / load kit layout (positions, sizes, rotation, finish, mirrors) ────────
const VALID_PAD_IDS = new Set(PAD_DEFS.map(d => d[0]));
function exportLayout() {
  const payload = {
    format: 'strike-remap-layout', version: 1,
    saved: new Date().toISOString(), overrides: padOverrides,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url; a.download = `strike-kit-layout-${stamp}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  const n = Object.keys(padOverrides).length;
  setMsg(`Saved layout (${n} customized pad${n === 1 ? '' : 's'})`);
}

async function importLayout(file) {
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const ov = (data && data.overrides && typeof data.overrides === 'object') ? data.overrides
             : (data && typeof data === 'object' && !data.format) ? data : null;  // tolerate a bare overrides object
    if (!ov) { setMsg('Not a valid layout file', true); return; }
    // Keep only recognized pad IDs; ignore anything else.
    const clean = {};
    for (const [id, o] of Object.entries(ov)) {
      if (VALID_PAD_IDS.has(id) && o && typeof o === 'object') clean[id] = o;
    }
    padOverrides = clean;
    savePadOverrides();
    renderDrumMap();
    renderPadDetail();
    const n = Object.keys(clean).length;
    setMsg(`Loaded layout (${n} customized pad${n === 1 ? '' : 's'})`);
  } catch (err) {
    setMsg('Could not read layout file: ' + err.message, true);
  }
}

// ── Patch panel ───────────────────────────────────────────────────────────────
function renderPatchPanel() {
  const el = document.getElementById('patch-panel');
  if (!el) return;
  el.innerHTML = JACK_ROWS.map(row =>
    `<div class="jack-row">${row.map(([grp, num, lbl]) => {
      const hot = selectedGroup === grp ? ' jack-hot' : '';
      return `<div class="jack-item${hot}" onclick="selectGroupFromPanel('${grp}')">`
        + `<div class="jack-plug"></div>`
        + (num ? `<div class="jack-num">${escHtml(num)}</div>` : '<div class="jack-num">&nbsp;</div>')
        + `<div class="jack-lbl">${escHtml(lbl)}</div></div>`;
    }).join('')}</div>`
  ).join('');
}

function selectGroupFromPanel(grpKey) {
  selectedGroup = grpKey;
  const g = PAD_GROUPS[grpKey];
  if (g && g.pads.length) {
    // Keep selectedPad if it's already in this group, otherwise default to first pad / layer A
    const keepPad = selectedPad && g.pads.includes(selectedPad.id);
    const pid = keepPad ? selectedPad.id : g.pads[0];
    selectedMapPad = pid;
    if (!keepPad) selectedPad = {id: pid, layer: 'a'};
  }
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
}

// ── Drag support ──────────────────────────────────────────────────────────────
function svgPt(svgEl, clientX, clientY) {
  const pt = svgEl.createSVGPoint();
  pt.x = clientX; pt.y = clientY;
  return pt.matrixTransform(svgEl.getScreenCTM().inverse());
}

function startDrag(e, id, isMirror) {
  e.preventDefault();
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);
  const def   = effectivePadDef(id);
  if (!def) return;
  const mir = isMirror ? ((padOverrides[id] || {}).mirror || {dx: 0, dy: 0}) : null;
  dragState = {id, isMirror: !!isMirror,
               origCx: def[2] + (mir ? mir.dx : 0), origCy: def[3] + (mir ? mir.dy : 0),
               baseCx: def[2], baseCy: def[3],
               startX: pt.x, startY: pt.y, moved: false};
}

// Resize / rotate handle drag — edits the pad's rx/ry or rot in padOverrides live.
function startHandle(e, id, kind) {
  e.preventDefault();
  e.stopPropagation();
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);
  const def   = effectivePadDef(id);
  if (!def) return;
  const cx = def[2], cy = def[3];
  dragState = {
    id, handle: kind, cx, cy,
    origRx: def[4], origRy: def[5], origRot: +((padOverrides[id] || {}).rot) || 0,
    startDist: Math.max(2, Math.hypot(pt.x - cx, pt.y - cy)),
    startAng:  Math.atan2(pt.y - cy, pt.x - cx) * 180 / Math.PI,
    moved: false,
  };
}

function svgMouseMove(e) {
  if (!dragState) return;
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);

  // Handle drags (resize / rotate) operate on the base pad only.
  if (dragState.handle) {
    const dx0 = pt.x - dragState.cx, dy0 = pt.y - dragState.cy;
    if (!padOverrides[dragState.id]) padOverrides[dragState.id] = {};
    if (dragState.handle === 'resize') {
      const factor = Math.hypot(dx0, dy0) / dragState.startDist;
      padOverrides[dragState.id].rx = Math.max(10, Math.min(320, Math.round(dragState.origRx * factor)));
      padOverrides[dragState.id].ry = Math.max(4,  Math.min(220, Math.round(dragState.origRy * factor)));
    } else {
      // rotate grip sits above centre (−90°), so offset the pointer angle by +90°
      let rot = Math.round(Math.atan2(dy0, dx0) * 180 / Math.PI + 90);
      if (e.shiftKey) rot = Math.round(rot / 15) * 15;     // Shift = snap to 15°
      while (rot > 180) rot -= 360;  while (rot < -180) rot += 360;
      padOverrides[dragState.id].rot = rot;
    }
    dragState.moved = true;
    renderDrumMap();
    if (selectedMapPad && editTargetOf(selectedMapPad) === dragState.id) renderPadDetail();
    return;
  }

  const dx    = pt.x - dragState.startX;
  const dy    = pt.y - dragState.startY;
  if (Math.abs(dx) > 4 || Math.abs(dy) > 4) dragState.moved = true;
  if (!dragState.moved) return;
  const cx = Math.max(20, Math.min(680, Math.round(dragState.origCx + dx)));
  const cy = Math.max(10, Math.min(310, Math.round(dragState.origCy + dy)));
  if (dragState.isMirror) {
    if (!padOverrides[dragState.id]) padOverrides[dragState.id] = {};
    padOverrides[dragState.id].mirror = {dx: cx - dragState.baseCx, dy: cy - dragState.baseCy};
    renderDrumMap();
    return;
  }
  // Move this pad and all companions together
  const all = [dragState.id, ...(PAD_COMPANIONS[dragState.id] || [])];
  for (const pid of all) {
    if (!padOverrides[pid]) padOverrides[pid] = {};
    padOverrides[pid].cx = cx;
    padOverrides[pid].cy = cy;
  }
  renderDrumMap();
}

function svgMouseUp(e) {
  if (!dragState) return;
  const wasMoved = dragState.moved;
  const isHandle = !!dragState.handle;
  const id = dragState.id;
  dragState = null;
  if (isHandle) {
    if (wasMoved) { savePadOverrides(); renderPadDetail(); }
    return;  // handle clicks never select/deselect
  }
  if (wasMoved) {
    savePadOverrides();
    setMsg('Layout saved in browser (drag again to reposition; Reset layout to undo)');
  } else {
    clickPad(id);  // short click = select
  }
}

async function api(path, body) {
  const opts = body
    ? { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }
    : {};
  const r = await fetch('/api' + path, opts);
  return r.json();
}

// In-app async replacement for window.confirm(): themed, and automatable —
// native confirm() blocks the event loop and is auto-dismissed as "cancel"
// by headless browsers, which made restore/delete undriveable in tests.
let _confirmResolve = null;
function appConfirm(message, okLabel = 'OK') {
  let m = document.getElementById('confirm-modal');
  if (!m) {
    m = document.createElement('div');
    m.id = 'confirm-modal';
    m.innerHTML = '<div class="confirm-box"><p id="confirm-msg"></p>'
      + '<div class="confirm-actions">'
      + '<button id="confirm-cancel">Cancel</button>'
      + '<button id="confirm-ok" class="btn-primary"></button>'
      + '</div></div>';
    document.body.appendChild(m);
    m.addEventListener('click', e => { if (e.target === m) _confirmDone(false); });
    document.getElementById('confirm-cancel').onclick = () => _confirmDone(false);
    document.getElementById('confirm-ok').onclick     = () => _confirmDone(true);
    // Capture phase so Escape/Enter don't fall through to the global shortcuts
    document.addEventListener('keydown', e => {
      if (!m.classList.contains('open')) return;
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); _confirmDone(false); }
      if (e.key === 'Enter')  { e.preventDefault(); e.stopPropagation(); _confirmDone(true); }
    }, true);
  }
  document.getElementById('confirm-msg').textContent = message;
  document.getElementById('confirm-ok').textContent  = okLabel;
  m.classList.add('open');
  document.getElementById('confirm-ok').focus();
  return new Promise(res => { _confirmResolve = res; });
}
function _confirmDone(ok) {
  document.getElementById('confirm-modal').classList.remove('open');
  const r = _confirmResolve; _confirmResolve = null;
  if (r) r(ok);
}

// ── External controller bridge (Loupedeck) ──────────────────────────────────
// Mirror the selected pad to the server; poll for param edits made on dials.
let _extSel = null, _extRev = -1;

function postSelect() {
  const id = selectedMapPad || null;
  if (id === _extSel) return;
  _extSel = id;
  fetch('/api/select', {method:'POST', headers:{'Content-Type':'application/json'},
                        body: JSON.stringify({pad_id: id})}).catch(() => {});
}

setInterval(async () => {
  try {
    const s = await (await fetch('/api/selected')).json();
    if (vmActive && s.rev !== vmRev) { vmRev = s.rev; vmRefreshManifest(); }
    if (s.rev === _extRev) return;
    const first = _extRev === -1;
    _extRev = s.rev;
    if (first || !s.pad_id || !s.params) return;
    const p = pads.find(p => p.id === s.pad_id);
    if (!p) return;
    let changed = false;
    for (const k in s.params) if (p[k] !== s.params[k]) { p[k] = s.params[k]; changed = true; }
    if (changed) {
      if (selectedMapPad === s.pad_id) renderPadDetail();
      setDirtyState(true);
    }
  } catch {}
}, 1500);

function setMsg(txt, err=false) {
  const el = document.getElementById('msg');
  el.textContent = txt;
  el.className = err ? 'err' : '';
}

function setDirtyState(dirty, cnt, labels) {
  undoCount = cnt != null ? cnt : undoCount;
  if (labels !== undefined) undoLabels = labels;
  const badge = document.getElementById('dirty-badge');
  if (badge) badge.style.display = dirty ? '' : 'none';
  const undoBtn = document.getElementById('undo-btn');
  if (undoBtn) undoBtn.disabled = undoCount <= 0;
  const histBtn = document.getElementById('undo-hist-btn');
  if (histBtn) histBtn.disabled = undoCount <= 0;
  if (dirty) scheduleAutoSnapshot();  // leave a trail during an editing session (server dedupes)
}

async function undoLast() {
  const data = await api('/undo', {});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  const kfxModal = document.getElementById('kitfx-modal');
  if (kfxModal && kfxModal.classList.contains('open')) showKitFxModal();  // undo restores kit_raw too
  setMsg('Undo');
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Toolbar popover helpers ───────────────────────────────────────────────────
const POPOVERS = ['kit-menu', 'save-menu', 'tools-menu', 'dup-form'];

function closeAllPopovers() {
  POPOVERS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function menuToggle(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const isOpen = el.style.display !== 'none';
  closeAllPopovers();
  if (!isOpen) el.style.display = '';
}

document.addEventListener('click', e => {
  if (!e.target.closest('.tb-group')) {
    closeAllPopovers();
  }
});

// ── Kit list ──────────────────────────────────────────────────────────────────
const SOURCE_BADGE = {'library':'&#x1F4C1;', 'user SD':'&#x1F4BE;', 'preset SD':'&#x1F4BF;'};

function renderKitList() {
  const el = document.getElementById('kit-list');
  el.innerHTML = kits.map((k,i) => {
    const badge  = SOURCE_BADGE[k.source] || '';
    const active = state_kitPath && k.path === state_kitPath ? ' active' : '';
    return `<div class="kit-item${active}" onclick="openKit(${i})" title="${escHtml(k.path)}">`
      + `<span class="kit-src">${badge}</span>${escHtml(k.name)}</div>`;
  }).join('');
}

async function loadKitList() {
  const data = await api('/kits');
  kits = data.kits;
  renderKitList();
}

// Shared post-load state application: used by openKit, drag-drop .skt loading,
// and boot-time rehydration from /api/session.
function applyKitData(data, path, opts) {
  const {dirty = false, undoCount = 0, historyLabels = []} = opts || {};
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = path;
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kitNameEl = document.getElementById('kit-name');
  kitNameEl.textContent = '— ' + kitName;
  kitNameEl.contentEditable = 'true';
  document.getElementById('parse-warn').style.display = data.skt_lossless === false ? '' : 'none';
  document.getElementById('save-lib-btn').disabled    = !libSavePath;
  document.getElementById('save-sd-btn').disabled     = !sdSavePath;
  document.getElementById('dup-btn').disabled         = false;
  document.getElementById('clear-pads-btn').disabled  = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(dirty, undoCount, historyLabels);
  renderKitList();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  if (liveLoop?.ctx) liveLoop.prefetchAll();
  refreshKitSize();
  checkPaths();
}

async function openKit(idx) {
  stopPreview();
  const path = typeof idx === 'number' ? kits[idx].path : idx;
  const data = await api('/load', {path});
  if (data.error) { setMsg(data.error, true); return; }
  applyKitData(data, path);
  closeAllPopovers();
  setMsg(data.message);
}

// ── Drum map ──────────────────────────────────────────────────────────────────
// Strike Pro signature look: dark mesh heads on red-sparkle shells, brass cymbals
// Realistic drum sprites (ported from the drum-realism design mockup). Each sprite is
// modelled at native radius ~100 centred on 0,0; renderDrumMap() places one per pad via
// <use> with translate()+scale(). Rim = hoop-only overlay (transparent centre) that
// registers on its drum; bell = gold dome that sits at the ride's centre.
const DRUM_MAP_DEFS = `<defs>
  <radialGradient id="gShadow" cx="50%" cy="50%" r="50%">
    <stop offset=".55" stop-color="rgba(0,0,0,.42)"/><stop offset="1" stop-color="rgba(0,0,0,0)"/>
  </radialGradient>
  <radialGradient id="gMesh" cx="40%" cy="36%" r="70%">
    <stop offset="0" stop-color="#31343b"/><stop offset=".5" stop-color="#232529"/><stop offset="1" stop-color="#121316"/>
  </radialGradient>
  <pattern id="pMesh" width="5" height="5" patternUnits="userSpaceOnUse">
    <path d="M0 2.5H5M2.5 0V5" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
  </pattern>
  <radialGradient id="gSpec" cx="50%" cy="50%" r="50%">
    <stop offset="0" stop-color="rgba(255,255,255,.12)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/>
  </radialGradient>
  <radialGradient id="gShellRed" cx="38%" cy="34%" r="78%">
    <stop offset="0" stop-color="#cf2a3d"/><stop offset=".5" stop-color="#941a29"/><stop offset="1" stop-color="#520d17"/>
  </radialGradient>
  <pattern id="pSparkle" width="9" height="9" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="3" r=".7" fill="rgba(255,214,220,.55)"/><circle cx="6.5" cy="7" r=".55" fill="rgba(255,170,180,.5)"/>
    <circle cx="7.5" cy="1.5" r=".5" fill="rgba(255,255,255,.45)"/><circle cx="4" cy="6" r=".45" fill="rgba(255,190,190,.4)"/>
  </pattern>
  <linearGradient id="gChrome" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f4f6f9"/><stop offset=".28" stop-color="#c3c9d1"/><stop offset=".52" stop-color="#6b7077"/>
    <stop offset=".72" stop-color="#b6bcc4"/><stop offset="1" stop-color="#4c4f55"/>
  </linearGradient>
  <linearGradient id="gChromeV" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#e9ecf0"/><stop offset=".5" stop-color="#82878e"/><stop offset=".78" stop-color="#d4d9df"/><stop offset="1" stop-color="#54575c"/>
  </linearGradient>
  <linearGradient id="gTube" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#9ba0a8"/><stop offset=".45" stop-color="#e2e6eb"/><stop offset="1" stop-color="#3f4247"/>
  </linearGradient>
  <radialGradient id="gCym" cx="40%" cy="35%" r="74%">
    <stop offset="0" stop-color="#f2d78a"/><stop offset=".35" stop-color="#dab55b"/><stop offset=".75" stop-color="#a67e30"/><stop offset="1" stop-color="#6d5017"/>
  </radialGradient>
  <radialGradient id="gBell" cx="42%" cy="38%" r="65%">
    <stop offset="0" stop-color="#f9e6a8"/><stop offset=".55" stop-color="#c99b42"/><stop offset="1" stop-color="#7c5d1e"/>
  </radialGradient>
  <radialGradient id="gCymE" cx="40%" cy="35%" r="74%">
    <stop offset="0" stop-color="#484c55"/><stop offset=".5" stop-color="#31343b"/><stop offset="1" stop-color="#191b1f"/>
  </radialGradient>

  <g id="lug">
    <rect x="-4.5" y="-104" width="9" height="15" rx="3.2" fill="url(#gChromeV)" stroke="rgba(0,0,0,.55)" stroke-width=".8"/>
    <circle cx="0" cy="-96.5" r="1.7" fill="#26282c"/>
  </g>
  <g id="drumcore">
    <ellipse cx="7" cy="11" rx="106" ry="101" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gShellRed)"/><circle r="100" fill="url(#pSparkle)"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.45)" stroke-width="1.4"/>
    <circle r="91" fill="none" stroke="url(#gChrome)" stroke-width="10"/>
    <circle r="86" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.4"/>
    <circle r="85" fill="url(#gMesh)"/><circle r="85" fill="url(#pMesh)"/>
    <ellipse cx="-27" cy="-30" rx="52" ry="40" fill="url(#gSpec)"/>
    <circle r="85" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="2"/>
  </g>
  <g id="s-snare">
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(36)"/><use href="#lug" transform="rotate(72)"/>
    <use href="#lug" transform="rotate(108)"/><use href="#lug" transform="rotate(144)"/><use href="#lug" transform="rotate(180)"/>
    <use href="#lug" transform="rotate(216)"/><use href="#lug" transform="rotate(252)"/><use href="#lug" transform="rotate(288)"/>
    <use href="#lug" transform="rotate(324)"/>
    <circle r="8" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="1.5"/>
  </g>
  <g id="s-tom">
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(60)"/><use href="#lug" transform="rotate(120)"/>
    <use href="#lug" transform="rotate(180)"/><use href="#lug" transform="rotate(240)"/><use href="#lug" transform="rotate(300)"/>
  </g>
  <g id="s-floor">
    <g transform="rotate(28)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <g transform="rotate(148)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <g transform="rotate(268)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(45)"/><use href="#lug" transform="rotate(90)"/>
    <use href="#lug" transform="rotate(135)"/><use href="#lug" transform="rotate(180)"/><use href="#lug" transform="rotate(225)"/>
    <use href="#lug" transform="rotate(270)"/><use href="#lug" transform="rotate(315)"/>
  </g>
  <g id="s-rim">
    <circle r="98" fill="none" stroke="url(#gShellRed)" stroke-width="4"/>
    <circle r="98" fill="none" stroke="url(#pSparkle)" stroke-width="4"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.45)" stroke-width="1.4"/>
    <circle r="91" fill="none" stroke="url(#gChrome)" stroke-width="10"/>
    <circle r="86" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.4"/>
    <use href="#lug"/><use href="#lug" transform="rotate(36)"/><use href="#lug" transform="rotate(72)"/>
    <use href="#lug" transform="rotate(108)"/><use href="#lug" transform="rotate(144)"/><use href="#lug" transform="rotate(180)"/>
    <use href="#lug" transform="rotate(216)"/><use href="#lug" transform="rotate(252)"/><use href="#lug" transform="rotate(288)"/>
    <use href="#lug" transform="rotate(324)"/>
  </g>
  <g id="s-kick">
    <ellipse cx="8" cy="13" rx="108" ry="103" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gShellRed)"/><circle r="100" fill="url(#pSparkle)"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="1.6"/>
    <circle r="94" fill="none" stroke="url(#gChrome)" stroke-width="7"/>
    <circle r="90" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.2"/>
    <circle r="66" fill="url(#gMesh)"/><circle r="66" fill="url(#pMesh)"/>
    <circle r="66" fill="none" stroke="rgba(0,0,0,.6)" stroke-width="2.5"/>
    <ellipse cx="-20" cy="-24" rx="40" ry="32" fill="url(#gSpec)"/>
    <text y="40" text-anchor="middle" font-family="system-ui,sans-serif" font-size="13" font-weight="800" letter-spacing="4" fill="rgba(232,228,216,.5)">STRIKE</text>
  </g>
  <g id="s-cymbal">
    <ellipse cx="7" cy="10" rx="105" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gCym)"/>
    <g fill="none">
      <circle r="94" stroke="rgba(0,0,0,.13)" stroke-width="1.2"/><circle r="86" stroke="rgba(255,246,214,.14)" stroke-width="1.2"/>
      <circle r="78" stroke="rgba(0,0,0,.12)" stroke-width="1.2"/><circle r="70" stroke="rgba(255,246,214,.12)" stroke-width="1.2"/>
      <circle r="62" stroke="rgba(0,0,0,.12)" stroke-width="1.2"/><circle r="54" stroke="rgba(255,246,214,.11)" stroke-width="1.2"/>
      <circle r="46" stroke="rgba(0,0,0,.11)" stroke-width="1.2"/><circle r="38" stroke="rgba(255,246,214,.1)" stroke-width="1.2"/>
      <circle r="31" stroke="rgba(0,0,0,.1)" stroke-width="1.2"/>
    </g>
    <path d="M0 0 L97 -24 A100 100 0 0 0 55 -83 Z" fill="rgba(255,255,255,.12)"/>
    <path d="M0 0 L-97 24 A100 100 0 0 0 -55 83 Z" fill="rgba(255,255,255,.07)"/>
    <path d="M0 0 L24 97 A100 100 0 0 0 83 55 Z" fill="rgba(0,0,0,.08)"/>
    <circle r="26" fill="url(#gBell)"/><circle r="26" fill="none" stroke="rgba(0,0,0,.3)" stroke-width="1.6"/>
    <circle r="6.5" fill="#1a1a1c"/>
    <path d="M0 -5.4 L4.7 -2.7 L4.7 2.7 L0 5.4 L-4.7 2.7 L-4.7 -2.7 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".7"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.4)" stroke-width="1.4"/>
  </g>
  <g id="s-cym-e">
    <ellipse cx="7" cy="10" rx="105" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gCymE)"/>
    <g fill="none">
      <circle r="90" stroke="rgba(255,255,255,.05)" stroke-width="1.2"/><circle r="76" stroke="rgba(0,0,0,.2)" stroke-width="1.2"/>
      <circle r="62" stroke="rgba(255,255,255,.05)" stroke-width="1.2"/><circle r="48" stroke="rgba(0,0,0,.2)" stroke-width="1.2"/>
      <circle r="36" stroke="rgba(255,255,255,.045)" stroke-width="1.2"/>
    </g>
    <circle r="96" fill="none" stroke="rgba(212,175,55,.5)" stroke-width="2"/>
    <path d="M0 0 L97 -24 A100 100 0 0 0 55 -83 Z" fill="rgba(255,255,255,.07)"/>
    <circle r="26" fill="url(#gCymE)"/><circle r="26" fill="none" stroke="rgba(212,175,55,.55)" stroke-width="1.6"/>
    <ellipse cx="-8" cy="-9" rx="13" ry="10" fill="url(#gSpec)"/>
    <circle r="6.5" fill="#101113"/>
    <path d="M0 -5.4 L4.7 -2.7 L4.7 2.7 L0 5.4 L-4.7 2.7 L-4.7 -2.7 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".7"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="1.4"/>
  </g>
  <g id="s-bell">
    <ellipse cx="6" cy="9" rx="104" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gBell)"/><circle r="100" fill="none" stroke="rgba(0,0,0,.35)" stroke-width="2.5"/>
    <circle r="72" fill="none" stroke="rgba(0,0,0,.14)" stroke-width="2"/>
    <circle r="46" fill="none" stroke="rgba(255,248,220,.2)" stroke-width="2"/>
    <ellipse cx="-30" cy="-34" rx="42" ry="34" fill="url(#gSpec)"/><ellipse cx="-30" cy="-34" rx="20" ry="15" fill="rgba(255,255,255,.16)"/>
    <circle r="10" fill="#1a1a1c"/>
    <path d="M0 -8 L7 -4 L7 4 L0 8 L-7 4 L-7 -4 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/>
  </g>
  <g id="s-hfoot">
    <ellipse cx="6" cy="10" rx="66" ry="104" fill="url(#gShadow)"/>
    <rect x="-52" y="-96" width="104" height="192" rx="18" fill="#212329" stroke="rgba(0,0,0,.6)" stroke-width="1.5"/>
    <rect x="-52" y="-96" width="104" height="192" rx="18" fill="url(#pMesh)" opacity=".4"/>
    <rect x="-52" y="-92" width="9" height="150" rx="4.5" fill="url(#gChromeV)" opacity=".85"/>
    <rect x="43" y="-92" width="9" height="150" rx="4.5" fill="url(#gChromeV)" opacity=".85"/>
    <path d="M-30 -78 L30 -78 L38 62 L-38 62 Z" fill="url(#gTube)" stroke="rgba(0,0,0,.55)" stroke-width="1.5"/>
    <path d="M-30 -78 L30 -78 L33 -20 L-33 -20 Z" fill="rgba(255,255,255,.14)"/>
    <g stroke="rgba(0,0,0,.4)" stroke-width="2">
      <line x1="-31" y1="-52" x2="31" y2="-52"/><line x1="-32" y1="-26" x2="32" y2="-26"/><line x1="-34" y1="0" x2="34" y2="0"/>
      <line x1="-35" y1="26" x2="35" y2="26"/><line x1="-37" y1="50" x2="37" y2="50"/>
    </g>
    <path d="M-38 62 L38 62 L34 92 L-34 92 Z" fill="#2b2d33" stroke="rgba(0,0,0,.6)" stroke-width="1.5"/>
    <line x1="-38" y1="62" x2="38" y2="62" stroke="rgba(255,255,255,.18)" stroke-width="2"/>
    <rect x="-14" y="-96" width="28" height="14" rx="5" fill="url(#gChromeV)" stroke="rgba(0,0,0,.55)" stroke-width="1"/>
    <circle cy="-89" r="3.2" fill="#26282c"/>
  </g>
</defs>`;

function renderDrumMap() {
  const svgEl = document.getElementById('drum-svg');
  if (!svgEl) return;

  const padMap = {};
  for (const p of pads) padMap[p.id] = p;

  // Which pad IDs are in the currently selected group?
  const groupMembers = new Set();
  if (selectedGroup && PAD_GROUPS[selectedGroup]) {
    for (const pid of PAD_GROUPS[selectedGroup].pads) groupMembers.add(pid);
  }

  const parts = [];
  const overlays = [];   // rim/bell drawn after everything so they sit on top of their drum/ride
  for (const baseDef of PAD_DEFS) {
    const [id, type, cx, cy, rx, ry, lbl] = effectivePadDef(baseDef[0]);
    const p        = padMap[id];
    const hasInstA = p && p.layer_a_path;
    const hasInstB = p && p.layer_b_path;
    const hasInst  = hasInstA || hasInstB;
    const isSel    = selectedMapPad === id;
    const isAssT   = selectedPad && selectedPad.id === id;
    const inGroup  = groupMembers.has(id);

    const isBroken   = p && (brokenPaths.has(p.layer_a_path) || brokenPaths.has(p.layer_b_path));
    const isBatchSel = batchMode && batchSelected.has(id);
    const isOverlay  = (type === 'rim' || type === 'bell');

    const opacity = !pads.length ? 0.5 : (hasInst ? 1.0 : (isOverlay ? 0.62 : 0.34));

    // Sprite placement. Rim/bell register on their parent so the hoop lands on the drum
    // and the bell dome sits at the ride's centre; they also inherit the parent's rotation
    // and finish so a drum + rim (or ride + bell) read as one piece.
    const par = isOverlay ? drumParentOf(id) : null;
    let scx = cx, scy = cy, srx = rx, sry = ry;
    if (par) {
      scx = par[2]; scy = par[3];
      if (type === 'rim') { srx = par[4]; sry = par[5]; }   // hoop matches the drum exactly
    }
    // Rotation + finish live on the base pad (the drum/ride for an overlay).
    const baseOv  = padOverrides[par ? par[0] : id] || {};
    const srot    = +baseOv.rot || 0;
    const finSet  = finishSetFor(type);
    const finFilt = (finSet && baseOv.finish && finSet[baseOv.finish]) ? finSet[baseOv.finish].filter : '';

    const rotTf = srot ? ` rotate(${srot})` : '';
    const tf = (type === 'hfoot')
      ? `translate(${scx},${scy})${rotTf} scale(${(rx/56).toFixed(3)})`
      : `translate(${scx},${scy})${rotTf} scale(${(srx/100).toFixed(3)},${(sry/100).toFixed(3)})`;
    const sprite = `<use href="#s-${type}" transform="${tf}"${finFilt ? ` style="filter:${finFilt}"` : ''}/>`;

    // Selection / assignment-target use a CSS glow (below); group + batch add a footprint ring.
    let ring = '';
    const rrx = (srx + 4).toFixed(1), rry = (sry + 4).toFixed(1);
    const ringRot = srot ? ` transform="rotate(${srot} ${scx} ${scy})"` : '';
    if (isBatchSel) {
      ring = `<ellipse cx="${scx}" cy="${scy}" rx="${rrx}" ry="${rry}" fill="none" stroke="#e0a030" stroke-width="2.4" stroke-dasharray="4,2" pointer-events="none"${ringRot}/>`;
    } else if (inGroup && !isSel && !isAssT) {
      ring = `<ellipse cx="${scx}" cy="${scy}" rx="${rrx}" ry="${rry}" fill="none" stroke="#4a7fd0" stroke-width="1.6" opacity="0.75" pointer-events="none"${ringRot}/>`;
    }

    let glow = '';
    if (isSel)           glow = 'filter:drop-shadow(0 0 6px #f0b32e) drop-shadow(0 0 13px #f0b32e70);';
    else if (isAssT)     glow = 'filter:drop-shadow(0 0 6px #44aaff) drop-shadow(0 0 12px #44aaff70);';
    else if (isBatchSel) glow = 'filter:drop-shadow(0 0 6px #e0a030a0);';

    // Label (base pads only — rim/bell labels are empty in PAD_DEFS)
    let textEl = '';
    if (lbl) {
      const fs = Math.max(7, Math.min(13, ry * 1.2));
      const lblFill = isSel ? '#ffd86a' : (isBatchSel ? '#e0c060' : (inGroup ? '#dde8ff' : '#eef1f6'));
      textEl = `<text x="${cx}" y="${cy + fs * 0.35}" text-anchor="middle" `
        + `font-size="${fs}" fill="${lblFill}" font-family="system-ui,sans-serif" font-weight="700" `
        + `paint-order="stroke" stroke="#000000cc" stroke-width="2.4" stroke-linejoin="round" `
        + `pointer-events="none">${escHtml(lbl)}</text>`;
      // Show assigned instrument name on wider pads
      if (hasInst && rx >= 36) {
        const instrName = p.layer_a_name || p.layer_b_name || '';
        if (instrName) {
          const maxChars = Math.max(4, Math.floor(rx / 5.2));
          const short = instrName.length > maxChars ? instrName.slice(0, maxChars) + '…' : instrName;
          const ifs = Math.max(4.5, Math.min(6.5, ry * 0.6));
          textEl += `<text x="${cx}" y="${cy + fs * 0.35 + ifs * 1.9}" text-anchor="middle" `
            + `font-size="${ifs}" fill="#cdd6e2" paint-order="stroke" stroke="#000000cc" stroke-width="1.8" stroke-linejoin="round" `
            + `font-family="system-ui,sans-serif" pointer-events="none">${escHtml(short)}</text>`;
        }
      }
    }
    // Broken-path warning badge
    const warnEl = isBroken
      ? `<text x="${(scx + srx - 4).toFixed(1)}" y="${(scy - sry + 7).toFixed(1)}" font-size="9" fill="#ff9a3c" `
        + `font-family="system-ui,sans-serif" text-anchor="middle" pointer-events="none">⚠</text>`
      : '';

    // SVG <title> for browser tooltip on hover
    const tipLines = [padMap[id]?.label || id];
    if (p && p.layer_a_name) tipLines.push('A: ' + p.layer_a_name);
    if (p && p.layer_b_name) tipLines.push('B: ' + p.layer_b_name);
    if (isBroken)             tipLines.push('⚠ instrument file not found on this machine');
    if (pads.length && !hasInst) tipLines.push('(empty — click to assign)');
    const titleEl = `<title>${escHtml(tipLines.join('\n'))}</title>`;

    const inner = titleEl + sprite + ring + textEl + warnEl;
    (isOverlay ? overlays : parts).push(
      `<g class="map-pad" data-pid="${id}" style="opacity:${opacity};${glow}" onmousedown="startDrag(event,'${id}')">`
      + inner + `</g>`);

    // Mirror pad: same zone drawn a second time (e.g. dual hi-hats on a Y-splitter)
    const mir = (padOverrides[id] || {}).mirror;
    if (mir) {
      const link = `<text x="${(scx + srx - 6).toFixed(1)}" y="${(scy - sry + 8).toFixed(1)}" font-size="9" `
        + `fill="#7f8a9c" pointer-events="none" font-family="system-ui,sans-serif">&#x29C9;</text>`;
      (isOverlay ? overlays : parts).push(
        `<g class="map-pad" data-pid="${id}" transform="translate(${mir.dx},${mir.dy})" `
        + `style="opacity:${opacity};${glow}" onmousedown="startDrag(event,'${id}',true)">`
        + `<title>${escHtml((padMap[id]?.label || id) + ' (mirror — same zone, shared settings)')}</title>`
        + sprite + ring + textEl + warnEl + link + `</g>`);
    }
  }

  // Direct-manipulation handles on the selected pad (resize + rotate). Edits target the
  // base pad, so grabbing a rim/bell handle actually resizes/rotates its drum/ride.
  let handles = '';
  if (selectedMapPad && !batchMode) {
    const et = editTargetOf(selectedMapPad);
    const d  = effectivePadDef(et);
    if (d) {
      const [, , hcx, hcy, hrx, hry] = d;
      const rot  = +((padOverrides[et] || {}).rot) || 0;
      const rad  = rot * Math.PI / 180;
      // resize grip on the pad's right edge (follows rotation); rotate grip above centre
      const rex = hcx + (hrx + 7) * Math.cos(rad), rey = hcy + (hrx + 7) * Math.sin(rad);
      const rotHandleX = hcx + (hry + 22) * Math.sin(rad), rotHandleY = hcy - (hry + 22) * Math.cos(rad);
      handles =
        `<g class="pad-handle" data-h="rotate" onmousedown="startHandle(event,'${et}','rotate')">`
        + `<line x1="${hcx.toFixed(1)}" y1="${hcy.toFixed(1)}" x2="${rotHandleX.toFixed(1)}" y2="${rotHandleY.toFixed(1)}" stroke="#f0b32e" stroke-width="1.2" opacity=".8"/>`
        + `<circle cx="${rotHandleX.toFixed(1)}" cy="${rotHandleY.toFixed(1)}" r="5" fill="#141519" stroke="#f0b32e" stroke-width="1.6"/>`
        + `<path d="M ${(rotHandleX-2.4).toFixed(1)} ${rotHandleY.toFixed(1)} a 2.4 2.4 0 1 1 1.4 2.1" fill="none" stroke="#f0b32e" stroke-width="1"/>`
        + `</g>`
        + `<g class="pad-handle" data-h="resize" onmousedown="startHandle(event,'${et}','resize')">`
        + `<circle cx="${rex.toFixed(1)}" cy="${rey.toFixed(1)}" r="5" fill="#f0b32e" stroke="#141519" stroke-width="1.4"/>`
        + `<path d="M ${(rex-2.2).toFixed(1)} ${(rey-2.2).toFixed(1)} L ${(rex+2.2).toFixed(1)} ${(rey+2.2).toFixed(1)} M ${(rex+2.2).toFixed(1)} ${(rey-2.2).toFixed(1)} L ${(rex-2.2).toFixed(1)} ${(rey+2.2).toFixed(1)}" stroke="#141519" stroke-width="1.1"/>`
        + `</g>`;
    }
  }

  svgEl.innerHTML = DRUM_MAP_DEFS + parts.join('') + overlays.join('') + handles;
}

// The drum/ride an overlay pad (rim or bell) sits on — its first companion of a base type.
// Used so the rim hoop scales to its drum and the bell dome centres on its ride.
function drumParentOf(id) {
  const drums = new Set(['kick','snare','tom','floor']);
  for (const cid of (PAD_COMPANIONS[id] || [])) {
    const d = effectivePadDef(cid);
    if (!d) continue;
    if (drums.has(d[1]) || d[1] === 'cymbal' || d[1] === 'cym-e') return d;
  }
  return null;
}

// The pad an edit (resize/rotate/finish) should apply to: overlays redirect to their parent.
function editTargetOf(id) {
  const d = effectivePadDef(id);
  if (d && (d[1] === 'rim' || d[1] === 'bell')) {
    const par = drumParentOf(id);
    if (par) return par[0];
  }
  return id;
}

function clickPad(id) {
  if (batchMode) {
    if (batchSelected.has(id)) batchSelected.delete(id);
    else batchSelected.add(id);
    document.getElementById('batch-count').textContent = batchSelected.size + ' pad' + (batchSelected.size !== 1 ? 's' : '') + ' selected';
    renderDrumMap();
    return;
  }
  selectedMapPad = id;
  selectedGroup  = PAD_TO_GROUP[id] || null;
  // Auto-target this pad for assignment (keep current layer if re-clicking same pad)
  if (!selectedPad || selectedPad.id !== id) {
    selectedPad = {id, layer: 'a'};
  }
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  renderInstruments();  // refresh "current" highlight in browser
}

// ── Velocity xfade interactive control ───────────────────────────────────────
let _velDrag = null;

function velXfadeControl(padId, xfade, laLevel, lbLevel) {
  const W = 176, H = 48, pad = 4;
  const aCol = '#4a90d9', bCol = '#e06040';
  const xPx  = v => pad + (v / 127) * (W - pad * 2);
  const splitX = xfade === 0 ? W - pad : xPx(xfade);
  const maxH = H - 16;
  const aH = Math.max(3, (laLevel / 127) * maxH);
  const bH = Math.max(3, (lbLevel / 127) * maxH);
  const aY = H - 14 - aH, bY = H - 14 - bH;
  const bW = Math.max(0, W - pad - splitX);
  const eid = 'vx_' + padId.replace(/\W/g,'_');

  const splitViz = xfade > 0 ? `
    <line id="${eid}_spl" x1="${splitX}" y1="0" x2="${splitX}" y2="${H-14}" stroke="#aaa" stroke-width="1.5" stroke-dasharray="3,2"/>
    <rect id="${eid}_hdl" x="${splitX-5}" y="0" width="10" height="${H-14}" fill="transparent" style="cursor:ew-resize"/>
    <text id="${eid}_lbl" x="${splitX}" y="${H-3}" text-anchor="middle" font-size="8" fill="#aaa">${xfade}</text>` : `
    <text id="${eid}_lbl" x="${W/2}" y="${H-3}" text-anchor="middle" font-size="8" fill="#445">A only (drag to enable B)</text>`;

  return `<svg id="${eid}" class="vel-xfade-svg" width="${W}" height="${H}"
      data-pid="${escHtml(padId)}" onmousedown="startVelDrag(event)"
      style="display:block;flex-shrink:0;cursor:ew-resize;user-select:none;" xmlns="http://www.w3.org/2000/svg">
    <rect x="${pad}" y="0" width="${W - pad*2}" height="${H-14}" fill="#0a1520" rx="2"/>
    <rect id="${eid}_abar" x="${pad}" y="${aY}" width="${Math.max(0, splitX - pad)}" height="${aH}" fill="${aCol}" opacity="0.75" rx="1"/>
    <rect id="${eid}_bbar" x="${splitX}" y="${bY}" width="${bW}" height="${bH}" fill="${bCol}" opacity="${xfade===0?'0':'0.75'}" rx="1"/>
    ${splitViz}
    <text x="${pad+3}" y="${H-3}" font-size="8" fill="${aCol}">A</text>
    <text x="${W-pad-2}" y="${H-3}" text-anchor="end" font-size="8" fill="${xfade===0?'#334':bCol}">B</text>
  </svg>`;
}

function startVelDrag(e) {
  e.preventDefault();
  const svg = e.currentTarget;
  _velDrag = {padId: svg.dataset.pid, svg, rect: svg.getBoundingClientRect(), lastVel: null};
  _applyVelDrag(e.clientX);
}

function _applyVelDrag(clientX) {
  if (!_velDrag) return;
  const {svg, rect, padId} = _velDrag;
  const W = svg.viewBox?.baseVal?.width || svg.getBoundingClientRect().width;
  const pad = 4;
  const x = Math.max(pad, Math.min(W - pad, clientX - rect.left));
  const vel = Math.round((x - pad) / (W - pad * 2) * 127);
  const eid = 'vx_' + padId.replace(/\W/g,'_');
  const aCol = '#4a90d9', bCol = '#e06040';
  const aBar = document.getElementById(eid + '_abar');
  const bBar = document.getElementById(eid + '_bbar');
  const spl  = document.getElementById(eid + '_spl');
  const hdl  = document.getElementById(eid + '_hdl');
  const lbl  = document.getElementById(eid + '_lbl');
  if (aBar) aBar.setAttribute('width', Math.max(0, x - pad));
  if (bBar) { bBar.setAttribute('x', x); bBar.setAttribute('width', Math.max(0, W - pad - x)); bBar.setAttribute('opacity', vel === 0 ? '0' : '0.75'); }
  if (spl)  { spl.setAttribute('x1', x); spl.setAttribute('x2', x); }
  if (hdl)  hdl.setAttribute('x', x - 5);
  if (lbl)  { lbl.setAttribute('x', x); lbl.textContent = vel === 0 ? 'A only' : vel; }
  _velDrag.lastVel = vel;
}

// ── Pad detail helpers ────────────────────────────────────────────────────────
function midiNoteSelect(pid, val) {
  let opts = '';
  for (let i = 0; i <= 127; i++) {
    const lbl = GM_DRUMS_JS[i] ? `${i} – ${GM_DRUMS_JS[i]}` : String(i);
    opts += `<option value="${i}"${i===val?' selected':''}>${escHtml(lbl)}</option>`;
  }
  return `<select class="midi-select" onchange="setParam('${pid}','midi_note',+this.value)">${opts}</select>`;
}
function paramSlider(pid, param, val, lo, hi, disabled) {
  const dis = disabled ? ' disabled style="opacity:0.35;"' : '';
  return `<div class="param-slider-wrap">`
    + `<input type="range" min="${lo}" max="${hi}" value="${Math.min(hi,Math.max(lo,val))}"${dis} `
    + `oninput="this.nextElementSibling.textContent=this.value" `
    + `onchange="setParam('${pid}','${param}',+this.value)">`
    + `<span class="param-val"${dis}>${val}</span>`
    + `</div>`;
}

// ── Pad detail panel ──────────────────────────────────────────────────────────
function renderPadDetail() {
  const el = document.getElementById('pad-detail');
  if (!el) return;

  if (!selectedGroup || !pads.length) {
    el.innerHTML = '<div class="det-empty">Click a pad or jack to view and edit</div>';
    return;
  }

  const group = PAD_GROUPS[selectedGroup];
  if (!group) { el.innerHTML = ''; return; }

  const groupPads = group.pads.map(id => pads.find(p => p.id === id)).filter(Boolean);
  if (!groupPads.length) { el.innerHTML = ''; return; }

  // Primary pad = active assignment target (or first in group)
  const primary = groupPads.find(p => selectedPad && p.id === selectedPad.id) || groupPads[0];

  // Zone rows (one per pad in the group)
  const zoneHtml = groupPads.map(p => {
    const isSel    = selectedPad && selectedPad.id === p.id;
    const curLayer = isSel ? selectedPad.layer : null;
    const btnA     = `layer-btn${curLayer==='a' ? ' active-layer' : ''}`;
    const btnB     = `layer-btn${curLayer==='b' ? ' active-layer' : ''}`;
    const warnA    = p.layer_a_path && brokenPaths.has(p.layer_a_path) ? ' <span title="File not found on this machine" style="color:#e08020;font-size:.7rem;">⚠</span>' : '';
    const warnB    = p.layer_b_path && brokenPaths.has(p.layer_b_path) ? ' <span title="File not found on this machine" style="color:#e08020;font-size:.7rem;">⚠</span>' : '';
    return `<div class="det-zone${isSel ? ' zone-sel' : ''}">
      <div class="det-zone-id">${escHtml(p.id)}<span class="zlbl">${escHtml(p.label)}</span></div>
      <div class="det-layer">
        <span class="pill">A</span>
        <span class="name" title="${escHtml(p.layer_a_path||'')}">${escHtml(p.layer_a_name||'—')}${warnA}</span>
        <button class="${btnA}" onclick="selectPadLayer('${p.id}','a')">assign</button>
        ${p.layer_a_path ? `<button class="layer-btn" title="Edit instrument parameters" onclick="openSinEditor('${p.layer_a_path}')">&#9881;</button>` : ''}
        ${p.layer_a_path ? `<button class="layer-btn" title="Find similar-sounding instruments" onclick="openSimilar('${p.layer_a_path}')">&#8776;</button>` : ''}
        ${p.layer_a_path ? `<button class="layer-btn clear" onclick="clearLayer('${p.id}','a')">&#x2715;</button>` : ''}
      </div>
      <div class="det-layer">
        <span class="pill">B</span>
        <span class="name" title="${escHtml(p.layer_b_path||'')}">${escHtml(p.layer_b_name||'—')}${warnB}</span>
        <button class="${btnB}" onclick="selectPadLayer('${p.id}','b')">assign</button>
        ${p.layer_b_path ? `<button class="layer-btn" title="Edit instrument parameters" onclick="openSinEditor('${p.layer_b_path}')">&#9881;</button>` : ''}
        ${p.layer_b_path ? `<button class="layer-btn" title="Find similar-sounding instruments" onclick="openSimilar('${p.layer_b_path}')">&#8776;</button>` : ''}
        ${p.layer_b_path ? `<button class="layer-btn clear" onclick="clearLayer('${p.id}','b')">&#x2715;</button>` : ''}
      </div>
    </div>`;
  }).join('');

  // Params section — for the primary (active) zone
  const hasBLayer = !!primary.layer_b_path;
  const paramsHtml = `<div class="det-params">
    <div class="param-row">
      <span class="param-lbl" title="MIDI note sent when pad is hit">MIDI note</span>
      ${midiNoteSelect(primary.id, primary.midi_note)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer A level</span>
      ${paramSlider(primary.id, 'la_level', primary.la_level, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer A pan</span>
      ${paramSlider(primary.id, 'la_pan', primary.la_pan, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A pitch shift in semitones (-12 to +12)">Layer A pitch</span>
      ${paramSlider(primary.id, 'la_pitch', primary.la_pitch, -12, 12)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A fine pitch -50 to +50 cents">A fine pitch</span>
      ${paramSlider(primary.id, 'la_fine', primary.la_fine, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A decay (0=short, 99=long natural tail)">Layer A decay</span>
      ${paramSlider(primary.id, 'la_decay', primary.la_decay, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Volume sensitivity for Layer A">A vel→vol</span>
      ${paramSlider(primary.id, 'la_vel_vol', primary.la_vel_vol, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Decay for Layer A">A vel→dec</span>
      ${paramSlider(primary.id, 'la_vel_dec', primary.la_vel_dec, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Pitch for Layer A">A vel→pch</span>
      ${paramSlider(primary.id, 'la_vel_pch', primary.la_vel_pch, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Filter for Layer A">A vel→flt</span>
      ${paramSlider(primary.id, 'la_vel_flt', primary.la_vel_flt, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A filter: enable and cutoff frequency">Layer A filter</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:52px;" onchange="setParam('${primary.id}','la_fflag',+this.value)">
          <option value="0"${primary.la_fflag===0?' selected':''}>Off</option>
          <option value="1"${primary.la_fflag===1?' selected':''}>On</option>
        </select>
        ${paramSlider(primary.id, 'la_fcut', primary.la_fcut, 0, 99, !primary.la_fflag)}
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A loop mode — plays sample continuously while held">A loop</span>
      <select class="midi-select" style="width:72px;" onchange="setParam('${primary.id}','la_loop',+this.value)">
        <option value="0"${primary.la_loop===0?' selected':''}>Off</option>
        <option value="1"${primary.la_loop===1?' selected':''}>Loop On</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A velocity range minimum — layer plays at or above this velocity">A vel min</span>
      ${paramSlider(primary.id, 'la_vel_min', primary.la_vel_min, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A velocity range maximum — layer plays at or below this velocity">A vel max</span>
      ${paramSlider(primary.id, 'la_vel_max', primary.la_vel_max, 0, 127)}
    </div>
    ${hasBLayer ? `
    <div class="param-row">
      <span class="param-lbl">Layer B level</span>
      ${paramSlider(primary.id, 'lb_level', primary.lb_level, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer B pan</span>
      ${paramSlider(primary.id, 'lb_pan', primary.lb_pan, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B pitch shift in semitones (-12 to +12)">Layer B pitch</span>
      ${paramSlider(primary.id, 'lb_pitch', primary.lb_pitch, -12, 12)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B fine pitch -50 to +50 cents">B fine pitch</span>
      ${paramSlider(primary.id, 'lb_fine', primary.lb_fine, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B decay (0=short, 99=long natural tail)">Layer B decay</span>
      ${paramSlider(primary.id, 'lb_decay', primary.lb_decay, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Volume sensitivity for Layer B">B vel→vol</span>
      ${paramSlider(primary.id, 'lb_vel_vol', primary.lb_vel_vol, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Decay for Layer B">B vel→dec</span>
      ${paramSlider(primary.id, 'lb_vel_dec', primary.lb_vel_dec, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Pitch for Layer B">B vel→pch</span>
      ${paramSlider(primary.id, 'lb_vel_pch', primary.lb_vel_pch, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Filter for Layer B">B vel→flt</span>
      ${paramSlider(primary.id, 'lb_vel_flt', primary.lb_vel_flt, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B filter: enable and cutoff frequency">Layer B filter</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:52px;" onchange="setParam('${primary.id}','lb_fflag',+this.value)">
          <option value="0"${primary.lb_fflag===0?' selected':''}>Off</option>
          <option value="1"${primary.lb_fflag===1?' selected':''}>On</option>
        </select>
        ${paramSlider(primary.id, 'lb_fcut', primary.lb_fcut, 0, 99, !primary.lb_fflag)}
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B loop mode — plays sample continuously while held">B loop</span>
      <select class="midi-select" style="width:72px;" onchange="setParam('${primary.id}','lb_loop',+this.value)">
        <option value="0"${primary.lb_loop===0?' selected':''}>Off</option>
        <option value="1"${primary.lb_loop===1?' selected':''}>Loop On</option>
      </select>
    </div>
    <div class="param-row" style="align-items:flex-start;">
      <span class="param-lbl" style="padding-top:3px;" title="Velocity at which Layer B starts playing (0 = both layers always active)">Vel. xfade</span>
      ${velXfadeControl(primary.id, primary.xfade_vel, primary.la_level, primary.lb_level)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Play Layer A and B simultaneously at their current levels">Blend preview</span>
      <button class="btn-secondary" style="font-size:.68rem;padding:3px 9px;"
        onclick="previewBlend('${primary.id}')">&#9654; A+B</button>
    </div>` : ''}
    <div class="param-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2a3e;">
      <span class="param-lbl" style="font-weight:600;color:#7ab3ef;font-size:.7rem;">FX / Zone</span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Reverb send level (0=dry, 99=max)">Reverb</span>
      ${paramSlider(primary.id, 'reverb', primary.reverb, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="FX1 send level (0–99)">FX1</span>
      ${paramSlider(primary.id, 'fx1', primary.fx1, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="FX2 send level (0–99)">FX2</span>
      ${paramSlider(primary.id, 'fx2', primary.fx2, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="EQ/Comp enable">EQ/Comp</span>
      <select class="midi-select" onchange="setParam('${primary.id}','eq_comp',+this.value)">
        <option value="0"${primary.eq_comp===0?' selected':''}>Off</option>
        <option value="1"${primary.eq_comp===1?' selected':''}>On</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Playback mode: Poly allows multiple simultaneous hits, Mono stops previous">Play mode</span>
      <select class="midi-select" onchange="setParam('${primary.id}','play_mode',+this.value)">
        <option value="1"${primary.play_mode===1?' selected':''}>Poly</option>
        <option value="0"${primary.play_mode===0?' selected':''}>Mono</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Playback priority when voices are stolen">Priority</span>
      <select class="midi-select" onchange="setParam('${primary.id}','priority',+this.value)">
        <option value="0"${primary.priority===0?' selected':''}>Low</option>
        <option value="1"${primary.priority===1?' selected':''}>Med</option>
        <option value="2"${primary.priority===2?' selected':''}>High</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Note Off behaviour">Note Off</span>
      <select class="midi-select" onchange="setParam('${primary.id}','note_off',+this.value)">
        <option value="0"${primary.note_off===0?' selected':''}>Sent</option>
        <option value="1"${primary.note_off===1?' selected':''}>None</option>
        <option value="2"${primary.note_off===2?' selected':''}>Alt</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Duration of the MIDI note sent when struck: Free = fixed length in ms, Sync = tempo-synced, OFF = no gate">Gate time</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:96px;" onchange="setGateMode('${primary.id}',this.value)">
          <option value="free"${primary.gate_time<=99?' selected':''}>Free</option>
          ${GATE_SYNC.map((n,i)=>`<option value="${100+i}"${primary.gate_time===100+i?' selected':''}>${n}</option>`).join('')}
          <option value="255"${primary.gate_time===255?' selected':''}>OFF</option>
        </select>
        <input type="number" min="0" max="99" value="${primary.gate_time<=99?primary.gate_time:0}"
          ${primary.gate_time<=99?'':'disabled style="opacity:0.35;"'}
          class="midi-select" style="width:52px;" title="Gate length in ms (Free mode)"
          onchange="setParam('${primary.id}','gate_time',Math.min(99,Math.max(0,+this.value)))"> ms
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="MIDI output channel (1–16)">MIDI chan</span>
      <select class="midi-select" onchange="setParam('${primary.id}','midi_chan',+this.value)">
        ${Array.from({length:16},(_,i)=>`<option value="${i+1}"${primary.midi_chan===i+1?' selected':''}>${i+1}</option>`).join('')}
      </select>
    </div>
    <div class="param-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2a3e;">
      <span class="param-lbl" title="Mute Group: pads in the same group silence each other (e.g. open/closed hi-hat)">Mute group</span>
      <select class="midi-select" onchange="setParam('${primary.id}','mute_grp',+this.value)">
        <option value="0"${primary.mute_grp===0?' selected':''}>Off</option>
        ${[1,2,3,4,5,6,7,8,9].map(n=>`<option value="${n}"${primary.mute_grp===n?' selected':''}>${n}</option>`).join('')}
      </select>
    </div>
  </div>`;

  // Customize section — shape/label edit the zone; size/rotation/finish edit the base pad
  // (an overlay rim/bell redirects to its drum/ride so they stay a single piece).
  const effDef   = effectivePadDef(primary.id);
  const effType  = effDef ? effDef[1] : 'tom';
  const effLbl   = effDef ? effDef[6] : '';
  const hasOv    = padOverrides[primary.id] && Object.keys(padOverrides[primary.id]).length > 0;
  const typeOpts = ['kick','snare','rim','tom','floor','cymbal','cym-e','bell','hfoot']
    .map(t => `<option value="${t}"${t===effType?' selected':''}>${t}</option>`).join('');

  const editId   = editTargetOf(primary.id);
  const editDef  = effectivePadDef(editId);
  const editType = editDef ? editDef[1] : effType;
  const defSize  = PAD_TYPE_SIZES[editType] || [editDef ? editDef[4] : 40, editDef ? editDef[5] : 15];
  const curScale = editDef ? (editDef[4] / defSize[0]) : 1;
  const curRot   = +((padOverrides[editId] || {}).rot) || 0;
  const finSet   = finishSetFor(editType);
  const curFin   = (padOverrides[editId] || {}).finish || (finSet ? Object.keys(finSet)[0] : '');
  const finishRow = finSet ? `<div class="finish-row">${Object.entries(finSet).map(([k, f]) =>
    `<button class="fin-sw${k === curFin ? ' on' : ''}" title="${f.name}" style="background:${f.swatch}" `
    + `onclick="setPadShape('${editId}','finish','${k}',true)"></button>`).join('')}</div>` : '';

  const custHtml = `<details class="det-customize">
    <summary>&#9654; Customize on map (${escHtml(primary.id)})</summary>
    <div class="cust-grid">
      <span>Label</span>
      <input type="text" maxlength="6" value="${escHtml(effLbl)}"
        onchange="setPadOverride('${primary.id}','lbl',this.value.trim())">
      <span>Shape</span>
      <select onchange="setPadOverride('${primary.id}','type',this.value)">${typeOpts}</select>
      <span>Size</span>
      <span class="cust-slider">
        <input type="range" min="0.4" max="2.2" step="0.05" value="${curScale.toFixed(2)}"
          oninput="setPadSize('${editId}',+this.value);document.getElementById('cust-size-val').textContent=Math.round(this.value*100)+'%'">
        <span id="cust-size-val">${Math.round(curScale * 100)}%</span>
      </span>
      <span>Rotation</span>
      <span class="cust-slider">
        <input type="range" min="-180" max="180" step="1" value="${curRot}"
          oninput="setPadShape('${editId}','rot',+this.value);document.getElementById('cust-rot-val').textContent=this.value+'°'">
        <span id="cust-rot-val">${curRot}°</span>
      </span>
    </div>
    ${finSet ? `<div class="cust-fin-lbl">Finish</div>${finishRow}` : ''}
    <button class="btn-secondary" style="margin-top:8px;width:100%;font-size:.72rem;padding:4px;"
      title="Draw this zone a second time on the map — for Y-splitters / doubled triggers (same settings, same sounds)"
      onclick="toggleMirrorPad('${primary.id}')">${(padOverrides[primary.id]||{}).mirror ? '&#x2715; Remove mirror pad' : '&#x29C9; Add mirror pad'}</button>
    ${hasOv ? `<button class="btn-secondary" style="margin-top:6px;width:100%;font-size:.72rem;padding:4px;"
        onclick="resetPadOverride('${primary.id}')">&#x21BA; Reset to default</button>` : ''}
    <div class="cust-hint">Tip: select a pad on the map to drag it, or use the gold handles to resize &amp; rotate.</div>
  </details>`;

  const otherPads = pads.filter(p => p.id !== primary.id);
  const copyHtml  = otherPads.length ? `<div class="copy-pad-row">
    <label>Copy to:</label>
    <select id="copy-pad-target">${otherPads.map(p =>
      `<option value="${p.id}">${escHtml(p.id)} — ${escHtml(p.label)}</option>`).join('')}</select>
    <button class="btn-secondary" style="font-size:.7rem;padding:3px 8px;white-space:nowrap;"
      onclick="copyPad('${primary.id}', document.getElementById('copy-pad-target').value)">Copy</button>
  </div>
  <div class="copy-pad-row">
    <label>Swap with:</label>
    <select id="swap-pad-target">${otherPads.map(p =>
      `<option value="${p.id}">${escHtml(p.id)} — ${escHtml(p.label)}</option>`).join('')}</select>
    <button class="btn-secondary" style="font-size:.7rem;padding:3px 8px;white-space:nowrap;"
      onclick="swapPad('${primary.id}', document.getElementById('swap-pad-target').value)">Swap</button>
  </div>` : '';

  const hexHtml = `<div style="margin-top:8px;padding-top:6px;border-top:1px solid #2a2a3e;">
    <button class="btn-secondary" style="font-size:.68rem;padding:3px 8px;"
      onclick="hexInspect('${primary.id}')">&#x1F50D; Inspect bytes</button>
    <pre id="hex-output-${primary.id}" class="hex-output" style="display:none;"></pre>
  </div>`;

  el.innerHTML = `<div class="det-card">
    <div class="det-hdr">
      <span class="det-id">${escHtml(group.label)}</span>
      <span class="det-input" title="Physical input">${escHtml(group.jackLabel)}</span>
    </div>
    ${zoneHtml}${paramsHtml}${custHtml}${copyHtml}${hexHtml}
  </div>`;
}

// ── Assignment flow ───────────────────────────────────────────────────────────
function selectPadLayer(padId, layer) {
  selectedPad    = {id: padId, layer};
  selectedMapPad = padId;
  selectedGroup  = PAD_TO_GROUP[padId] || selectedGroup;
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  renderInstruments();  // refresh "current" highlight in browser
  setMsg(`Click an instrument to assign to ${padId} Layer ${layer.toUpperCase()}`);
}

function clearSelection() {
  selectedPad    = null;
  selectedGroup  = null;
  selectedMapPad = null;
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
}

function updateAssignBanner() {
  postSelect();
  const el = document.getElementById('assign-target');
  if (!el) return;
  if (selectedPad) {
    const p     = pads.find(p => p.id === selectedPad.id);
    const label = p ? p.label : selectedPad.id;
    el.className = 'assign-target';
    el.innerHTML = `<strong>${escHtml(selectedPad.id)}</strong> ${escHtml(label)}`
      + ` &ndash; Layer ${selectedPad.layer.toUpperCase()}`
      + ` <span class="clr" onclick="clearSelection()" title="Cancel">&#xD7;</span>`;
  } else {
    el.className = 'assign-target empty';
    el.textContent = 'Click a pad or jack above to assign instruments';
  }
}

async function clearLayer(padId, layer) {
  const data = await api('/clear', {pad_id: padId, layer});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// Gate time (off 53): 0–99 = Free ms, 100–109 = sync divisions, 255 = OFF
const GATE_SYNC = ['Sync:1/32','Sync:1/32T','Sync:1/16','Sync:1/16T',
                   'Sync:1/8','Sync:1/8T','Sync:1/4','Sync:1/4T','Sync:1/2','Sync:1/2T'];

function setGateMode(padId, v) {
  // 'free' → keep/restore a ms value; numeric strings are sync LUT values or 255
  setParam(padId, 'gate_time', v === 'free' ? 0 : +v);
}

async function setParam(padId, param, value) {
  if (window.VIEWER) return;  // viewer-mode: pad detail is read-only display
  if (isNaN(value)) return;
  const data = await api('/set_param', {pad_id: padId, param, value});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPadDetail();
  setMsg(data.message);
}

// ── Tags ──────────────────────────────────────────────────────────────────────
async function loadTags() {
  const data = await fetch('/api/tags').then(r => r.json()).catch(() => ({tags:{}}));
  instTags = data.tags || {};
  renderTagChips();
}

function renderTagChips() {
  const row = document.getElementById('tag-chips-row');
  if (!row) return;
  const allTags = new Set();
  for (const tags of Object.values(instTags)) tags.forEach(t => allTags.add(t));
  if (!allTags.size) { row.innerHTML = ''; return; }
  const sorted = [...allTags].sort();
  row.innerHTML = `<span class="tag-chip all-chip${!activeTagFilter ? ' active' : ''}" onclick="setTagFilter(null)">All</span>`
    + sorted.map(t => `<span class="tag-chip${activeTagFilter===t?' active':''}" onclick="setTagFilter('${escHtml(t)}')">${escHtml(t)}</span>`).join('');
}

function setTagFilter(tag) {
  activeTagFilter = (activeTagFilter === tag) ? null : tag;
  renderTagChips();
  renderInstruments();
}

async function saveInstrumentTags(sinRel, tags) {
  const data = await api('/set_tags', {sin_rel: sinRel, tags});
  if (data.error) { setMsg(data.error, true); return; }
  instTags = data.tags || {};
  renderTagChips();
  renderInstruments();
}

function editTagsInline(sinRel, triggerEl) {
  const current = (instTags[sinRel] || []).join(', ');
  const inp = document.createElement('input');
  inp.type = 'text'; inp.className = 'inst-tag-edit'; inp.value = current;
  inp.placeholder = 'tag1, tag2…'; inp.title = 'Comma-separated tags. Enter to save, Esc to cancel.';
  const finish = (save) => {
    if (save) {
      const tags = inp.value.split(',').map(t => t.trim()).filter(Boolean);
      saveInstrumentTags(sinRel, tags);
    } else {
      renderInstruments();
    }
  };
  inp.onkeydown = e => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    e.stopPropagation();
  };
  inp.onblur = () => finish(true);
  triggerEl.parentNode.replaceChild(inp, triggerEl);
  inp.focus(); inp.select();
}

// ── Instrument browser ────────────────────────────────────────────────────────
async function loadInstruments() {
  const data = await api('/instruments');
  avail       = data.instruments;
  instMtimes  = data.mtimes || {};
  renderInstruments();
}

function toggleCat(cat) {
  if (expandedCats.has(cat)) expandedCats.delete(cat);
  else expandedCats.add(cat);
  renderInstruments();
}

function renderInstItem(rel, inUse, currentPath) {
  const name      = rel.split('/').slice(1).join('/').replace(/\.sin$/i, '');
  const users     = inUse[rel] || [];
  const isCurr    = rel === currentPath;
  const isPlaying = previewRel === rel;
  const isStar    = favorites.has(rel);
  const tags      = instTags[rel] || [];

  let badge = '';
  if (users.length) {
    const isMine = users.some(u => selectedPad && u.id === selectedPad.id);
    const tip    = 'Used by: ' + users.map(u => `${u.id} Lyr ${u.layer}`).join(', ');
    const cls    = isMine ? 'in-use-badge mine' : 'in-use-badge';
    const lbl    = users.length === 1 ? users[0].id : `\xD7${users.length}`;
    badge = `<span class="${cls}" title="${escHtml(tip)}">${escHtml(lbl)}</span>`;
  }
  const waveId  = 'wv-' + rel.replace(/[^a-zA-Z0-9]/g, '_');
  const waveCanvas = `<canvas class="waveform-canvas" id="${escHtml(waveId)}" width="60" height="18"
    data-sin="${escHtml(rel)}" title="Waveform"></canvas>`;
  const playBtn = `<button class="play-btn${isPlaying ? ' playing' : ''}" `
    + `data-rel="${escHtml(rel)}" `
    + `onclick="event.stopPropagation();previewInstrument('${rel}')" `
    + `title="${isPlaying ? 'Stop' : 'Preview'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>`;
  const starBtn = `<button class="star-btn${isStar ? ' starred' : ''}" `
    + `onclick="event.stopPropagation();toggleFavorite('${rel}')" `
    + `title="${isStar ? 'Unstar' : 'Star'}">&#9733;</button>`;
  const abBtns = `<span class="ab-btns">
    <button class="ab-btn" onclick="event.stopPropagation();directAssign('${rel}','a')" title="Layer A">A</button>
    <button class="ab-btn" onclick="event.stopPropagation();directAssign('${rel}','b')" title="Layer B">B</button>
  </span>`;
  const tagHtml = tags.length
    ? tags.map(t => `<span class="inst-tag" onclick="event.stopPropagation();setTagFilter('${escHtml(t)}')" title="Filter by: ${escHtml(t)}">${escHtml(t)}</span>`).join('')
    : '';
  const editTagBtn = `<span class="inst-tag" style="opacity:.4;" title="Edit tags" onclick="event.stopPropagation();editTagsInline('${rel}',this)">&#9998;</span>`;
  const sinEditBtn = `<span class="inst-tag" style="opacity:.4;" title="Edit instrument parameters" onclick="event.stopPropagation();openSinEditor('${rel}')">&#9881;</span>`;
  const simBtn = `<span class="inst-tag" style="opacity:.4;" title="Find similar-sounding instruments" onclick="event.stopPropagation();openSimilar('${rel}')">&#8776;</span>`;
  const currStyle = isCurr ? ' style="background:#0a2218;border-left:2px solid #3a9060;"' : '';
  const hoverEvt  = hoverPreview
    ? ` onmouseenter="previewInstrument('${rel}')" onmouseleave="if(previewRel==='${rel}')stopPreview()"` : '';
  return `<div class="inst-item" onclick="assignInstrument('${rel}')" title="${escHtml(rel)}"${currStyle}${hoverEvt}>
    ${playBtn}${starBtn}<span class="iname">${escHtml(name)}</span>${badge}${waveCanvas}${tagHtml}${editTagBtn}${sinEditBtn}${simBtn}${abBtns}
  </div>`;
}

function renderInstruments() {
  const query     = document.getElementById('inst-search').value.toLowerCase();
  const el        = document.getElementById('inst-list');
  const searching = query.length > 0;
  const inUse     = buildInUseMap();

  let currentPath = null;
  if (selectedPad) {
    const sp = pads.find(p => p.id === selectedPad.id);
    if (sp) currentPath = selectedPad.layer === 'a' ? sp.layer_a_path : sp.layer_b_path;
  }

  const matchesFilters = r => {
    if (query && !r.toLowerCase().includes(query) && !(instTags[r] || []).some(t => t.toLowerCase().includes(query))) return false;
    if (activeTagFilter && !(instTags[r] || []).includes(activeTagFilter)) return false;
    return true;
  };

  // Starred section (filtered by search + tag when active)
  const starredRels = [...favorites].filter(r => avail[r] && matchesFilters(r));
  let starredHtml = '';
  if (starredRels.length) {
    starredHtml = `<div class="sect-hdr" style="border-left:2px solid #e8b820;">&#9733; Starred</div>`
      + starredRels.map(r => renderInstItem(r, inUse, currentPath)).join('');
  }

  // Recent section (hidden while searching/filtering)
  const recentRels = recentInst.filter(r => avail[r] && matchesFilters(r)).slice(0, 10);
  let recentHtml = '';
  if (recentRels.length && !searching) {
    recentHtml = `<div class="sect-hdr" style="border-left:2px solid #5a9aaa;">&#x23F0; Recent`
      + `<button class="layer-btn" style="margin-left:auto;font-size:.6rem;padding:1px 5px;" onclick="clearRecent()">Clear</button></div>`
      + recentRels.map(r => renderInstItem(r, inUse, currentPath)).join('');
  }

  // Categories
  const cats = {};
  for (const rel of Object.keys(avail)) {
    if (!matchesFilters(rel)) continue;
    const cat = rel.split('/')[0];
    if (!cats[cat]) cats[cat] = [];
    cats[cat].push(rel);
  }

  if (!Object.keys(cats).length && !starredRels.length) {
    el.innerHTML = '<p style="color:#666;font-size:.8rem;padding:8px">No instruments found.</p>';
    return;
  }

  // Use-count map for "most used" sort
  const useCount = {};
  for (const p of pads) {
    if (p.layer_a_path) useCount[p.layer_a_path] = (useCount[p.layer_a_path] || 0) + 1;
    if (p.layer_b_path) useCount[p.layer_b_path] = (useCount[p.layer_b_path] || 0) + 1;
  }

  const catsHtml = Object.keys(cats).sort().map(cat => {
    let items = cats[cat].slice();
    if (instSort === 'used') {
      items.sort((a, b) => (useCount[b] || 0) - (useCount[a] || 0) || a.localeCompare(b));
    } else if (instSort === 'recent') {
      items.sort((a, b) => (instMtimes[b] || 0) - (instMtimes[a] || 0));
    } else {
      items.sort((a, b) => a.localeCompare(b));
    }
    const collapsed = !searching && !expandedCats.has(cat);
    const arrow     = collapsed ? '&#9654;' : '&#9660;';
    const color     = catColor(cat);
    return `<div class="cat-header" style="border-left:2px solid ${color}" onclick="toggleCat('${escHtml(cat)}')">
        <span class="cat-arrow">${arrow}</span>${escHtml(cat)}
        <span class="cat-count">${items.length}</span>
      </div>
      <div class="cat-items" style="display:${collapsed?'none':'block'}">${items.map(r => renderInstItem(r, inUse, currentPath)).join('')}</div>`;
  }).join('');

  el.innerHTML = starredHtml + recentHtml + catsHtml;
  attachWaveObservers();
}

async function directAssign(sinRel, layer) {
  if (!selectedPad) {
    setMsg('Click a pad on the map first to target it.', true);
    return;
  }
  await assignInstrument(sinRel, selectedPad.id, layer);
}

async function assignInstrument(sinRel, forcePadId, forceLayer) {
  if (window.VIEWER) return;  // viewer-mode: read-only, no pad assignment
  const target = (forcePadId && forceLayer) ? {id: forcePadId, layer: forceLayer} : selectedPad;
  if (!target) {
    setMsg('Click a pad on the map first, then pick an instrument.', true);
    return;
  }
  const data = await api('/assign', {pad_id: target.id, layer: target.layer, sin_rel: sinRel});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  addToRecent(sinRel);
  if (autoPreview) previewInstrument(sinRel);
  // Advance to Layer B if A was just filled and B is empty
  if (!forcePadId && target.layer === 'a') {
    const updated = pads.find(p => p.id === target.id);
    if (updated && !updated.layer_b_path) {
      selectedPad = {id: target.id, layer: 'b'};
      updateAssignBanner();
    }
  }
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// ── Copy pad ──────────────────────────────────────────────────────────────────
async function copyPad(fromId, toId) {
  if (fromId === toId) { setMsg('Cannot copy pad to itself', true); return; }
  const data = await api('/copy_pad', {from_id: fromId, to_id: toId});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Swap pads ─────────────────────────────────────────────────────────────────
async function swapPad(fromId, toId) {
  if (fromId === toId) { setMsg('Cannot swap pad with itself', true); return; }
  const data = await api('/swap_pads', {pad_id_a: fromId, pad_id_b: toId});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Batch apply ───────────────────────────────────────────────────────────────
function batchToggle() {
  batchMode = !batchMode;
  batchSelected.clear();
  const btn = document.getElementById('batch-toggle-btn');
  const panel = document.getElementById('batch-panel');
  if (batchMode) {
    btn.style.background = '#1a3a0a';
    btn.style.borderColor = '#4a8020';
    btn.style.color = '#a0d060';
    panel.classList.add('active');
    document.getElementById('batch-count').textContent = '0 pads selected';
    setMsg('Click pads to select, then choose a parameter and value to apply');
  } else {
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color = '';
    panel.classList.remove('active');
  }
  renderDrumMap();
}

function batchSelectAll() {
  pads.forEach(p => batchSelected.add(p.id));
  document.getElementById('batch-count').textContent = batchSelected.size + ' pads selected';
  renderDrumMap();
}

function batchClearSel() {
  batchSelected.clear();
  document.getElementById('batch-count').textContent = '0 pads selected';
  renderDrumMap();
}

async function batchApply() {
  if (!batchSelected.size) { setMsg('No pads selected', true); return; }
  const param = document.getElementById('batch-param').value;
  const value = parseInt(document.getElementById('batch-value').value, 10);
  if (isNaN(value)) { setMsg('Enter a numeric value', true); return; }
  const data = await api('/batch_set_param', {pad_ids: [...batchSelected], param, value});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Check broken paths ────────────────────────────────────────────────────────
async function checkPaths() {
  const data = await fetch('/api/check_paths').then(r => r.json()).catch(() => ({broken: []}));
  brokenPaths = new Set(data.broken || []);
  if (brokenPaths.size) {
    setMsg(`⚠ ${brokenPaths.size} instrument(s) not found on this machine — use 🔧 Fix broken paths in the Kits menu`, true);
  }
  renderDrumMap();
  renderPadDetail();
}

// ── Sample relink wizard ──────────────────────────────────────────────────────
async function showRelinkModal() {
  closeAllPopovers();
  const data = await fetch('/api/relink_suggest').then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  const box = document.getElementById('relink-body');
  if (!data.suggestions.length) {
    box.innerHTML = '<p style="color:#5a9a6a;font-size:.8rem;">✓ No broken instrument paths in this kit.</p>';
  } else {
    const rows = data.suggestions.map((s, i) => {
      const opts = s.candidates.map(c =>
        `<option value="${escHtml(c.rel)}">${escHtml(c.rel)}${c.score < 1 ? ` (${Math.round(c.score*100)}%)` : ''}</option>`
      ).join('');
      return `<tr>
        <td style="color:#e08020;" title="${escHtml(s.broken)}">⚠ ${escHtml(s.broken)}</td>
        <td>${s.candidates.length
          ? `<select id="rl-${i}" data-broken="${escHtml(s.broken)}" style="max-width:280px;">
               <option value="">— leave broken —</option>${opts}</select>`
          : '<span style="color:#667;">no match found in library/SD</span>'}</td>
      </tr>`;
    }).join('');
    box.innerHTML = `<div style="font-size:.7rem;color:#667;margin-bottom:6px;">
        ${data.suggestions.length} broken path(s). Best matches are pre-selected; relinking
        updates every pad that references the old path (one undo step).</div>
      <table style="width:100%;border-collapse:collapse;font-size:.72rem;">
        <thead><tr><th style="text-align:left;">Missing instrument</th><th style="text-align:left;">Replace with</th></tr></thead>
        <tbody>${rows}</tbody></table>`;
    // Pre-select the top candidate for each row
    data.suggestions.forEach((s, i) => {
      const sel = document.getElementById(`rl-${i}`);
      if (sel && s.candidates.length) sel.selectedIndex = 1;
    });
  }
  document.getElementById('relink-apply-btn').style.display = data.suggestions.length ? '' : 'none';
  document.getElementById('relink-modal').classList.add('open');
}

function closeRelinkModal() {
  document.getElementById('relink-modal').classList.remove('open');
}

async function applyRelink() {
  const mapping = {};
  document.querySelectorAll('#relink-body select[data-broken]').forEach(sel => {
    if (sel.value) mapping[sel.dataset.broken] = sel.value;
  });
  if (!Object.keys(mapping).length) { setMsg('Pick at least one replacement', true); return; }
  const data = await api('/relink_apply', {mapping});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  closeRelinkModal();
  await checkPaths();
  setMsg(data.message);
}

// ── Kit FX editor ─────────────────────────────────────────────────────────────
async function showKitFxModal() {
  closeAllPopovers();
  const d = await fetch('/api/kit_fx').then(r => r.json());
  if (d.error) { setMsg(d.error, true); return; }
  renderKitFx(d);
  document.getElementById('kitfx-modal').classList.add('open');
}

async function kitFxSet(param, value) {
  if (isNaN(value)) return;
  const data = await api('/kit_fx_set', {param, value});
  if (data.error) { setMsg(data.error, true); return; }
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderKitFx(data.fx);
  setMsg(data.message);
}

function kfxSlider(param, val, lo=0, hi=99) {
  return `<div class="param-slider-wrap">`
    + `<input type="range" min="${lo}" max="${hi}" value="${Math.min(hi,Math.max(lo,val))}" `
    + `oninput="this.nextElementSibling.textContent=this.value" `
    + `onchange="kitFxSet('${param}',+this.value)">`
    + `<span class="param-val">${val}</span></div>`;
}

function kfxNum(param, val, lo, hi, suffix='') {
  return `<span style="display:flex;align-items:center;gap:4px;">
    <input type="number" min="${lo}" max="${hi}" value="${val}" class="midi-select" style="width:60px;"
      onchange="kitFxSet('${param}',Math.min(${hi},Math.max(${lo},+this.value)))">${suffix}</span>`;
}

function kfxRow(label, control, title='') {
  return `<div class="param-row"><span class="param-lbl"${title?` title="${title}"`:''}>${label}</span>${control}</div>`;
}

function kfxSection(label) {
  return `<div class="param-row" style="margin-top:8px;padding-top:6px;border-top:1px solid #2a2a3e;">
    <span class="param-lbl" style="font-weight:600;color:#7ab3ef;font-size:.7rem;">${label}</span></div>`;
}

function renderKitFx(d) {
  const rvOpts = [];
  const rvMax = Math.max(d.reverb_max_seen, d.reverb.type);
  for (let i = 0; i <= rvMax; i++) {
    const nm = d.reverb_names[i] || `Type ${i}`;
    rvOpts.push(`<option value="${i}"${d.reverb.type===i?' selected':''}>${nm}</option>`);
  }
  const fxSel = (param, f) => `<select class="midi-select" style="width:130px;"
      onchange="kitFxSet('${param}',+this.value)">
      <option value="255"${f.type===255?' selected':''}>Off</option>
      ${d.fx_types.map((n,i)=>`<option value="${i}"${f.type===i?' selected':''}>${n}</option>`).join('')}
    </select>`;
  const fxBlock = (label, key, f) => {
    const isDelay = f.type >= 9 && f.type <= 16;
    return kfxSection(label)
      + kfxRow('Type', fxSel(`${key}_type`, f))
      + kfxRow('Level',    kfxSlider(`${key}_level`,    f.level))
      + kfxRow('Feedback', kfxSlider(`${key}_feedback`, f.feedback))
      + kfxRow('Depth',    kfxSlider(`${key}_depth`,    f.depth))
      + kfxRow('Rate',     kfxSlider(`${key}_rate`,     f.rate))
      + (isDelay ? kfxRow('Delay', kfxNum(`${key}_delay_ms`, f.delay_ms, 0, 3000, 'ms'),
                          'Delay time in ms (delay-family effects)') : '');
  };
  const eq = d.eq_comp;
  const freqHint = idx => d.known_freqs[idx] ? ` <span style="color:#667;font-size:.65rem;">${d.known_freqs[idx]}</span>` : '';
  document.getElementById('kitfx-body').innerHTML = `
    <span class="sin-ro-badge" style="align-self:flex-start;">offsets hardware-confirmed &mdash; reverb/FX type names beyond the hex-diff anchors are inferred from the manual</span>
    <div style="max-height:60vh;overflow-y:auto;padding-right:4px;">
    ${kfxSection('Reverb')}
    ${kfxRow('Type', `<select class="midi-select" style="width:130px;" onchange="kitFxSet('reverb_type',+this.value)">${rvOpts.join('')}</select>`,
             'Only Big Gate (2) and Close Mic (3) are hardware-confirmed names')}
    ${kfxRow('Level', kfxSlider('reverb_level', d.reverb.level))}
    ${kfxRow('Size',  kfxSlider('reverb_size',  d.reverb.size))}
    ${kfxRow('Color', kfxSlider('reverb_color', d.reverb.color), 'High-frequency damping — higher = brighter')}
    ${fxBlock('FX1', 'fx1', d.fx1)}
    ${fxBlock('FX2', 'fx2', d.fx2)}
    ${kfxSection('EQ')}
    ${kfxRow('LF Gain', kfxNum('eq_lf_gain', eq.lf_gain_db, -60, 12, 'dB'))}
    ${kfxRow('LF Freq', kfxNum('eq_lf_freq', eq.lf_freq_idx, 0, 127, `idx${freqHint(eq.lf_freq_idx)}`),
             'Sequential frequency-table index (10=58 Hz, 11=66 Hz); full table not yet enumerated')}
    ${kfxRow('HF Gain', kfxNum('eq_hf_gain', eq.hf_gain_db, -60, 12, 'dB'))}
    ${kfxRow('HF Freq', kfxNum('eq_hf_freq', eq.hf_freq_idx, 0, 127, `idx${freqHint(eq.hf_freq_idx)}`),
             'Sequential frequency-table index (77=8.7 kHz, 78=9.1 kHz); full table not yet enumerated')}
    ${kfxSection('Compressor')}
    ${kfxRow('Preset', `<select class="midi-select" style="width:130px;" onchange="kitFxSet('comp_preset',+this.value)">
      ${d.comp_presets.map((n,i)=>`<option value="${i}"${eq.comp_preset===i?' selected':''}>${n}</option>`).join('')}
    </select>`, '0=Master 1 and 1=Radio 1 hardware-confirmed; remaining order from the official editor guide')}
    ${kfxRow('Threshold', kfxNum('comp_threshold', eq.threshold_db, -90, 0, 'dB'))}
    ${kfxRow('Output',    kfxNum('comp_output',    eq.output_db,   -24, 24, 'dB'))}
    </div>
    <div style="font-size:.65rem;color:#667;margin-top:6px;">Edits write to the loaded kit's KIT header — save the kit to persist. Per-pad send levels live in each pad's FX/Zone section.</div>`;
}

// ── Kit bundles ───────────────────────────────────────────────────────────────
function exportBundle() {
  closeAllPopovers();
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  setMsg('Building bundle… (kit + instruments + samples)');
  window.location = '/api/export_bundle';
}

async function importBundle(file) {
  closeAllPopovers();
  setMsg(`Importing ${file.name}…`);
  const buf = await file.arrayBuffer();
  let bin = '';
  const bytes = new Uint8Array(buf);
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  const data = await api('/import_bundle', {data_b64: btoa(bin)});
  if (data.error) { setMsg(data.error, true); return; }
  kits = data.kits;
  avail = data.instruments;
  renderKitList();
  renderInstruments();
  await checkPaths();
  setMsg(data.message);
}

// ── Kit diff ──────────────────────────────────────────────────────────────────
function showDiffModal() {
  closeAllPopovers();
  const sel = document.getElementById('diff-kit-select');
  sel.innerHTML = '<option value="">— select a kit —</option>'
    + kits.map(k => `<option value="${escHtml(k.path)}">${escHtml(k.name)}</option>`).join('');
  document.getElementById('diff-result').innerHTML = '';
  document.getElementById('diff-modal').classList.add('open');
}

function closeDiffModal() {
  document.getElementById('diff-modal').classList.remove('open');
}

async function runDiff() {
  const path = document.getElementById('diff-kit-select').value;
  if (!path) { setMsg('Select a kit to compare', true); return; }
  const data = await api('/diff_kit', {path});
  if (data.error) { setMsg(data.error, true); return; }
  const box = document.getElementById('diff-result');
  if (!data.diff.length) {
    box.innerHTML = `<div class="diff-no-diff">No differences found between current kit and ${escHtml(data.other_name)}.</div>`;
    return;
  }
  const LABELS = {
    layer_a: 'Layer A', layer_b: 'Layer B', midi_note: 'MIDI note',
    la_level: 'A level', la_pan: 'A pan', la_pitch: 'A pitch', la_fine: 'A fine pitch', la_loop: 'A loop',
    la_decay: 'A decay', la_vel_vol: 'A vel→vol',
    lb_level: 'B level', lb_pan: 'B pan', lb_pitch: 'B pitch', lb_fine: 'B fine pitch', lb_loop: 'B loop',
    lb_decay: 'B decay', lb_vel_vol: 'B vel→vol',
  };
  const rows = data.diff.map(d => {
    if (d.only_in) {
      const where = d.only_in === 'current' ? 'only in current kit' : `only in ${escHtml(data.other_name)}`;
      return `<tr class="diff-row-changed"><td>${escHtml(d.id)}</td><td colspan="3" style="color:#889;">${where}</td></tr>`;
    }
    const fields = Object.entries(d.changed).map(([k, v]) => {
      const lbl = LABELS[k] || k;
      const cur = v.current === null ? '—' : String(v.current);
      const oth = v.other   === null ? '—' : String(v.other);
      return `<tr class="diff-row-changed"><td>${escHtml(d.id)}</td><td>${escHtml(lbl)}</td>`
        + `<td class="diff-val-cur">${escHtml(cur)}</td>`
        + `<td class="diff-val-oth">${escHtml(oth)}</td></tr>`;
    }).join('');
    return fields;
  }).join('');
  box.innerHTML = `<div style="font-size:.68rem;color:#556;margin-bottom:4px;">`
    + `${data.diff.length} pad(s) differ · comparing current kit vs ${escHtml(data.other_name)}</div>`
    + `<table><thead><tr><th>Pad</th><th>Param</th>`
    + `<th>Current</th><th>${escHtml(data.other_name)}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>`;
}

// ── Kit time machine ──────────────────────────────────────────────────────────
let tmSnaps = [];   // snapshots for the current kit (newest first)
let tmSel   = null; // focused snapshot id

const TM_DIFF_LABELS = {
  layer_a: 'Layer A', layer_b: 'Layer B', midi_note: 'MIDI note',
  la_level: 'A level', la_pan: 'A pan', la_pitch: 'A pitch',
  la_fine: 'A fine pitch', la_decay: 'A decay',
};

function tmFmtTime(iso, ts) {
  const d = iso ? new Date(iso) : new Date((ts || 0) * 1000);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  return sameDay ? time : d.toLocaleDateString([], {month: 'short', day: 'numeric'}) + ' ' + time;
}

function tmFmtSize(n) {
  return n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';
}

function openTimeMachine() {
  closeAllPopovers();
  document.getElementById('tm-modal').classList.add('open');
  loadTimeMachine();
}
function closeTimeMachine() {
  document.getElementById('tm-modal').classList.remove('open');
}

async function loadTimeMachine() {
  const all = document.getElementById('tm-all-kits').checked;
  const data = await fetch('/api/snapshots' + (all ? '?all=1' : '')).then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  document.getElementById('tm-kit-name').textContent =
    tmSnaps.length ? `· ${data.kit} · ${tmSnaps.length} snapshot(s)` : `· ${data.kit} · no snapshots yet`;
  if (!tmSnaps.some(s => s.id === tmSel)) tmSel = tmSnaps.length ? tmSnaps[0].id : null;
  renderTimeMachine();
}

function renderTimeMachine() {
  const list = document.getElementById('tm-list');
  const slider = document.getElementById('tm-slider');
  if (!tmSnaps.length) {
    list.innerHTML = `<div class="tm-empty">No snapshots for this kit yet. They appear automatically on load and save, or hit “Snapshot now”.</div>`;
    slider.max = 0; slider.value = 0;
    document.getElementById('tm-scrub-lbl').textContent = '';
    tmFillCompareSelects();
    return;
  }
  slider.max = tmSnaps.length - 1;
  const selIdx = Math.max(0, tmSnaps.findIndex(s => s.id === tmSel));
  slider.value = selIdx;
  const cur = tmSnaps[selIdx];
  document.getElementById('tm-scrub-lbl').textContent =
    `${selIdx + 1} / ${tmSnaps.length} · ${tmFmtTime(cur.iso, cur.ts)}`;

  list.innerHTML = tmSnaps.map(s => {
    const kind = (s.kind || 'manual');
    return `<div class="tm-snap${s.id === tmSel ? ' sel' : ''}" onclick="tmSelect('${s.id}')">
      <div class="tm-snap-top">
        <span class="tm-kind ${kind}">${escHtml(kind)}</span>
        <span class="tm-snap-lbl">${escHtml(s.label || '')}</span>
        <button class="tm-pin${s.pinned ? ' on' : ''}" title="${s.pinned ? 'Unpin' : 'Pin (survives cleanup)'}"
          onclick="event.stopPropagation();tmPin('${s.id}',${s.pinned ? 'false' : 'true'})">&#x1F4CC;</button>
        <span class="tm-snap-time">${tmFmtTime(s.iso, s.ts)}</span>
      </div>
      <div class="tm-snap-meta">
        <span>${s.assigned ?? '?'} pads assigned</span><span>${tmFmtSize(s.size || 0)}</span>
        ${document.getElementById('tm-all-kits').checked ? `<span>${escHtml(s.kit || '')}</span>` : ''}
      </div>
      <div class="tm-snap-actions">
        <button onclick="event.stopPropagation();tmRestore('${s.id}')">&#x21BA; Restore</button>
        <button onclick="event.stopPropagation();tmDiffVsCurrent('${s.id}')">&#x1F50D; vs current</button>
        <button class="tm-del" onclick="event.stopPropagation();tmDelete('${s.id}')">&#x2715;</button>
      </div>
    </div>`;
  }).join('');
  tmFillCompareSelects();
}

function tmFillCompareSelects() {
  const opts = `<option value="current">Current working state</option>`
    + tmSnaps.map(s => `<option value="${s.id}">${escHtml(s.label || s.id)} · ${tmFmtTime(s.iso, s.ts)}</option>`).join('');
  const a = document.getElementById('tm-cmp-a'), b = document.getElementById('tm-cmp-b');
  const av = a.value, bv = b.value;
  a.innerHTML = opts; b.innerHTML = opts;
  a.value = (tmSel && tmSnaps.some(s => s.id === av)) ? av : (tmSel || 'current');
  b.value = bv && (bv === 'current' || tmSnaps.some(s => s.id === bv)) ? bv : 'current';
}

function tmScrub(idx) {
  if (!tmSnaps[idx]) return;
  tmSel = tmSnaps[idx].id;
  renderTimeMachine();
  tmDiffVsCurrent(tmSel);
}

function tmSelect(id) {
  tmSel = id;
  renderTimeMachine();
  tmDiffVsCurrent(id);
}

async function tmSnapshotNow() {
  const data = await api('/snapshot', {kind: 'manual'});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.snapshot?.deduped) setMsg('No changes since the last snapshot');
  else setMsg('Snapshot saved');
  tmSnaps = data.snapshots || [];
  if (data.snapshot && !data.snapshot.deduped) tmSel = data.snapshot.id;
  document.getElementById('tm-kit-name').textContent = `· ${data.kit} · ${tmSnaps.length} snapshot(s)`;
  renderTimeMachine();
}

// Debounced auto-snapshot so an editing session leaves a trail (server dedupes).
let _autoSnapTimer = null;
function scheduleAutoSnapshot() {
  if (_autoSnapTimer) clearTimeout(_autoSnapTimer);
  _autoSnapTimer = setTimeout(() => {
    _autoSnapTimer = null;
    api('/snapshot', {kind: 'auto'}).then(() => {
      if (document.getElementById('tm-modal').classList.contains('open')) loadTimeMachine();
    }).catch(() => {});
  }, 20000);
}

function _tmRenderDiff(data, aLabel, bLabel) {
  const box = document.getElementById('tm-diff');
  if (data.error) { box.innerHTML = `<div class="tm-empty">${escHtml(data.error)}</div>`; return; }
  if (!data.diff.length) {
    box.innerHTML = `<div class="tm-empty">No differences between <b>${escHtml(aLabel)}</b> and <b>${escHtml(bLabel)}</b>.</div>`;
    return;
  }
  const rows = data.diff.map(d => {
    if (d.only_in) {
      const where = d.only_in === 'current' ? `only in ${escHtml(aLabel)}` : `only in ${escHtml(bLabel)}`;
      return `<tr class="chg"><td>${escHtml(d.id)}</td><td colspan="3" style="color:#889;">${where}</td></tr>`;
    }
    return Object.entries(d.changed).map(([k, v]) => {
      const lbl = TM_DIFF_LABELS[k] || k;
      const a = v.current === null ? '—' : String(v.current);
      const b = v.other   === null ? '—' : String(v.other);
      return `<tr class="chg"><td>${escHtml(d.id)}</td><td>${escHtml(lbl)}</td>`
        + `<td class="diff-val-cur">${escHtml(a)}</td><td class="diff-val-oth">${escHtml(b)}</td></tr>`;
    }).join('');
  }).join('');
  box.innerHTML = `<div style="font-size:.66rem;color:#556;margin-bottom:4px;">`
    + `${data.changed_count} pad(s) differ · <b>${escHtml(aLabel)}</b> vs <b>${escHtml(bLabel)}</b></div>`
    + `<table><thead><tr><th>Pad</th><th>Param</th><th>${escHtml(aLabel)}</th><th>${escHtml(bLabel)}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>`;
}

function _tmSourceLabel(id) {
  if (id === 'current') return 'Current';
  const s = tmSnaps.find(s => s.id === id);
  return s ? `${s.label} · ${tmFmtTime(s.iso, s.ts)}` : id;
}

async function tmDiffVsCurrent(id) {
  const data = await api('/snapshot_diff', {a: id, b: 'current'});
  _tmRenderDiff(data, _tmSourceLabel(id), 'Current');
}

async function tmCompare() {
  const a = document.getElementById('tm-cmp-a').value;
  const b = document.getElementById('tm-cmp-b').value;
  const data = await api('/snapshot_diff', {a, b});
  _tmRenderDiff(data, _tmSourceLabel(a), _tmSourceLabel(b));
}

async function tmRestore(id) {
  const s = tmSnaps.find(s => s.id === id);
  if (!await appConfirm(`Restore "${s ? s.label : id}"? This replaces the working kit (undoable with Ctrl+Z).`, 'Restore')) return;
  const data = await api('/snapshot_restore', {id});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  refreshKitSize();
  checkPaths();
  const kfxModal = document.getElementById('kitfx-modal');
  if (kfxModal && kfxModal.classList.contains('open')) showKitFxModal();
  setMsg(data.message || 'Snapshot restored');
}

async function tmDelete(id) {
  const s = tmSnaps.find(s => s.id === id);
  if (!await appConfirm(`Delete snapshot "${s ? s.label : id}"? This cannot be undone.`, 'Delete')) return;
  const data = await api('/snapshot_delete', {id});
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  if (tmSel === id) tmSel = tmSnaps.length ? tmSnaps[0].id : null;
  document.getElementById('tm-kit-name').textContent = `· ${data.kit} · ${tmSnaps.length} snapshot(s)`;
  renderTimeMachine();
  setMsg('Snapshot deleted');
}

async function tmPin(id, pinned) {
  const data = await api('/snapshot_pin', {id, pinned});
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  renderTimeMachine();
}

// ── Instrument (.sin) editor ──────────────────────────────────────────────────
let sinEd = null;  // current /api/sin_detail payload while the editor modal is open

async function openSinEditor(rel) {
  const data = await fetch('/api/sin_detail?sin=' + encodeURIComponent(rel)).then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  document.getElementById('sin-modal').classList.add('open');  // before render: lane needs real width
  renderSinEditor();
}

function closeSinEditor() {
  document.getElementById('sin-modal').classList.remove('open');
  sinEd = null;
}

function _sinSlider(id, label, val, min, max) {
  return `<div class="sin-row"><label>${label}</label>
    <input type="range" id="sin-${id}" min="${min}" max="${max}" value="${val}"
      oninput="document.getElementById('sin-${id}-v').textContent=this.value;if(this.id.includes('vel_'))renderVelCurve()">
    <span class="sin-val" id="sin-${id}-v">${val}</span></div>`;
}

function renderSinEditor() {
  const d = sinEd, p = d.params;
  const name = d.sin_rel.replace(/\.sin$/i, '');
  const ro = !d.editable;
  const dis = ro ? ' style="opacity:.55;pointer-events:none;"' : '';
  const groupOpts = Object.entries(d.groups)
    .map(([n, g]) => `<option value="${n}"${+n === p.group ? ' selected' : ''}>${escHtml(g)}</option>`).join('');
  const mapRows = d.mappings.map((m, i) => {
    const rr = m.rr > 127 ? m.rr - 256 : m.rr;
    return `<tr>
      <td title="${escHtml(m.sample)}">${escHtml(m.sample.split('/').pop())}</td>
      <td><input type="number" id="sm-${i}-vmin" min="0" max="127" value="${m.vmin}" oninput="renderZoneLane()"></td>
      <td><input type="number" id="sm-${i}-vmax" min="0" max="127" value="${m.vmax}" oninput="renderZoneLane()"></td>
      <td><input type="number" id="sm-${i}-rr" min="-2" max="127" value="${rr}"
        title="Round-robin index (-2 = hi-hat pedal function)"></td>
      <td><input type="number" id="sm-${i}-hhmin" min="0" max="127" value="${m.hh_min}"></td>
      <td><input type="number" id="sm-${i}-hhmax" min="0" max="127" value="${m.hh_max}"></td>
      <td style="white-space:nowrap;">
        <button class="layer-btn" title="Split zone at its midpoint" onclick="sinZoneOp('split',${i})">&#x2702;</button>
        <button class="layer-btn" title="Add a round-robin variant of this zone" onclick="sinZoneOp('rr',${i})">+RR</button>
        <button class="layer-btn clear" title="Delete zone" onclick="sinZoneOp('del',${i})"
          ${d.mappings.length < 2 ? 'disabled' : ''}>&#x2715;</button>
      </td>
    </tr>`;
  }).join('');
  document.getElementById('sin-body').innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <b style="font-size:.85rem;">${escHtml(name)}</b>
      ${ro ? '<span class="sin-ro-badge">read-only SD preset &mdash; sync library to edit a copy</span>' : ''}
      <button class="play-btn" onclick="previewInstrument(sinEd.sin_rel)" title="Preview">&#9654;</button>
    </div>
    <div class="sin-grid"${dis}>
      <div class="sin-row"><label>Group</label><select id="sin-group">${groupOpts}</select><span class="sin-val"></span></div>
      ${_sinSlider('level', 'Level', p.level, 0, 127)}
      ${_sinSlider('pan', 'Pan', p.pan, -50, 50)}
      ${_sinSlider('decay', 'Decay', p.decay, 0, 127)}
      ${_sinSlider('semi', 'Pitch semi', p.semi, -12, 12)}
      ${_sinSlider('fine', 'Pitch fine', p.fine, -50, 50)}
      ${_sinSlider('cutoff', 'Filter cutoff', p.cutoff, 0, 127)}
      <div class="sin-row"><label>Filter type</label><select id="sin-hipass">
        <option value="0"${p.hipass ? '' : ' selected'}>Low-pass</option>
        <option value="1"${p.hipass ? ' selected' : ''}>High-pass</option></select><span class="sin-val"></span></div>
      ${_sinSlider('vel_level', 'Vel &rarr; Level', p.vel_level, -99, 99)}
      ${_sinSlider('vel_decay', 'Vel &rarr; Decay', p.vel_decay, -99, 99)}
      ${_sinSlider('vel_pitch', 'Vel &rarr; Pitch', p.vel_pitch, -99, 99)}
      ${_sinSlider('vel_filter', 'Vel &rarr; Filter', p.vel_filter, -99, 99)}
      <div class="sin-row"><label>Loop</label><input type="checkbox" id="sin-loop"${p.loop ? ' checked' : ''}
        style="margin:0;width:auto;flex:none;"><span class="sin-val"></span></div>
      <div class="sin-row"><label>Cycle mode</label><select id="sin-cycle">
        <option value="0"${d.cycle_random ? '' : ' selected'}>Round-robin</option>
        <option value="1"${d.cycle_random ? ' selected' : ''}>Random</option></select><span class="sin-val"></span></div>
    </div>
    <div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;margin-top:8px;">
      <div>
        <div class="sin-sec-title" style="margin-top:0;">Velocity response
          <button class="sin-curve-tab" id="sct-vel_level" onclick="setCurveParam('vel_level')">Level</button>
          <button class="sin-curve-tab" id="sct-vel_decay" onclick="setCurveParam('vel_decay')">Decay</button>
          <button class="sin-curve-tab" id="sct-vel_pitch" onclick="setCurveParam('vel_pitch')">Pitch</button>
          <button class="sin-curve-tab" id="sct-vel_filter" onclick="setCurveParam('vel_filter')">Filter</button>
        </div>
        <svg id="sin-curve" width="240" height="120" title="Drag vertically to set depth"></svg>
        <div style="font-size:.6rem;color:#556;margin-top:2px;">soft hit → hard hit · drag curve to set depth</div>
      </div>
      <div style="flex:1;min-width:360px;">
        <div class="sin-sec-title" style="margin-top:0;">Velocity zones (${d.mappings.length}) — drag edges to move split points · click a zone to audition at that velocity</div>
        <svg id="sin-lane" width="100%" height="40"></svg>
      </div>
    </div>
    <div style="font-size:.7rem;color:#667;margin-top:6px;">Sample mappings (${d.mappings.length})</div>
    <div class="sin-maps"${dis}>
      <table><thead><tr><th>Sample</th><th>Vel&nbsp;min</th><th>Vel&nbsp;max</th><th>RR</th>
        <th>HH&nbsp;open&nbsp;min</th><th>HH&nbsp;open&nbsp;max</th><th></th></tr></thead>
      <tbody>${mapRows}</tbody></table>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px;">
      ${d.has_backup && d.editable ? '<button class="btn-secondary" onclick="revertSin()">Revert all edits</button>' : ''}
      ${ro ? '' : '<button class="btn-primary" onclick="saveSin()">Save</button>'}
      <button class="btn-secondary" onclick="closeSinEditor()">Close</button>
    </div>`;
  initSinVisuals();
}

// ── Velocity zone lane + response curves ──────────────────────────────────────
let curveParam   = 'vel_level';
let _laneLayout  = [];    // [{i, vmin, vmax, row}] from last renderZoneLane
let _laneDragB   = null;  // boundary value being dragged, or null
let _laneAudio   = null;  // lazy AudioContext for zone audition
const LANE_ROW_H = 22, LANE_AXIS_H = 14;

function initSinVisuals() {
  renderZoneLane();
  setCurveParam(curveParam);
  const lane = document.getElementById('sin-lane');
  lane.addEventListener('pointerdown', laneDown);
  lane.addEventListener('pointermove', laneHover);
  const curve = document.getElementById('sin-curve');
  curve.addEventListener('pointerdown', curveDown);
}

function _mapVals() {
  return sinEd.mappings.map((m, i) => ({
    i,
    vmin: +document.getElementById(`sm-${i}-vmin`).value,
    vmax: +document.getElementById(`sm-${i}-vmax`).value,
    sample: m.sample,
  }));
}

function _laneW() {
  const el = document.getElementById('sin-lane');
  return Math.max(360, el.clientWidth || el.parentElement.clientWidth || 560);
}

function _velFromX(evt) {
  const rect = document.getElementById('sin-lane').getBoundingClientRect();
  return Math.max(0, Math.min(127, (evt.clientX - rect.left) / rect.width * 128));
}

function renderZoneLane() {
  const lane = document.getElementById('sin-lane');
  if (!lane || !sinEd) return;
  const maps  = _mapVals();
  // Same-range mappings (round robins) stack vertically within one band
  const bands = {};
  maps.forEach(m => { const k = m.vmin + '-' + m.vmax; (bands[k] = bands[k] || []).push(m); });
  _laneLayout = [];
  for (const k in bands) bands[k].forEach((m, row) => _laneLayout.push({...m, row}));
  const rows = Math.max(1, ...Object.values(bands).map(b => b.length));
  const W = _laneW(), H = rows * LANE_ROW_H + LANE_AXIS_H;
  const sx = v => v / 128 * W;
  const colors = ['#3a7bd5', '#3aa07a', '#a07a3a', '#7a3aa0', '#a03a5a', '#5aa0c8'];
  let svg = '';
  // velocity grid lines + labels
  for (const v of [0, 32, 64, 96, 127]) {
    svg += `<line x1="${sx(v)}" y1="0" x2="${sx(v)}" y2="${H - LANE_AXIS_H}" stroke="#26334a" stroke-width="1"/>`
        +  `<text x="${Math.min(sx(v) + 2, W - 18)}" y="${H - 3}" font-size="9" fill="#667">${v}</text>`;
  }
  const bandKeys = Object.keys(bands).sort((a, b) => parseInt(a) - parseInt(b));
  _laneLayout.forEach(m => {
    const bi = bandKeys.indexOf(m.vmin + '-' + m.vmax);
    const x = sx(m.vmin), w = Math.max(2, sx(m.vmax + 1) - x);
    const y = m.row * LANE_ROW_H + 2;
    const name = m.sample.split('/').pop().replace(/\.wav$/i, '');
    svg += `<rect x="${x}" y="${y}" width="${w}" height="${LANE_ROW_H - 4}" rx="3"
              fill="${colors[bi % colors.length]}" fill-opacity="0.75" stroke="#0b0e15" stroke-width="1"/>`;
    if (w > 46) {
      svg += `<text x="${x + 4}" y="${y + 12}" font-size="9" fill="#eef"
                style="pointer-events:none">${escHtml(name.slice(0, Math.floor(w / 6)))}</text>`;
    }
  });
  lane.setAttribute('height', H);
  lane.setAttribute('viewBox', `0 0 ${W} ${H}`);
  lane.setAttribute('preserveAspectRatio', 'none');
  lane.innerHTML = svg;
}

function _nearBoundary(vel) {
  // Returns the boundary value (zone start, or end+1) within grab range of vel
  for (const m of _laneLayout) {
    if (Math.abs(vel - m.vmin) < 2.2) return m.vmin;
    if (Math.abs(vel - (m.vmax + 1)) < 2.2) return m.vmax + 1;
  }
  return null;
}

function laneHover(evt) {
  if (_laneDragB !== null) return;
  const lane = document.getElementById('sin-lane');
  const b = _nearBoundary(_velFromX(evt));
  lane.style.cursor = (b !== null && b > 0 && b < 128 && sinEd.editable) ? 'ew-resize' : 'pointer';
}

function laneDown(evt) {
  evt.preventDefault();
  const vel = _velFromX(evt);
  const b = _nearBoundary(vel);
  if (b !== null && b > 0 && b < 128 && sinEd.editable) {
    _laneDragB = b;
    const move = e => laneDragMove(e);
    const up = () => { _laneDragB = null;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up); };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    return;
  }
  // Audition: find the zone under the pointer at its clicked velocity
  const rect = document.getElementById('sin-lane').getBoundingClientRect();
  const row = Math.floor((evt.clientY - rect.top) / LANE_ROW_H);
  const v = Math.round(vel);
  const hit = _laneLayout.find(m => m.row === row && m.vmin <= v && v <= m.vmax)
           || _laneLayout.find(m => m.vmin <= v && v <= m.vmax);
  if (hit) playZone(hit.i, Math.max(1, v));
}

function laneDragMove(evt) {
  if (_laneDragB === null) return;
  const nb = Math.round(Math.max(1, Math.min(127, _velFromX(evt))));
  if (nb === _laneDragB) return;
  // Move every edge that sat on the old boundary (band mates + abutting neighbours)
  let valid = true;
  const edits = [];
  for (const m of _mapVals()) {
    let vmin = m.vmin, vmax = m.vmax;
    if (vmin === _laneDragB) vmin = nb;
    if (vmax + 1 === _laneDragB) vmax = nb - 1;
    if (vmin > vmax) { valid = false; break; }
    edits.push([m.i, vmin, vmax]);
  }
  if (!valid) return;  // refuse drags that would invert a zone
  for (const [i, vmin, vmax] of edits) {
    document.getElementById(`sm-${i}-vmin`).value = vmin;
    document.getElementById(`sm-${i}-vmax`).value = vmax;
  }
  _laneDragB = nb;
  renderZoneLane();
}

async function playZone(idx, vel) {
  try {
    _laneAudio = _laneAudio || new (window.AudioContext || window.webkitAudioContext)();
    const r = await fetch(`/api/wav?sin=${encodeURIComponent(sinEd.sin_rel)}&idx=${idx}`);
    if (!r.ok) throw new Error();
    const buf = await _laneAudio.decodeAudioData(await r.arrayBuffer());
    const src = _laneAudio.createBufferSource();
    src.buffer = buf;
    const g = _laneAudio.createGain();
    g.gain.value = Math.max(0.04, Math.pow(vel / 127, 2));
    src.connect(g); g.connect(_laneAudio.destination);
    src.start();
    setMsg(`▶ zone ${idx + 1} @ velocity ${vel}`);
  } catch {
    setMsg('Sample unavailable for preview (sync library from SD?)', true);
  }
}

function setCurveParam(p) {
  curveParam = p;
  document.querySelectorAll('.sin-curve-tab').forEach(b =>
    b.classList.toggle('active', b.id === 'sct-' + p));
  renderVelCurve();
}

function renderVelCurve() {
  const svg = document.getElementById('sin-curve');
  if (!svg || !sinEd) return;
  const d = +document.getElementById('sin-' + curveParam).value;  // -99..99 depth
  const W = 240, H = 120, pad = 8;
  // Depth visualization: output vs velocity; d=0 flat, +99 full upward slope
  const y = v => {
    const out = 0.5 + (d / 99) * (v / 127 - 0.5);
    return pad + (1 - out) * (H - 2 * pad);
  };
  let s = `<line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="#26334a"/>`;
  for (const v of [32, 64, 96]) {
    s += `<line x1="${v/127*W}" y1="0" x2="${v/127*W}" y2="${H}" stroke="#1c2738"/>`;
  }
  s += `<polyline points="${[0, 32, 64, 96, 127].map(v => `${v/127*W},${y(v)}`).join(' ')}"
         fill="none" stroke="#3a7bd5" stroke-width="2.5" stroke-linecap="round"/>`;
  s += `<circle cx="${W/2}" cy="${y(63.5)}" r="4" fill="#e0e8ff"/>`;
  s += `<text x="${W - 34}" y="14" font-size="10" fill="#88a">${d > 0 ? '+' : ''}${d}</text>`;
  svg.innerHTML = s;
}

function curveDown(evt) {
  evt.preventDefault();
  if (!sinEd.editable) return;
  const move = e => {
    const rect = document.getElementById('sin-curve').getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const d = Math.round((0.5 - frac) * 2 * 99);
    const slider = document.getElementById('sin-' + curveParam);
    slider.value = d;
    document.getElementById('sin-' + curveParam + '-v').textContent = d;
    renderVelCurve();
  };
  const up = () => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
  move(evt);
}

async function saveSin() {
  const params = _collectSinParams();
  const mappings = sinEd.mappings.map((m, i) => ({
    index: i,
    vmin:   +document.getElementById(`sm-${i}-vmin`).value,
    vmax:   +document.getElementById(`sm-${i}-vmax`).value,
    rr:     +document.getElementById(`sm-${i}-rr`).value,
    hh_min: +document.getElementById(`sm-${i}-hhmin`).value,
    hh_max: +document.getElementById(`sm-${i}-hhmax`).value,
  }));
  const data = await api('/sin_update', {sin_rel: sinEd.sin_rel, params,
                                         cycle_random: +document.getElementById('sin-cycle').value,
                                         mappings});
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

function _collectSinParams() {
  const gv = id => +document.getElementById('sin-' + id).value;
  return {
    group: gv('group'), level: gv('level'), pan: gv('pan'), decay: gv('decay'),
    semi: gv('semi'), fine: gv('fine'), cutoff: gv('cutoff'), hipass: gv('hipass'),
    vel_level: gv('vel_level'), vel_decay: gv('vel_decay'),
    vel_pitch: gv('vel_pitch'), vel_filter: gv('vel_filter'),
    loop: document.getElementById('sin-loop').checked ? 1 : 0,
  };
}

async function sinZoneOp(op, idx) {
  if (!sinEd.editable) return;
  // Current zone list from the live inputs, each cloning its original block (src)
  const zones = sinEd.mappings.map((m, i) => ({
    src: i,
    vmin:   +document.getElementById(`sm-${i}-vmin`).value,
    vmax:   +document.getElementById(`sm-${i}-vmax`).value,
    rr:     +document.getElementById(`sm-${i}-rr`).value,
    hh_min: +document.getElementById(`sm-${i}-hhmin`).value,
    hh_max: +document.getElementById(`sm-${i}-hhmax`).value,
  }));
  const z = zones[idx];
  if (op === 'split') {
    if (z.vmax - z.vmin < 1) { setMsg('Zone too narrow to split', true); return; }
    const mid = Math.floor((z.vmin + z.vmax) / 2);
    zones.splice(idx, 1,
      {...z, vmax: mid},
      {...z, vmin: mid + 1});
  } else if (op === 'rr') {
    const bandMax = Math.max(...zones.filter(o => o.vmin === z.vmin && o.vmax === z.vmax)
                                  .map(o => o.rr >= 0 && o.rr < 128 ? o.rr : 0));
    zones.splice(idx + 1, 0, {...z, rr: bandMax + 1});
  } else if (op === 'del') {
    if (zones.length < 2) { setMsg('An instrument needs at least one zone', true); return; }
    zones.splice(idx, 1);
  }
  const data = await api('/sin_zones', {
    sin_rel: sinEd.sin_rel, zones,
    cycle_random: +document.getElementById('sin-cycle').value,
    params: _collectSinParams(),
  });
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

async function revertSin() {
  const data = await api('/sin_revert', {sin_rel: sinEd.sin_rel});
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

// ── Kit duplicate ─────────────────────────────────────────────────────────────
function showDuplicateForm() {
  closeAllPopovers();
  const form = document.getElementById('dup-form');
  form.style.display = 'flex';
  const inp = document.getElementById('dup-name');
  inp.value = kitName.replace(/\.skt$/i, '') + ' copy';
  inp.focus();
  inp.select();
}
function cancelDuplicate() {
  document.getElementById('dup-form').style.display = 'none';
}
async function confirmDuplicate() {
  const name = document.getElementById('dup-name').value.trim();
  if (!name) { setMsg('Enter a name for the copy', true); return; }
  cancelDuplicate();
  const data = await api('/duplicate_kit', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kits = data.kits;
  renderKitList();
  setMsg(data.message);
}

// ── Clear all pads ────────────────────────────────────────────────────────────
async function clearAllPads() {
  if (!await appConfirm('Clear all pad assignments? This can be undone.', 'Clear all')) return;
  const data = await api('/clear_all_pads', {});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// ── Kit templates ─────────────────────────────────────────────────────────────
async function runTemplate(name) {
  setMsg(`Running template ${name}…`);
  const data = await api('/run_template', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = libSavePath;
  kits          = data.kits || kits;
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kne = document.getElementById('kit-name');
  kne.textContent    = '— ' + kitName;
  kne.contentEditable = 'true';
  document.getElementById('save-lib-btn').disabled   = !libSavePath;
  document.getElementById('dup-btn').disabled        = false;
  document.getElementById('clear-pads-btn').disabled = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(false, 0, []);
  renderKitList(); renderPatchPanel(); renderDrumMap(); renderPadDetail(); updateAssignBanner();
  setMsg(data.message || `Template ${name} applied`);
}

// ── Kit size ──────────────────────────────────────────────────────────────────
async function refreshKitSize() {
  const badge = document.getElementById('kit-size-badge');
  if (!badge || !kitName) { if (badge) badge.style.display = 'none'; return; }
  try {
    const data = await fetch('/api/kit_size').then(r => r.json());
    const mb   = (data.total_bytes / 1048576).toFixed(1);
    const warn = data.total_bytes > 178000000;  // warn above ~170 MB
    badge.textContent = `${mb} MB`;
    badge.style.display = '';
    badge.style.color = warn ? '#c08030' : '#557799';
    badge.title = `${data.found_wavs} / ${data.total_wavs} WAV files located`;
  } catch(e) { badge.style.display = 'none'; }
}

async function importAssignCSV(file) {
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  const text = await file.text();
  const assignments = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const cols = line.split(',').map(c => c.trim());
    if (cols.length < 2) continue;
    // Support: pad_id,sin_rel  OR  pad_id,layer,sin_rel
    if (cols.length === 2) {
      assignments.push({pad_id: cols[0], layer: 'a', sin_rel: cols[1]});
    } else {
      assignments.push({pad_id: cols[0], layer: cols[1].toLowerCase(), sin_rel: cols[2]});
    }
  }
  if (!assignments.length) { setMsg('No valid rows found in CSV', true); return; }
  setMsg(`Assigning ${assignments.length} pads from CSV…`);
  const data = await api('/batch_assign_csv', {assignments});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap(); renderPadDetail(); checkPaths();
  setMsg(data.message + (data.skipped?.length ? ` — skipped: ${data.skipped.slice(0,3).join(', ')}${data.skipped.length > 3 ? '…' : ''}` : ''));
}

function printMidiMap() {
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  window.open('/api/midi_map_html', '_blank');
}

async function exportKits() {
  const a = document.createElement('a');
  a.href = '/api/export_kits';
  a.download = 'strike_kits_export.json';
  a.click();
}

// ── SD sync ───────────────────────────────────────────────────────────────────
async function syncKitsFromCard() {
  setMsg('Syncing kits from card…');
  const data = await api('/sync_kits', {});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.kits) { kits = data.kits; renderKitList(); }
  setMsg(data.message);
}

let _syncPollTimer = null;

async function syncLibrary() {
  const btn = document.getElementById('sync-lib-btn');
  const prog = document.getElementById('sync-progress');
  const startData = await api('/sync_library', {});
  if (startData.error) { setMsg(startData.error, true); return; }
  prog.style.display = '';
  if (btn) btn.disabled = true;
  _pollSyncStatus();
}

async function _pollSyncStatus() {
  if (_syncPollTimer) { clearTimeout(_syncPollTimer); _syncPollTimer = null; }
  let data;
  try {
    const r = await fetch('/api/sync_status');
    data = await r.json();
  } catch(e) {
    _syncPollTimer = setTimeout(_pollSyncStatus, 1500);
    return;
  }

  const phaseEl  = document.getElementById('sync-phase');
  const barEl    = document.getElementById('sync-bar');
  const countsEl = document.getElementById('sync-counts');
  const detailEl = document.getElementById('sync-detail');
  const btn      = document.getElementById('sync-lib-btn');
  const prog     = document.getElementById('sync-progress');

  const phaseLabels = {kits:'Kits', instruments:'Instruments', samples:'Samples', done:'Done', error:'Error'};
  if (phaseEl)  phaseEl.textContent  = phaseLabels[data.phase] || data.phase;

  const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
  if (barEl)    barEl.style.width    = pct + '%';

  let counts = '';
  if (data.total > 0) counts = `${data.done}/${data.total}`;
  if (data.mb_copied > 0) counts += `  ${data.mb_copied.toFixed(0)} MB`;
  if (countsEl) countsEl.textContent = counts;
  if (detailEl) detailEl.textContent = data.detail || '';

  if (data.phase === 'done') {
    if (phaseEl) phaseEl.textContent = '✓ Done';
    if (barEl)   barEl.style.width   = '100%';
    if (countsEl) countsEl.textContent = `${data.copied} copied, ${data.skipped} skipped`;
    if (detailEl) detailEl.textContent = '';
    if (btn) btn.disabled = false;
    setMsg('Library sync complete.');
    // Refresh instrument browser
    const idata = await api('/instruments');
    if (idata.instruments) { avail = idata.instruments; instMtimes = idata.mtimes || {}; renderInstruments(); }
    setTimeout(() => { if (prog) prog.style.display = 'none'; }, 4000);
    return;
  }

  if (data.phase === 'error') {
    if (phaseEl) phaseEl.style.color = '#e05060';
    if (phaseEl) phaseEl.textContent = '✗ Error';
    if (detailEl) detailEl.textContent = data.error || 'Unknown error';
    if (btn) btn.disabled = false;
    setMsg(data.error || 'Sync failed', true);
    return;
  }

  // Still running — poll again in 1s
  _syncPollTimer = setTimeout(_pollSyncStatus, 1000);
}

// ── "More like this" similarity search ────────────────────────────────────────
let _simRel = null;

function closeSimilar() {
  document.getElementById('similar-modal').classList.remove('open');
  _simRel = null;
}

async function openSimilar(rel) {
  _simRel = rel;
  const modal = document.getElementById('similar-modal');
  const short = rel.split('/').slice(1).join('/').replace(/\.sin$/i, '');
  document.getElementById('sim-src').textContent = '· ' + short;
  document.getElementById('sim-body').innerHTML = '<p style="color:#667;font-size:.78rem;padding:8px;">Analysing…</p>';
  modal.classList.add('open');
  let data;
  try {
    const r = await fetch('/api/similar?n=10&sin=' + encodeURIComponent(rel));
    data = await r.json();
  } catch(e) {
    document.getElementById('sim-body').innerHTML = '<p style="color:#e07080;font-size:.78rem;padding:8px;">Request failed.</p>';
    return;
  }
  if (_simRel !== rel) return;   // superseded by another click
  renderSimilar(data);
}

function renderSimilar(data) {
  const body = document.getElementById('sim-body');
  if (data.error) {
    body.innerHTML = `<p style="color:#e07080;font-size:.78rem;padding:8px;">${escHtml(data.error)}</p>`;
    return;
  }
  if (data.unfingerprinted) {
    body.innerHTML = `<p style="color:#c89040;font-size:.78rem;padding:8px;">
      No audio fingerprint for this instrument &mdash; its WAV may not be on this machine
      (mount the SD card or Sync the library first).</p>`;
    return;
  }
  if (!data.results || !data.results.length) {
    body.innerHTML = `<p style="color:#667;font-size:.78rem;padding:8px;">
      No neighbours yet. Build the similarity index below to fingerprint the whole library
      (${data.corpus||0} analysed so far).</p>`;
    return;
  }
  const rows = data.results.map(x => `
    <div class="sim-row">
      <button class="play-btn" title="Preview" onclick="event.stopPropagation();previewInstrument('${x.sin_rel}')">&#9654;</button>
      <span class="sim-name" title="${escHtml(x.sin_rel)}" onclick="openSimilar('${x.sin_rel}')" style="cursor:pointer;">${escHtml(x.name)}</span>
      <span class="sim-grp">${escHtml(x.group)}</span>
      <button class="ab-btn" title="Assign to selected pad, Layer A" onclick="event.stopPropagation();directAssign('${x.sin_rel}','a')">A</button>
      <button class="ab-btn" title="Assign to selected pad, Layer B" onclick="event.stopPropagation();directAssign('${x.sin_rel}','b')">B</button>
      <span class="sim-dist" title="distance (lower = closer)">${x.dist.toFixed(2)}</span>
    </div>`).join('');
  body.innerHTML = `<div style="font-size:.66rem;color:#667;margin:2px 0 4px;">
    ${data.results.length} closest of ${data.corpus} fingerprinted &middot; click a name to pivot</div>${rows}`;
}

let _fpPollTimer = null;

async function buildFingerprints() {
  const btn = document.getElementById('sim-build-btn');
  const prog = document.getElementById('sim-build');
  const start = await api('/fingerprint_build', {});
  if (start.error) { setMsg(start.error, true); }
  prog.style.display = '';
  if (btn) btn.disabled = true;
  _pollFingerprintStatus();
}

async function _pollFingerprintStatus() {
  if (_fpPollTimer) { clearTimeout(_fpPollTimer); _fpPollTimer = null; }
  let data;
  try {
    const r = await fetch('/api/fingerprint_status');
    data = await r.json();
  } catch(e) {
    _fpPollTimer = setTimeout(_pollFingerprintStatus, 1500);
    return;
  }
  const phaseEl = document.getElementById('sim-phase');
  const barEl   = document.getElementById('sim-bar');
  const cntEl   = document.getElementById('sim-counts');
  const detEl   = document.getElementById('sim-detail');
  const btn     = document.getElementById('sim-build-btn');

  const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
  if (barEl) barEl.style.width = pct + '%';
  if (phaseEl) phaseEl.textContent = data.phase === 'done' ? '✓ Index built'
                : data.phase === 'error' ? '✗ Error' : 'Fingerprinting';
  if (cntEl) cntEl.textContent = data.total > 0 ? `${data.done}/${data.total}` : '';
  if (detEl) detEl.textContent = (data.detail || '').split('/').slice(1).join('/');

  if (data.phase === 'done') {
    if (cntEl) cntEl.textContent = `${data.computed} analysed, ${data.cached} cached, ${data.skipped} skipped`;
    if (detEl) detEl.textContent = '';
    if (btn) btn.disabled = false;
    setMsg('Similarity index built.');
    if (_simRel) openSimilar(_simRel);   // refresh results now the corpus exists
    return;
  }
  if (data.phase === 'error') {
    if (detEl) { detEl.textContent = data.error || 'Unknown error'; detEl.style.color = '#e05060'; }
    if (btn) btn.disabled = false;
    setMsg(data.error || 'Fingerprint build failed', true);
    return;
  }
  _fpPollTimer = setTimeout(_pollFingerprintStatus, 800);
}

// ── Hex inspector ─────────────────────────────────────────────────────────────
async function hexInspect(padId) {
  const el = document.getElementById('hex-output-' + padId);
  if (el && el.style.display !== 'none') { el.style.display = 'none'; return; }
  setMsg('Loading hex dump…');
  const data = await api('/hex_inspect', {pad_id: padId});
  if (data.error) { setMsg(data.error, true); return; }
  if (el) {
    el.textContent   = data.output;
    el.style.display = '';
  }
  setMsg('');
}

// ── Layer blend preview ───────────────────────────────────────────────────────
async function previewBlend(padId) {
  const pad = pads.find(p => p.id === padId);
  if (!pad || !pad.layer_a_path || !pad.layer_b_path) { setMsg('Need both layers assigned', true); return; }
  try {
    if (!_blendCtx) _blendCtx = new AudioContext();
    if (_blendCtx.state === 'suspended') await _blendCtx.resume();
    const vol = previewVol * previewVelGain;
    const [rawA, rawB] = await Promise.all([
      fetch('/api/preview?sin=' + encodeURIComponent(pad.layer_a_path)).then(r => { if (!r.ok) throw new Error('A unavailable'); return r.arrayBuffer(); }),
      fetch('/api/preview?sin=' + encodeURIComponent(pad.layer_b_path)).then(r => { if (!r.ok) throw new Error('B unavailable'); return r.arrayBuffer(); }),
    ]);
    const [bufA, bufB] = await Promise.all([
      _blendCtx.decodeAudioData(rawA),
      _blendCtx.decodeAudioData(rawB),
    ]);
    const master = _blendCtx.createGain();
    master.gain.value = vol;
    master.connect(_blendCtx.destination);
    const gA = _blendCtx.createGain(); gA.gain.value = (pad.la_level || 95) / 127; gA.connect(master);
    const gB = _blendCtx.createGain(); gB.gain.value = (pad.lb_level || 95) / 127; gB.connect(master);
    const sA = _blendCtx.createBufferSource(); sA.buffer = bufA; sA.connect(gA); sA.start();
    const sB = _blendCtx.createBufferSource(); sB.buffer = bufB; sB.connect(gB); sB.start();
    setMsg(`Blend: ${pad.layer_a_name} + ${pad.layer_b_name}`);
  } catch(err) {
    setMsg('Blend preview failed: ' + err.message, true);
  }
}

// ── Script runner ─────────────────────────────────────────────────────────────
async function loadTools() {
  const data = await api('/tools');
  const el   = document.getElementById('tools-list');
  if (!el || !data.tools) return;
  el.innerHTML = data.tools.map(t =>
    `<div class="tool-item">
       <span title="${escHtml(t.name)}">${escHtml(t.label)}</span>
       <button class="btn-secondary" style="font-size:.65rem;padding:2px 6px;"
         onclick="runTool('${escHtml(t.name)}')">Run</button>
     </div>`
  ).join('');
}

async function runTool(name) {
  const outEl = document.getElementById('tool-output');
  if (outEl) { outEl.textContent = `Running ${name}…`; outEl.classList.add('visible'); }
  setMsg(`Running ${name}…`);
  const data = await api('/run_tool', {name});
  if (data.error) {
    if (outEl) outEl.textContent = 'Error: ' + data.error;
    setMsg(data.error, true);
    return;
  }
  if (outEl) outEl.textContent = data.output || '(no output)';
  if (data.kits) { kits = data.kits; renderKitList(); }
  setMsg(`${name} finished`);
}

// ── WAV import ────────────────────────────────────────────────────────────────
let stagedFiles = [];  // [{file, minVel, maxVel, rrIndex}]

function toggleImportForm() {
  const el = document.getElementById('import-wav-form');
  const nowVisible = el.style.display !== 'none';
  if (nowVisible) {
    hideImportForm();
  } else {
    el.style.display = '';
    document.getElementById('import-progress').textContent = '';
  }
}

function hideImportForm() {
  document.getElementById('import-wav-form').style.display = 'none';
  stagedFiles = [];
  renderStagedFiles();
  document.getElementById('import-name').value = '';
  document.getElementById('import-progress').textContent = '';
}

function handleImportDrop(e) {
  e.preventDefault();
  document.getElementById('import-drop-zone').classList.remove('drag-over');
  const files = [...e.dataTransfer.files].filter(f => f.name.toLowerCase().endsWith('.wav'));
  if (!files.length) { setMsg('Drop WAV files only', true); return; }
  stageFiles(files);
}

function velBands(n) {
  if (n <= 0) return [];
  if (n === 1) return [[1, 127]];
  const size = Math.floor(127 / n);
  return Array.from({length: n}, (_, i) => {
    const lo = 1 + i * size;
    const hi = i < n - 1 ? lo + size - 1 : 127;
    return [lo, hi];
  });
}

function stageFiles(files) {
  const wasEmpty = stagedFiles.length === 0;
  for (const f of files) {
    stagedFiles.push({file: f, minVel: 1, maxVel: 127, rrIndex: stagedFiles.length + 1});
  }
  if (wasEmpty && stagedFiles.length > 0) {
    document.getElementById('import-name').value = stagedFiles[0].file.name.replace(/\.wav$/i, '');
  }
  recalcVelBands();
  renderStagedFiles();
}

function recalcVelBands() {
  const mode  = document.getElementById('import-mode').value;
  const n     = stagedFiles.length;
  if (mode === 'roundrobin') {
    stagedFiles.forEach((f, i) => { f.minVel = 1; f.maxVel = 127; f.rrIndex = i + 1; });
  } else {
    const bands = velBands(n);
    stagedFiles.forEach((f, i) => { f.minVel = bands[i][0]; f.maxVel = bands[i][1]; f.rrIndex = 1; });
  }
}

function renderStagedFiles() {
  const el   = document.getElementById('import-staged-list');
  const mode = document.getElementById('import-mode') ? document.getElementById('import-mode').value : 'velocity';
  const isRR = mode === 'roundrobin';

  if (!stagedFiles.length) {
    el.innerHTML = '';
    const btn = document.getElementById('import-create-btn');
    if (btn) btn.disabled = true;
    return;
  }

  el.innerHTML = stagedFiles.map((f, i) => {
    const fname = escHtml(f.file.name.replace(/\.wav$/i, ''));
    const velPart = isRR
      ? `<span class="staged-rr">RR&nbsp;${f.rrIndex}</span>`
      : `<input class="staged-vel" type="number" min="0" max="127" value="${f.minVel}"
           onchange="stagedFiles[${i}].minVel=Math.min(127,Math.max(0,+this.value))" title="Min velocity">
         <span class="staged-sep">–</span>
         <input class="staged-vel" type="number" min="0" max="127" value="${f.maxVel}"
           onchange="stagedFiles[${i}].maxVel=Math.min(127,Math.max(0,+this.value))" title="Max velocity">`;
    return `<div class="staged-row">
      <span class="staged-name" title="${escHtml(f.file.name)}">${fname}</span>
      ${velPart}
      <button class="layer-btn" onclick="removeStagedFile(${i})" title="Remove">&#x2715;</button>
    </div>`;
  }).join('');

  const btn = document.getElementById('import-create-btn');
  if (btn) btn.disabled = false;
}

function removeStagedFile(idx) {
  stagedFiles.splice(idx, 1);
  if (!stagedFiles.length) document.getElementById('import-name').value = '';
  recalcVelBands();
  renderStagedFiles();
}

async function createInstrument() {
  if (!stagedFiles.length) return;
  const category  = document.getElementById('import-category').value.trim() || 'Custom';
  const name      = document.getElementById('import-name').value.trim()
                 || stagedFiles[0].file.name.replace(/\.wav$/i, '');
  const mode      = document.getElementById('import-mode').value;
  const normalize = document.getElementById('import-normalize')?.checked ?? false;
  const auto_map  = document.getElementById('import-automap')?.checked ?? false;
  const prog     = document.getElementById('import-progress');
  prog.style.color = '';
  prog.textContent = 'Reading files…';

  const btn = document.getElementById('import-create-btn');
  btn.disabled = true;

  try {
    const wavs = [];
    for (let i = 0; i < stagedFiles.length; i++) {
      const f   = stagedFiles[i];
      prog.textContent = `Reading ${i + 1}/${stagedFiles.length}: ${f.file.name}`;
      const buf = await f.file.arrayBuffer();
      // Chunked btoa to avoid call stack overflow on large files
      const u8  = new Uint8Array(buf);
      let bin   = '';
      for (let j = 0; j < u8.length; j += 8192) {
        bin += String.fromCharCode(...u8.subarray(j, j + 8192));
      }
      wavs.push({
        filename:  f.file.name,
        data:      btoa(bin),
        min_vel:   f.minVel,
        max_vel:   f.maxVel,
        rr_index:  f.rrIndex,
      });
    }

    prog.textContent = 'Creating instrument…';
    const resp = await fetch('/api/import_instrument', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({category, name, mode, normalize, auto_map, wavs}),
    });
    const data = await resp.json();
    if (data.error) {
      prog.style.color  = '#e08080';
      prog.textContent  = 'Error: ' + data.error;
      setMsg(data.error, true);
      btn.disabled = false;
    } else {
      avail = data.instruments;
      stagedFiles = [];
      document.getElementById('import-name').value = '';
      renderStagedFiles();
      renderInstruments();
      prog.style.color = '#88c090';
      prog.textContent = data.message;
      setMsg(data.message);
    }
  } catch (err) {
    prog.style.color = '#e08080';
    prog.textContent = 'Error: ' + err.message;
    btn.disabled = false;
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────
async function _doSave(path) {
  if (!path) { setMsg('No kit loaded', true); return; }
  const data = await api('/save', {path});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.kits) {
    kits = data.kits;
    state_kitPath = path;
    if (data.lib_save_path) libSavePath = data.lib_save_path;
    if (data.sd_save_path)  sdSavePath  = data.sd_save_path;
    renderKitList();
  }
  setDirtyState(false, null);
  setMsg(data.message);
}
async function saveToLibrary() { await _doSave(libSavePath); }
async function saveToSD()      { await _doSave(sdSavePath);  }
async function saveCustom() {
  const path = document.getElementById('save-path').value.trim();
  if (!path) { setMsg('Enter a save path', true); return; }
  await _doSave(path);
}

// ── New kit ───────────────────────────────────────────────────────────────────
function showNewKitForm() {
  document.getElementById('new-kit-form').style.display = 'block';
  const inp = document.getElementById('new-kit-name');
  inp.value = '';
  inp.focus();
}
function cancelNewKit() {
  document.getElementById('new-kit-form').style.display = 'none';
}
async function confirmNewKit() {
  const name = document.getElementById('new-kit-name').value.trim() || 'New Kit';
  cancelNewKit();
  const data = await api('/new_kit', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kits          = data.kits;
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = data.lib_save_path || '';
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kitNameEl2 = document.getElementById('kit-name');
  kitNameEl2.textContent = '— ' + kitName;
  kitNameEl2.contentEditable = 'true';
  document.getElementById('parse-warn').style.display = 'none';
  document.getElementById('save-lib-btn').disabled    = !libSavePath;
  document.getElementById('save-sd-btn').disabled     = !sdSavePath;
  document.getElementById('dup-btn').disabled         = false;
  document.getElementById('clear-pads-btn').disabled  = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(false, 0, []);
  renderKitList();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  setMsg(data.message);
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function checkStatus() {
  const s = await api('/status');
  const parts = [];
  if (s.user_mounted)   parts.push('&#x1F4BE; User: ' + s.user_path);
  else                  parts.push('&#x26A0; User card NOT mounted');
  if (s.preset_mounted) parts.push('&#x1F4C0; Preset: ' + s.preset_path);
  document.getElementById('vol-status').innerHTML = parts.join(' \xB7 ');
  const hint = document.getElementById('save-hint');
  if (hint) {
    const sep = (s.user_path || '').includes('\\') ? '\\' : '/';
    hint.textContent = s.user_mounted
      ? `Save to ${s.user_path}${sep}Kits${sep} to write back to the user card.`
      : 'Mount the user card to save back to SD.';
  }
}

(async () => {
  applyTheme();

  // Wire up SVG drag listeners once (they survive innerHTML replacements)
  const svgEl = document.getElementById('drum-svg');
  svgEl.addEventListener('mousemove', svgMouseMove);
  window.addEventListener('mouseup', e => {
    svgMouseUp(e);
    if (_velDrag?.lastVel != null) {
      setParam(_velDrag.padId, 'xfade_vel', _velDrag.lastVel);
    }
    _velDrag = null;
  });
  window.addEventListener('mousemove', e => {
    if (_velDrag) _applyVelDrag(e.clientX);
  });

  // Scroll-to-zoom on drum map; double-click resets
  document.getElementById('drum-svg-wrap').addEventListener('wheel', e => {
    e.preventDefault();
    const svg  = document.getElementById('drum-svg');
    const rect = svg.getBoundingClientRect();
    const mx   = svgView.x + (e.clientX - rect.left)  / rect.width  * svgView.w;
    const my   = svgView.y + (e.clientY - rect.top)   / rect.height * svgView.h;
    const factor = e.deltaY < 0 ? 0.85 : 1 / 0.85;
    const newW = Math.min(SVG_DEF_W * 3, Math.max(SVG_DEF_W * 0.2, svgView.w * factor));
    const newH = newW * SVG_DEF_H / SVG_DEF_W;
    svgView.x = mx - (e.clientX - rect.left)  / rect.width  * newW;
    svgView.y = my - (e.clientY - rect.top)   / rect.height * newH;
    svgView.w = newW;
    svgView.h = newH;
    applySvgView();
  }, {passive: false});
  document.getElementById('drum-svg-wrap').addEventListener('dblclick', e => {
    if (!e.target.closest('.map-pad')) {
      svgView = {x: 0, y: 0, w: SVG_DEF_W, h: SVG_DEF_H};
      applySvgView();
    }
  });

  // ── Drag-and-drop .skt kit loading ───────────────────────────────────────
  let _dndCount = 0;
  document.addEventListener('dragenter', e => {
    if ([...e.dataTransfer.types].includes('Files')) {
      _dndCount++;
      document.getElementById('drop-overlay').classList.add('active');
      e.preventDefault();
    }
  });
  document.addEventListener('dragover', e => {
    if ([...e.dataTransfer.types].includes('Files')) e.preventDefault();
  });
  document.addEventListener('dragleave', () => {
    _dndCount = Math.max(0, _dndCount - 1);
    if (!_dndCount) document.getElementById('drop-overlay').classList.remove('active');
  });
  document.addEventListener('drop', async e => {
    _dndCount = 0;
    document.getElementById('drop-overlay').classList.remove('active');
    if (e.target.closest && e.target.closest('#import-wav-form')) return;  // let WAV importer handle it
    const sktFiles = [...e.dataTransfer.files].filter(f => f.name.toLowerCase().endsWith('.skt'));
    if (!sktFiles.length) return;
    e.preventDefault();
    const file = sktFiles[0];
    setMsg(`Loading ${file.name}…`);
    try {
      const buf  = await file.arrayBuffer();
      const u8   = new Uint8Array(buf);
      let bin = '';
      for (let j = 0; j < u8.length; j += 8192) bin += String.fromCharCode(...u8.subarray(j, j + 8192));
      const resp = await fetch('/api/load_bytes', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({filename: file.name, data: btoa(bin)}),
      });
      const data = await resp.json();
      if (data.error) { setMsg(data.error, true); return; }
      applyKitData(data, '', {dirty: true});
      setMsg(data.message);
    } catch(err) {
      setMsg('Error loading file: ' + err.message, true);
    }
  });

  // Global keyboard shortcuts
  document.addEventListener('keydown', e => {
    // Don't intercept when focus is inside a text input
    const tag = document.activeElement?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    const mod = e.ctrlKey || e.metaKey;

    if (mod && !e.shiftKey && e.key === 'z') {
      e.preventDefault();
      if (undoCount > 0) undoLast();
      return;
    }
    if (mod && e.key === 's') {
      e.preventDefault();
      if (libSavePath) saveToLibrary();
      return;
    }
    if (!mod && e.key === 'Escape') {
      clearSelection();
      return;
    }
    if (!mod && e.key === ' ') {
      e.preventDefault();
      if (selectedPad) {
        const p = pads.find(p => p.id === selectedPad.id);
        const sinRel = p && (selectedPad.layer === 'a' ? p.layer_a_path : p.layer_b_path);
        if (sinRel) previewInstrument(sinRel);
      }
      return;
    }
    if (!mod && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      const keys = Object.keys(PAD_GROUPS);
      const cur  = selectedGroup ? keys.indexOf(selectedGroup) : -1;
      const next = Math.max(0, Math.min(keys.length - 1, cur + (e.key === 'ArrowRight' ? 1 : -1)));
      if (keys[next]) selectGroupFromPanel(keys[next]);
      return;
    }
    if (!mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      if (!selectedGroup) return;
      const g   = PAD_GROUPS[selectedGroup];
      if (!g)  return;
      const cur = g.pads.indexOf(selectedPad?.id ?? '');
      const idx = Math.max(0, Math.min(g.pads.length - 1, (cur < 0 ? 0 : cur) + (e.key === 'ArrowDown' ? 1 : -1)));
      const pid = g.pads[idx];
      if (pid) {
        selectedMapPad = pid;
        selectedPad    = {id: pid, layer: selectedPad?.layer ?? 'a'};
        updateAssignBanner(); renderPatchPanel(); renderDrumMap(); renderPadDetail();
      }
      return;
    }
  });

  applyPatchPanelState();
  updateLayoutBadge();

  // Apply saved browser toolbar prefs
  const volSlider = document.getElementById('preview-vol-slider');
  if (volSlider) volSlider.value = previewVol;
  const velSlider = document.getElementById('preview-vel-slider');
  try { if (velSlider) velSlider.value = parseFloat(localStorage.getItem('strike_previewVel') ?? '127') || 127; } catch(e) {}
  const sortEl = document.getElementById('inst-sort');
  if (sortEl) sortEl.value = instSort;
  const hoverChk = document.getElementById('hover-preview-chk');
  if (hoverChk) hoverChk.checked = hoverPreview;
  const autoChk = document.getElementById('auto-preview-chk');
  if (autoChk) autoChk.checked = autoPreview;

  // Kit-name inline rename
  const kitNameEl = document.getElementById('kit-name');
  kitNameEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); kitNameEl.blur(); }
    if (e.key === 'Escape') { kitNameEl.textContent = '— ' + kitName; kitNameEl.blur(); }
  });
  kitNameEl.addEventListener('blur', () => {
    if (kitNameEl.contentEditable !== 'true') return;
    const raw = kitNameEl.textContent.replace(/^—\s*/, '').trim();
    if (!raw || raw === kitName.replace(/\.skt$/i, '')) {
      kitNameEl.textContent = '— ' + kitName;
      return;
    }
    const newName = raw.endsWith('.skt') ? raw : raw + '.skt';
    kitName = newName;
    kitNameEl.textContent = '— ' + kitName;
    if (libSavePath) {
      const parts = libSavePath.replace(/\\/g, '/').split('/');
      parts[parts.length - 1] = newName;
      libSavePath = parts.join('/');
      document.getElementById('save-lib-btn').disabled = false;
      document.getElementById('save-path').value = libSavePath;
    }
    setMsg(`Kit name set to ${kitName} — save to apply`);
  });

  // Restore loop panel open state
  if (loopPanelOpen) {
    document.getElementById('loop-body').style.display = '';
    document.getElementById('loop-toggle-arrow').textContent = '▾';
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }

  await checkStatus();
  await loadKitList();
  await loadInstruments();
  loadTags();

  // Rehydrate if the server already has a kit loaded (page reload / second tab):
  // the served HTML is static, so without this the client starts blank.
  const sess = await api('/session');
  if (sess.loaded) {
    applyKitData(sess, sess.path, {dirty: sess.dirty, undoCount: sess.undo_count,
                                   historyLabels: sess.history_labels});
    setMsg(`Restored session — ${sess.name}`);
  }

  checkPaths();
  loadTools();
  renderPatchPanel();
  renderDrumMap();

  // Auto-save every 60 s while there are unsaved changes
  setInterval(async () => {
    if (undoCount > 0) await api('/autosave', {});
  }, 60000);

  // Check for crash-recovery autosaves from previous sessions
  (async () => {
    const data = await api('/autosaves');
    if (!data.autosaves?.length) return;
    const banner = document.createElement('div');
    banner.id = 'autosave-banner';
    const rows = data.autosaves.map(a =>
      `<span class="as-item"><strong>${escHtml(a.name)}</strong>`
      + `<a href="#" onclick="recoverAutosave('${escHtml(a.autosave_path)}','${escHtml(a.kit_path)}');return false;">Recover</a>`
      + `<a href="#" onclick="dismissAutosave('${escHtml(a.autosave_path)}',this);return false;">&#x2715;</a></span>`
    ).join('');
    if (data.autosaves.length === 1) {
      banner.innerHTML = `<span>&#9888;&nbsp;Unsaved changes found:</span>${rows}`;
    } else {
      banner.innerHTML =
        `<span>&#9888;&nbsp;Unsaved changes found for <strong>${data.autosaves.length} kits</strong></span>`
        + `<a href="#" onclick="document.getElementById('autosave-banner').classList.toggle('expanded');return false;">Show</a>`
        + `<a href="#" onclick="dismissAllAutosaves();return false;" style="opacity:.7;">Dismiss all</a>`
        + `<div id="as-list">${rows}</div>`;
    }
    banner.dataset.count = data.autosaves.length;
    document.body.prepend(banner);
  })();
})();

async function recoverAutosave(autosavePath, kitPath) {
  await openKit(autosavePath);
  if (kitPath) {
    document.getElementById('save-path').value = kitPath;
    libSavePath = kitPath;
    document.getElementById('save-lib-btn').disabled = false;
  }
  document.getElementById('autosave-banner')?.remove();
  setMsg('Recovered from autosave — review changes and save to keep them');
}

async function dismissAutosave(autosavePath, el) {
  await api('/delete_autosave', {path: autosavePath});
  const banner = document.getElementById('autosave-banner');
  if (el && banner && +banner.dataset.count > 1) {
    el.closest('.as-item')?.remove();
    banner.dataset.count = +banner.dataset.count - 1;
    if (+banner.dataset.count === 0) banner.remove();
  } else {
    banner?.remove();
  }
}

async function dismissAllAutosaves() {
  const data = await api('/autosaves');
  for (const a of (data.autosaves || [])) {
    await api('/delete_autosave', {path: a.autosave_path});
  }
  document.getElementById('autosave-banner')?.remove();
}
