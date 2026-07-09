// engine.js — client-side, READ-ONLY replacement for strike_remap.py's HTTP server.
//
// The extracted frontend (app.js) is byte-identical to the Python app's embedded
// <script> and still issues ~18 raw `fetch('/api/...')` calls plus the `api()` helper.
// Rather than rewrite any call site, this module installs a fetch interceptor BEFORE
// app.js runs: any `/api/*` URL is served locally by handleApi(); everything else
// (static files, factory JSON) falls through to the real fetch.
//
// Only the READ paths are implemented — mirrored handler-for-handler against the
// Python Handler.do_GET / do_POST. Every mutating route returns {error:'Read-only viewer'}.
// Binary/audio endpoints (/api/wav, /api/waveform, /api/preview, /api/kit_playback)
// return a 404 Response; the UI affordances that use them are hidden in viewer-mode.
//
// This is an ES module and runs deferred (after DOM parse). It installs the interceptor
// synchronously at import time, loads the static catalog + fingerprints, sets viewer-mode,
// then dynamically injects app.js as a classic <script> so the extracted frontend (global
// functions + inline onclick) works unchanged and runs AFTER interception is in place.

import { parseSkt } from '../skt.js';
import { parseSin, parseSinAllWavs, SIN_GROUPS } from '../sin.js';
// similarInstruments comes from ../similar.js. In dev it's dynamically imported (see
// loadStaticData); in the single-file bundle similar.js is flattened into the same
// scope, so the declaration below is stripped and references bind to its function.
// [bundle-strip-begin]
let similarInstruments = null;
// [bundle-strip-end]

// ── Install the fetch interceptor FIRST (before anything async / before app.js) ──
const _realFetch = window.fetch.bind(window);
window.fetch = (url, opts) => {
  const u = typeof url === 'string' ? url : (url && url.url) || String(url);
  if (u.startsWith('/api/')) return Promise.resolve(handleApi(u, opts));
  return _realFetch(url, opts);
};

// Viewer flag: app.js code guards mutating branches with `if (window.VIEWER) ...`.
window.VIEWER = true;

// ── Engine state (mirrors the relevant parts of the Python `state` dict) ──────────
const engine = {
  loaded: false,
  name: '',
  pads: [],            // padView() array (as /api/session `pads`)
  instruments: [],     // str table (ordered sin_rel paths)
  skt_lossless: true,
  message: '',
  sel_pad: null,
  param_rev: 0,
};

// Static data — injected as globals by the single-file bundler, else fetched in dev.
let FACTORY_CATALOG = {};       // { "<sin_rel>": {name, group, group_name, cycle, size, mappings} }
let FACTORY_FINGERPRINTS = {};  // { "<sin_rel>": {v, wav_rel, size, feats, factory} }

// ── JSON Response helpers ─────────────────────────────────────────────────────────
function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function notFound() {
  // Binary/audio endpoints the viewer can't serve (no filesystem / no WAVs in v1).
  return new Response('', { status: 404 });
}
const READ_ONLY = { error: 'Read-only viewer' };

// ── Static data loading ───────────────────────────────────────────────────────────
async function loadStaticData() {
  // Prefer bundler-injected globals; fall back to dev fetch of the repo-root JSON.
  if (window.FACTORY_CATALOG) {
    FACTORY_CATALOG = window.FACTORY_CATALOG;
  } else {
    try {
      const r = await _realFetch('../../factory_catalog.json');
      if (r.ok) {
        const j = await r.json();
        FACTORY_CATALOG = (j && j.instruments) ? j.instruments : (j || {});
      }
    } catch { /* absent in this worktree — viewer still loads kits, just no catalog data */ }
  }
  if (window.FACTORY_FINGERPRINTS) {
    FACTORY_FINGERPRINTS = window.FACTORY_FINGERPRINTS;
  } else {
    try {
      const r = await _realFetch('../../factory_fingerprints.json');
      if (r.ok) FACTORY_FINGERPRINTS = await r.json();
    } catch { /* committed at repo root; if truly absent, similarity degrades gracefully */ }
  }
  // Load the real similarity port if present; otherwise leave similarInstruments null.
  // [bundle-strip-begin] — the bundle flattens similar.js into this scope instead
  try {
    const mod = await import('../similar.js');
    similarInstruments = mod.similarInstruments || mod.default || null;
  } catch { similarInstruments = null; }
  // [bundle-strip-end]
}

// ── Query / body parsing ──────────────────────────────────────────────────────────
function parseQuery(u) {
  const q = u.indexOf('?');
  return new URLSearchParams(q >= 0 ? u.slice(q + 1) : '');
}
function apiPath(u) {
  const q = u.indexOf('?');
  return q >= 0 ? u.slice(0, q) : u;
}
function jsonBody(opts) {
  if (!opts || !opts.body) return {};
  try { return JSON.parse(opts.body); } catch { return {}; }
}

// ── Session view (mirrors GET /api/session) ───────────────────────────────────────
function sessionView() {
  if (!engine.loaded) return { loaded: false };
  return {
    loaded: true,
    name: engine.name,
    path: '',                       // no filesystem in the viewer
    pads: engine.pads,
    sd_save_path: '',
    lib_save_path: '',
    skt_lossless: engine.skt_lossless,
    dirty: false,                   // viewer never mutates
    undo_count: 0,
    history_labels: [],
  };
}

// ── selected_view (mirrors GET /api/selected) ─────────────────────────────────────
function selectedView() {
  const pid = engine.sel_pad;
  const pad = pid ? engine.pads.find((p) => p.id === pid) : null;
  if (!pad) return { pad_id: null, rev: engine.param_rev };
  return {
    pad_id: pid,
    label: pad.label || pid,
    rev: engine.param_rev,
    params: {
      la_level: pad.la_level,
      la_pitch: pad.la_pitch,
      la_decay: pad.la_decay,
      la_fcut: pad.la_fcut,
    },
  };
}

// ── check_paths (mirrors GET /api/check_paths); "available" = factory catalog keys ─
// Named engineCheckPaths (not checkPaths) because app.js's global `checkPaths()`
// (the frontend's fetch('/api/check_paths') caller) would otherwise collide with
// this one once both land in the same top-level scope in the single-file bundle
// (classic <script> tags share one global scope, unlike ES modules in dev).
function engineCheckPaths() {
  const broken = [];
  for (const pad of engine.pads) {
    for (const key of ['layer_a_path', 'layer_b_path']) {
      const sinRel = pad[key];
      if (!sinRel) continue;
      if (!(sinRel in FACTORY_CATALOG) && !broken.includes(sinRel)) broken.push(sinRel);
    }
  }
  return { broken };
}

// ── kit_size (mirrors GET /api/kit_size) ──────────────────────────────────────────
// No WAVs on disk in the viewer, so bytes are unknowable → benign zeroed shape. The UI
// (refreshKitSize) just shows "0.0 MB" / hides the badge — it never errors on this.
function kitSize() {
  return { total_bytes: 0, found_wavs: 0, total_wavs: 0 };
}

// ── sin_detail (mirrors GET /api/sin_detail) from the factory catalog entry ────────
// Read-only: fields the catalog can supply are filled; the rest are null. INST params
// (level/pan/decay/…) aren't in the catalog schema → null; mappings map to the catalog's.
// SIN_GROUPS comes from ../sin.js (imported above); in the single-file bundle sin.js is
// flattened into this same scope ahead of engine.js, so the name resolves either way.
function sinDetail(sinRel) {
  const cat = FACTORY_CATALOG[sinRel];
  if (!cat) return { error: `Instrument not found: ${sinRel}` };
  const mappings = (cat.mappings || []).map((m) => ({
    sample: m.wav_rel || null,
    vmin: m.vmin ?? null,
    vmax: m.vmax ?? null,
    rr: m.rr ?? null,
    hh_min: null,
    hh_max: null,
  }));
  return {
    // INST params — not in the catalog schema; null in the read-only viewer.
    group: cat.group ?? null,
    level: null, pan: null, decay: null, semi: null, fine: null,
    cutoff: null, hipass: null,
    vel_decay: null, vel_pitch: null, vel_filter: null, vel_level: null,
    loop: null,
    cycle_random: cat.cycle ?? null,
    mappings,
    sin_rel: sinRel,
    editable: false,          // viewer never writes .sin files
    has_backup: false,
    groups: SIN_GROUPS,
  };
}

// ── load_kit_bytes (mirrors POST /api/load_bytes) ─────────────────────────────────
function loadKitBytes(rawBytes, filename) {
  const parsed = parseSkt(rawBytes);   // { kit_raw, pads, instruments, tail }
  engine.loaded = true;
  engine.name = filename;
  engine.pads = parsed.pads;
  engine.instruments = parsed.instruments;
  // No JS writer (build_skt) exists yet, so round-trip can't be verified here → assume
  // lossless (matches the parsers' verified read-parity; a writer stage would confirm it).
  engine.skt_lossless = true;
  engine.message = `Loaded ${filename}`;
  engine.param_rev += 1;
  return {
    name: filename,
    message: engine.message,
    pads: engine.pads,
    lib_save_path: '',
    sd_save_path: '',
    skt_lossless: true,
  };
}

// ── Instruments map from the factory catalog (mirrors GET /api/instruments) ────────
function instrumentsView() {
  const instruments = {};
  for (const rel of Object.keys(FACTORY_CATALOG)) instruments[rel] = rel;  // value unused in viewer
  return { instruments, mtimes: {} };
}

// ── similar (mirrors GET /api/similar) ────────────────────────────────────────────
function similar(sinRel, n) {
  if (typeof similarInstruments === 'function') {
    return similarInstruments(sinRel, FACTORY_FINGERPRINTS, n);
  }
  // Stub fallback (real port arrives via ../similar.js). Report an empty corpus so the
  // modal shows "no neighbours yet" rather than erroring.
  const corpus = Object.values(FACTORY_FINGERPRINTS).filter((e) => e && e.feats).length;
  return { query: sinRel, results: [], unfingerprinted: false, corpus };
}

// ── The router ────────────────────────────────────────────────────────────────────
function handleApi(u, opts) {
  const method = (opts && opts.method ? opts.method : 'GET').toUpperCase();
  const path = apiPath(u);
  const qs = parseQuery(u);

  // ---- GET routes ----
  if (method === 'GET') {
    switch (path) {
      case '/api/status':
        return jsonResponse({
          user_mounted: false, preset_mounted: false,
          user_path: '', preset_path: '',
        });
      case '/api/session':
        return jsonResponse(sessionView());
      case '/api/kits':
        return jsonResponse({ kits: [] });
      case '/api/instruments':
        return jsonResponse(instrumentsView());
      case '/api/tags':
        return jsonResponse({ tags: {} });
      case '/api/selected':
        return jsonResponse(selectedView());
      case '/api/check_paths':
        return jsonResponse(engineCheckPaths());
      case '/api/kit_size':
        return jsonResponse(kitSize());
      case '/api/snapshots':
        return jsonResponse({ snapshots: [] });
      case '/api/autosaves':
        return jsonResponse({ autosaves: [] });
      case '/api/fingerprint_status':
        return jsonResponse({
          running: false, phase: '', detail: '',
          done: 0, total: 0, computed: 0, cached: 0, skipped: 0, error: '',
        });
      case '/api/sin_detail':
        return jsonResponse(sinDetail(qs.get('sin') || ''));
      case '/api/similar': {
        const sin = qs.get('sin') || '';
        if (!sin) return jsonResponse({ error: 'missing sin' }, 400);
        const n = parseInt(qs.get('n') || '10', 10) || 10;
        try { return jsonResponse(similar(sin, n)); }
        catch (e) { return jsonResponse({ error: String(e) }, 500); }
      }
      case '/api/tools':
        return jsonResponse({ tools: [] });          // Tools menu is hidden in viewer-mode
      // Binary/audio endpoints — no filesystem / no WAVs in v1 → 404 (UI hidden).
      case '/api/wav':
      case '/api/waveform':
      case '/api/preview':
      case '/api/kit_playback':
        return notFound();
      default:
        return notFound();
    }
  }

  // ---- POST routes ----
  if (method === 'POST') {
    switch (path) {
      case '/api/load_bytes': {
        try {
          const body = jsonBody(opts);
          const raw = base64ToU8(body.data || '');
          return jsonResponse(loadKitBytes(raw, body.filename || 'kit.skt'));
        } catch (e) {
          return jsonResponse({ error: String(e && e.message ? e.message : e) });
        }
      }
      case '/api/load':
        return jsonResponse({ error: 'Load a .skt by dropping it here' });
      case '/api/select':
        engine.sel_pad = (jsonBody(opts).pad_id) || null;
        return jsonResponse({ ok: true });
      // Every other POST is a mutation → read-only.
      default:
        return jsonResponse(READ_ONLY);
    }
  }

  return notFound();
}

// base64 → Uint8Array (mirrors the Python base64.b64decode on load_bytes).
function base64ToU8(b64) {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

// ── Test hook: load a kit from an ArrayBuffer through the same code path ───────────
// Verification harness calls window.__loadKitBytes(arrayBuffer) instead of driving the
// (hard-to-automate) drag-drop. Returns the load response object.
window.__loadKitBytes = function (arrayBuffer, filename = 'test.skt') {
  const u8 = new Uint8Array(arrayBuffer);
  return loadKitBytes(u8, filename);
};

// ── Boot: load static data, mark viewer-mode, then inject app.js ──────────────────
(async () => {
  await loadStaticData();
  document.body.classList.add('viewer-mode');

  // Add a visible file-input affordance for the empty state (drag-drop already exists).
  // Placed in the header's kit-picker group so it reads as "open a kit".
  installFilePicker();

  // Inject app.js as a CLASSIC script so its top-level const/functions become globals
  // and inline onclick handlers resolve — exactly as the original embedded <script> did.
  // This runs after the interceptor is installed and after DOM parse.
  // [bundle-strip-begin] — the bundle inlines app.js as its own <script> tag instead;
  // with the data globals injected, loadStaticData resolves in microtasks, which drain
  // before the next classic <script> executes, so ordering is preserved.
  const s = document.createElement('script');
  s.src = 'app.js';
  document.body.appendChild(s);
  // [bundle-strip-end]
})();

// A header <input type=file accept=".skt"> that reuses app.js's drop code path via the
// engine load hook, so the empty state is actionable without drag-drop.
function installFilePicker() {
  const header = document.querySelector('header');
  if (!header) return;
  const wrap = document.createElement('label');
  wrap.className = 'viewer-file-pick';
  wrap.title = 'Open a .skt kit file';
  wrap.innerHTML = '📁 Open .skt <input type="file" accept=".skt" style="display:none">';
  const input = wrap.querySelector('input');
  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      const buf = await file.arrayBuffer();
      const data = window.__loadKitBytes(buf, file.name);
      // app.js defines applyKitData/setMsg as globals once it has loaded.
      if (typeof window.applyKitData === 'function') {
        window.applyKitData(data, '', { dirty: false });
        if (typeof window.setMsg === 'function') window.setMsg(data.message);
      }
    } catch (err) {
      if (typeof window.setMsg === 'function') window.setMsg('Error loading file: ' + err.message, true);
    }
    input.value = '';
  });
  header.appendChild(wrap);
}
