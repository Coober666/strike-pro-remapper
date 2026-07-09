# Planned Features

Features are grouped by theme. Items marked **[easy]** are low-effort / mostly UI wiring;
**[medium]** need moderate new code; **[hard]** need reverse-engineering or significant architecture.

See `RESEARCH.md` for full context: community pain points, competitor landscape, official editor
parameter list, and distribution considerations.

---

## 🧭 Direction & principles (2026-07-06 reprioritization)

**Product ethos (hard filter):** *download-and-use — no setup, no accounts, no cloud, no
API keys, no per-use cost.* Anything that needs an LLM API, login, or hosted service is demoted
to optional/far-future, never core. Stdlib-only stays.

**The through-line is "shareable + usable anywhere."** The founding itch was editing at the kit
without the primary desktop setup,
but the bigger prize is **distribution** — a thing you can point to, that anyone can try
with no friction. Both point at the same answer: **a pure-web app, entered via a shareable
read-only viewer** (see § 🏛️ Architectural direction). A URL beats a download; a live demo beats a
repo. (Note: a laptop already gives full at-the-kit capability *today* in Chrome — the iPad is a
form-factor upgrade, not the only path.)

**Revised priority order:**
1. ~~Merge the feature branches~~ ✅ **done 2026-07-06** — all five merged to main, tested,
   pushed; branches pruned.
2. ~~**⭐ Web Viewer v1**~~ ✅ **built 2026-07-06** — JS parsers + baked data (factory catalog +
   fingerprints) + the existing read-only UI, assembled into a single self-contained
   `dist/strike_viewer.html` (~2.5 MB, works from a double-click / `file://`, `python
   tools/build_viewer.py`). **Hosting deferred by choice** (GitHub Pages needs a public repo);
   publish decision + the iPad field test are the remaining steps of "ship". **Then re-evaluate
   on real interest before porting editing.** (See § 🏛️ Architectural direction.)
3. **Local kit designer** (the NL-builder wow *without* the LLM — see Experimental #3) — lands in
   the web app naturally.
4. **Hardware batch** (Kit FX enums + drop-clutch test) — cheap; the MacBook covers at-the-kit.
5. Full-editor web port (stages 2–6 of the direction) — *only if the viewer earns it.*
6. Audio-reuse toys (sample lab, kit-from-loop) — later, in the web app.
- **Demoted:** LLM natural-language input (optional layer only); community registry (needs
  hosting/accounts — shrink to "share a bundle link"); standalone desktop packaging/signing (mooted
  by the single-`.html` web deliverable).

---

## 📱 Mobile / iPad-first **[medium — now top feature]**

The app is a Python server + browser client, so "mobile" = **run the server on an always-on
mini-PC/homelab server, use the iPad as the browser client** at `http://<box>:8765`. The
iPad never runs Python. This also dissolves the dev-logistics problem: develop on the desktop (or
the server box), app runs on the server box, iPad is the at-kit client — the primary laptop drops
out of the loop.

Two pieces, different sizes:
- **LAN access [tiny]:** bind `0.0.0.0` instead of `127.0.0.1` (`strike_remap.py` ~L7881), ideally
  a `--host`/`--port` flag. One caveat: any LAN device can then reach it — fine on a trusted home
  network. Prerequisite for *anything* iPad.
- **Touch-first UI [medium, the real work]:** responsive breakpoints exist, but the drum-map
  drag/mirror/zoom interactions are mouse-centric — need Pointer Events, bigger hit targets, and
  panel-collapse tuning for narrow/tablet viewports. (Supersedes the old "Mobile-friendly layout"
  bullet under UI / UX.) Bonus synergy: the kit-designer's slider/chip UI (#3) is inherently
  touch-friendly.

**Storage reality (corrected 2026-07-06):**
- **USB-C→USB-B to the module exposes the SD as USB mass storage** (WAVs can be pulled off via USB
  without ever removing the card, and `get_volumes()`'s mounted-volume scan works over USB → the SD
  mounts as a drive over USB). The Strike almost certainly enumerates as a **composite USB device:
  USB-MIDI *and* mass storage at once** — which is why the Web-MIDI features *and* the volume scan
  both work off one cable. (Earlier note claiming "MIDI only" was wrong.) So **no card-pulling is
  needed** — the storage last-mile largely evaporates if the server box has the module on USB.
- **The hard constraint is where the server runs, not file access.** The Python server must be the
  process that sees the mounted volume:
  - **Server on the box the module is plugged into + iPad = WiFi browser client** → the clean path.
    Needs a small always-on machine near the kit (Pi / mini-PC, within ~5 m USB
    reach). No card pulling.
  - **Server *on* the iPad is impractical:** iOS suspends backgrounded processes (server dies when
    you switch to Safari), the sandbox has no `/Volumes` for `get_volumes()`, and perf is poor.
- **Getting kits back *onto* the module:** with mass-storage-over-USB, the server writes to the
  mounted SD directly (existing save-to-SD path) — as long as the module is USB-connected to the
  server box. This iPad-client model suits homelab users; the packaged desktop exe covers the
  mass-market "just download it" audience.

**Usability on iPad Safari (latency is NOT the problem):**
- **Editing feels native-fast:** everything but audio/MIDI is client-side JS + tiny `fetch` calls;
  LAN round-trips are single-digit ms. iPads render the SVG map + 1,749-item list easily.
- **Web MIDI is unsupported in iOS/iPadOS Safari** — the app already gates it ("Web MIDI requires
  Chrome or Edge", `strike_remap.py` ~L3789/3870). So the **MIDI monitor, virtual-module mode, and
  SysEx trigger backup won't work in Safari** (the irony: those are the at-the-kit features).
  Workaround: a Web-MIDI-capable iOS browser (e.g. "Web MIDI Browser"), not stock Safari.
- **Touch + audio-unlock:** drum-map drag/mirror/zoom is mouse-centric → needs Pointer Events +
  bigger targets; iOS gates audio behind a user gesture (tap-to-preview works; auto-preview /
  live-loop may need one "arm" tap). Web Audio itself is fine (code already uses `webkitAudioContext`).

---

## 🏛️ Architectural direction: converge to ONE web app — enter via a shareable viewer

**Decision (2026-07-06):** the destination is a single **pure-browser app — no Python server** —
that runs everywhere and *progressively enhances* by browser capability. **Not two forks.** A
"mobile version" would just be the same app in a weaker browser; forking means maintaining the
crown-jewel lossless binary logic in two languages that *will* drift (→ kit corruption) — fatal
for a solo maintainer. One codebase, feature-detected tiers, Python app kept until the web app
reaches parity, then retired.

**Primary driver = distribution, not iPad.** The goal is for this to be shareable — "look what I did," maybe
it gets traction, maybe not. A **URL beats everything**: "click this link" demolishes "download an
unsigned .exe past a malware warning" and "install Python + run a script." A live thing anyone can
try in 5 s on any device is the best possible portfolio artifact *and* the purest download-and-use
ethos (no install, no server, no account, no cost). It **hosts free + forever on GitHub Pages**
(client-side → no backend cost) and **deletes the packaging/signing problem entirely** (§ Packaging
is mooted — the deliverable is a single self-contained `.html`).

**Strategy: distribution-first / viewer-first — ship the smallest publishable slice, don't start
the full port.** The scary, high-risk part (lossless *writers*, save-in-place) is deferred; the
first public artifact is a **read-only viewer** that needs only *parsers* + the UI + baked data.
It's genuinely shareable on its own, doubles as stage 1 of the port and the iPad experiment, and —
crucially — if editing never gets ported, you *still* have a complete, published, clickable thing.
Right risk posture for uncertain traction: minimize investment to first public artifact, ship it,
scale effort to whether people actually show up.

**The app is already ~56% browser code:** of ~7,900 lines, **~4,400 are the embedded HTML/CSS/JS
frontend** (already runs in a browser) and **~3,500 are the Python backend** (binary parse/build,
`.sin`, WAV/FFT/fingerprints, HTTP glue). So this is a **port of the backend into the UI it already
has**, not a rewrite. The UI stays; `fetch('/api/...')` calls become direct in-browser function
calls + browser file APIs. The Python app remains the full-featured editor the whole time — nothing
is thrown away, nothing stalls.

### Capability tiers (progressive enhancement)
- **Full tier** — Chromium desktop (Windows / macOS / Linux + Chrome
  or Edge): **File System Access API** (real folder access to the SD/library + silent save-in-place,
  matching today's Python app) + **Web MIDI** (monitor / virtual-module / trigger-backup) + Web
  Audio. Feature-complete.
- **Degraded tier** — Safari (desktop *and* all iPad browsers, since iOS locks every browser to
  WebKit): `<input type=file>` pick + export/download (no silent save), **no Web MIDI**. Mitigated
  by shipping baked static data (below) so browse/assign/similarity need zero file access.
- **Detection:** feature-detect `window.showDirectoryPicker` and `navigator.requestMIDIAccess`;
  adapt UI + save flow accordingly. (The Mac is full-tier in Chrome, degraded in Safari — browser
  choice, not OS, decides. The iPad is degraded no matter what.)

### Baked static data (extends the factory-fingerprints trick)
Ship the fixed factory content as static JSON so the app is fully useful with **no filesystem
access** (critical for the degraded tier): the existing `factory_fingerprints.json` **plus** a new
baked **instrument catalog** (factory `.sin` names / groups / sample refs). Then browse, assign,
tag-filter, and "more like this" all work offline from baked data; file access is only needed to
load the user's `.skt` and import custom WAVs. Generated by the Python dev tools (below).

### ⭐ Web Viewer v1 — the first public artifact (the actual next build)

A hosted, **read-only** kit explorer. Drop a `.skt`, see and hear it. Publishable on its own,
zero corruption risk (no writers), runs on every browser incl. iPad Safari. Hosted on GitHub Pages.

**What it needs (the low-risk half of the port):**
- **Parsers only, in JS:** `parse_skt` (+ pad payload offset reads → `_pad_view` shape) and
  `parse_sin` / `parse_sin_all_wavs` / `_sin_blocks`. **No writers** → the losslessness burden and
  its test gate don't apply to v1 (they arrive with editing).
- **The existing UI, reused:** drum map SVG, pad-detail (read-only), instrument browser, MIDI-map
  view, waveform thumbnails, the "≈ similar" browser. Strip/disable the mutating controls.
- **Baked static data:** `factory_fingerprints.json` + the new factory instrument catalog, so
  browsing + similarity + waveform/preview work with **no filesystem access**.
- **File input:** a single `<input type=file>` (or drag-drop) for the user's `.skt` — works on iPad
  Safari. Resolve its instrument refs against the baked catalog; where a factory sample is
  referenced, preview/waveform come from baked data (or a bundled sample subset / lazy fetch).
- **Audio:** Web Audio preview + waveform for factory samples (already browser-native).

**What it deliberately leaves OUT of v1 (defer to later stages):**
- **All editing / writing** — assign, params, `.sin` editor, kit FX, zone rebuild, save. (No
  `build_skt`/`patch_sin` → no corruption risk.)
- **Save/export, File System Access, IndexedDB persistence, folder-tree library access.**
- **User custom WAV import + on-the-fly fingerprinting** (baked factory set covers v1; the JS FFT
  can come with the sample lab / editing stages).
- **MIDI features** (monitor / virtual-module / trigger-backup) — Web MIDI absent in Safari anyway;
  add on the full tier later.

**Why this slice:** maximal shareability (a real tool: "explore your Strike kit + find similar
sounds in the browser") for minimal, *safe* work (parsers + baked data + existing UI); it's stage 1
of the migration below, not throwaway; and it's the honest iPad test.

### Port scope — Python (~3,500 lines) → JavaScript, graded

**Trivial (deterministic byte ops → JS `DataView`/`ArrayBuffer`, 1:1):**
`parse_skt`/`build_skt`, `parse_sin`/`patch_sin`/`rebuild_sin_zones`/`_sin_blocks`, all offset
constants + `_PARAM_MAP`/`_KIT_FX_PARAM_MAP`, `_pad_view` (build the JS object directly),
`set_pad_param`/`set_kit_fx`, the diff engine (`_diff_pad_lists`), snapshots/time-machine logic.

**Moderate:** WAV decode (`wave` → manual `DataView` parse; 24-bit needs hand-parsing since
decodeAudioData yields float), `normalize_wav`/`wav_peak`/`compute_waveform`; the fingerprint stack
(`_fft` radix-2 → JS, or OfflineAudioContext+Analyser; `extract_fingerprint`, `_knn_rank`,
`similar_instruments` — the k-NN math is trivial); bundle zip import/export (use native
`CompressionStream`/`DecompressionStream`, or a tiny vendored zip lib — keep the no-heavy-deps
spirit). localStorage already holds prefs/favorites/recents.

**Fiddly — the real work & risk:**
- **Losslessness (highest risk).** The `.skt`/`.sin` writers are the corruption boundary. Port the
  round-trip suites (`test_roundtrip`, `test_sin_roundtrip`) to run in **Node/CI against the same
  fixtures, requiring byte-identical output** — do this FIRST, before trusting any writer in JS.
- **File-location layer (biggest redesign).** `get_volumes`/`refresh_available`/`scan_instruments`/
  `_sin_abs`/`find_wav_for_sin*`/`_find_wav_in_roots` assume a real filesystem with path resolution.
  Replace with: *full tier* → a directory handle from `showDirectoryPicker`, walked lazily; *degraded
  tier* → file-picks + the baked catalog. Not hard code, but a genuine rethink of "how the app finds
  instruments/samples."
- **Persistence layer (new).** Where user data (kits, `tags.json`, snapshots, user fingerprints)
  lives: *full tier* → the picked directory; *degraded tier* → IndexedDB + import/export. New code.
- **Big kits (200 MB) on iPad** → watch memory; stream File reads, avoid holding everything.

**Stays Python — dev tooling, split by PURPOSE not platform (not shipped in the app):**
`build_factory_fingerprints.py` (+ a new catalog builder) generate the baked JSON; `hex_explorer.py`,
`make_metal_kit.py`, `analyze_offsets.py`, `scan_mute_groups.py`, `make_fixtures.py` and the
`test_*` suites stay as dev/CI scripts. The in-app **plugin/script runner + hex-inspect** (which
shell out to Python) are desktop-only concepts → drop or reimplement in JS. Round-trip tests gain
JS twins for the web build.

### Migration order (distribution-first; each stage is independently shippable)
0. **Bake the factory instrument catalog** (Python dev tool, sibling of
   `build_factory_fingerprints.py`) — the static data the viewer rides on.
1. **⭐ Web Viewer v1** (above): JS **parsers** + existing read-only UI + baked data → **publish on
   GitHub Pages.** This is the first public artifact; ship it before anything else. Doubles as the
   iPad touch/usability test. **Stop here and re-evaluate based on real interest.**
2. **JS writers, test-gated:** port `build_skt`/`patch_sin`/`rebuild_sin_zones` with the round-trip
   suites (`test_roundtrip`, `test_sin_roundtrip`) ported to run in **Node/CI, byte-identical output
   required** — this is the corruption boundary; prove it before any editing UI trusts it.
3. **Editing on the full tier:** re-enable the mutating UI; add File System Access (folder access +
   save-in-place) + audio/fingerprint port (FFT, WAV, k-NN) for custom samples.
4. **Persistence + degraded-tier saves:** IndexedDB for user data; file-pick + export-and-place /
   bundle-zip where File System Access is absent (Safari/iPad).
5. **Retire the `/api` server path:** swap remaining `fetch('/api/*')` for direct JS calls; add the
   graceful Web-MIDI-absent fallback (frontend already uses Web MIDI).
6. **Retire the Python app**; keep `tools/` (catalog/fingerprint builders, offset tools, `test_*`)
   as dev-only.

### Risk register
- Lossless drift in ported writers → **port tests first, CI byte-equality gate.**
- Safari/iPad file limits → baked catalog + bundle-zip + export-and-place saves.
- iPad memory on huge kits → streaming reads.
- Zip/deps → prefer native `CompressionStream`; if a lib is needed, vendor a tiny one.

**Effort:** **Viewer v1 is small** — parsers + baked data + the existing read-only UI, no writers,
no file/persistence layer, no test-gate. That's the whole point: a shareable artifact for a
fraction of the work. The *full editor* port is the multi-session part (stages 2–6), gated on
whether the viewer draws interest. Start the viewer **after the four feature branches merge** (don't
port a moving target); everything past stage 1 is "only if it earns it."

### Remote prep options (things doable away from the kit)
Critical path (review → merge → test merged → bake catalog → viewer) is blocked on being home
(merges need review; manual smoke test + all hardware need the module). But some things parallelize
with **no hardware / no manual testing** (verification is automated):
1. **⭐ Port `parse_skt`/`parse_sin` to JS under a Node-vs-Python parity test** on the synthetic
   fixtures (`make_fixtures.py`, deterministic, no library). Highest-leverage: de-risks the
   crown-jewel format logic, is stage-1 foundation, and won't be invalidated by the merge (the
   parsers predate all four branches). **Parsers only — no writers.** *(A copy/paste starter prompt
   for this exists; branch `web-parsers` off `main`.)*
2. **Merge-prep aid:** per-branch change/risk summary + the exact pre-resolved `ci.yml`/`PLANNED.md`/
   `CLAUDE.md` conflict files, so the eventual merge is mechanical.
3. **Draft the factory-catalog builder + schema** (Stage 0). Writing it is remote; running it needs
   the library — but a first cut is derivable from the committed `factory_fingerprints.json` alone.
4. **Viewer v1 design doc + GitHub Pages scaffold plan.** Lower value than #1.
- *Needs home:* the merges (review), the merged-whole manual smoke test, all hardware items.

---

## ✅ Done

### Pad parameters (all confirmed via hardware hex diff)
- Full pad assignment, layer A/B, xfade velocity, MIDI note
- Level sliders (Layer A off 6, Layer B off 26)
- Pan sliders (Layer A off 7, Layer B off 27)
- Pitch ±12 st (Layer A off 11, Layer B off 31)
- Fine pitch ±50 cents (Layer A off 12, Layer B off 32)
- Decay 0–99 (Layer A off 8, Layer B off 28)
- Filter cutoff 0–99 + enable/type flag (off 13/14, off 33/34)
- Loop mode On/Off per layer (off 21/41)
- Vel range min/max Layer A (off 19/20), Layer B xfade threshold (off 39)
- Velocity→Volume/Decay/Pitch/Filter per layer (off 15–18, off 35–38)
- Per-pad FX sends: Reverb (off 44), FX1 (off 45), FX2 (off 61), EQ/Comp enable (off 46)
- Priority Low/Med/High (off 48), Mute group Off/1–9 (off 49)
- Note Off Sent/None/Alt (off 50), MIDI channel 1–16 (off 51)
- Gate time full LUT (off 53): Free=0, Sync:32–Sync:2T=100–109, OFF=255
- Playback mode Mono/Poly (off 54)

### Kit-level FX offsets (all confirmed via hardware hex diff — not yet in UI)
- Reverb type/size/color/level (kit_raw[16–19])
- FX1 type/level/feedback/depth/rate (kit_raw[20–29])
- FX2 type/level/feedback/depth/rate (kit_raw[32–41])
- EQ/Comp: preset index, threshold, LF/HF gain, LF/HF freq index, output (kit_raw[44–50])

### App features
- Broken path detection (⚠ badge on drum map + in layer rows; `/api/check_paths`)
- Swap pads (full payload swap; "Swap with:" row in pad detail)
- Batch parameter apply (multi-select pads via Batch edit mode, apply one param to all)
- Kit diff (side-by-side comparison modal; "Compare with kit…" in Kits menu)
- Undo (20 steps) with labeled history dropdown
- Drag-and-drop kit loading
- WAV import → `.sin` creation
- Live loop preview (step sequencer, Web Audio API)
- Audio preview with volume + velocity sliders
- Waveform thumbnails in instrument browser (lazy-loaded, IntersectionObserver)
- Kit size meter in header (sums referenced WAV sizes, warns near 200 MB)
- Export kits to JSON (`/api/export_kits` — all library kits)
- Auto-save every 60s + crash recovery
- Keyboard shortcuts (arrows, Space, Ctrl+Z, Ctrl+S, Esc)
- Dark/light theme toggle
- Favorites ★ + Recent sections in instrument browser
- Sort options (A-Z / Most used / Recently added)
- Hover preview + Auto-preview on assign toggles
- Copy pad (full payload copy)
- Kit rename, duplicate, clear all pads
- 3-column layout + toolbar merged into header
- MIDI monitor (Web MIDI API — pad hit flashes drum map, plays preview; Chromium only)
- Full library sync from SD (background thread, live progress bar)
- Round-trip parser test (`tools/test_roundtrip.py`)
- Automatic lossless check on kit load (⚠ badge if mismatch)
- Cache-Control: no-store (prevents stale JS)
- Zoom on drum map (scroll-to-zoom SVG viewBox; double-click empty area to reset)
- Layer blend preview (▶ A+B button in pad detail; Web Audio API, respects level sliders)
- Export MIDI map PDF (🖨 Print MIDI map in Kits menu; opens printable HTML cheat sheet)
- Batch assign from CSV (📋 Import assignment CSV in Kits menu; `pad_id[,layer],sin_rel` format)
- Sample normalization on import (✓ Normalize to -0.1 dBFS checkbox in WAV import form)
- Search by tags (sidecar `library/tags.json`; ✎ edit tags per instrument; chip filter above browser)
- **Relink wizard** — 🔧 Fix broken paths… in Kits menu; exact-basename then fuzzy
  (difflib ≥0.6) suggestions from avail; rewrites the kit's instrument string table,
  all affected pads in one undo step (`/api/relink_suggest`, `/api/relink_apply`)
- **Kit bundles** — 📦 Export/Import kit bundle in Kits menu; self-contained zip
  (manifest.json + kit/ + instruments/<sin_rel> + samples/<wav_rel>) mirroring library
  layout so no path rewriting is needed; import never overwrites (identical→skip,
  different→conflict kept existing, kit name collisions get " (n)" suffix)
- **Instrument (.sin) editor** — full INST-block parameter editing (group, level/pan/decay,
  semi/fine pitch, filter type+cutoff, vel→level/decay/pitch/filter, loop), cycle mode
  (round-robin/random), per-mapping velocity + hi-hat pedal ranges. ⚙ on instrument rows and
  pad detail layers. Format decoded by strike4j (github.com/cbuschka/strike4j), verified
  against all 1749 library presets; `tools/test_sin_roundtrip.py` guards losslessness.
  Edits write to the library copy only (SD presets read-only) with per-session Revert.
- Hex inspector panel ("Inspect bytes" button in pad detail; runs `hex_explorer.py`, renders inline)
- Plugin / script runner (Tools menu in header; lists `tools/*.py`, run + stream stdout)
- **Gate time selector** — pad-detail row wiring the confirmed off-53 encoding: mode dropdown
  (Free / Sync:1/32…Sync:1/2T / OFF) + ms input (0–99) for Free mode. The official editor
  guide (p.8) revealed 0–99 = Free gate length in **milliseconds**, not a bare "Free" flag.
- **Kit-level FX editor** — the read-only inspector is now a full editor (Kits menu → Kit FX
  editor…): reverb type/level/size/color, FX1/FX2 type/level/feedback/depth/rate (+delay ms
  for delay-family types), EQ LF/HF gain + freq indices, compressor preset/threshold/output.
  `set_kit_fx()` + POST `/api/kit_fx_set`; `kit_raw` now included in undo snapshots.
  Comp preset order from the official editor guide (0=Master 1, 1=Radio 1 hex-diff-anchored).
  Reverb type names still only Big Gate (2) / Close Mic (3); others render "Type N".
- **Official Strike Editor .zip import compatibility** — `import_bundle()` now classifies
  entries by path segment (`Kits/`, `Instruments/`, `Samples/`, case-insensitive, at any
  nesting depth) with fallbacks: `.skt` anywhere → kits, `.sin` → parent-folder rel,
  loose `.wav` → placed at the rel path referenced by the zip's `.sin` string tables.
  Accepts our strike-bundles, official editor exports, and commercial pack zips.
- **Trigger settings backup (SysEx)** — Tools menu modal: captures the module's 236-byte
  trigger-config dump (F0 00 00 0E …) via Web MIDI with `{sysex: true}` (no python-rtmidi
  needed — capture-first design, user presses Send on the module), save/load `.syx`,
  verbatim restore with output picker + confirmation, hex inspector with known bytes
  highlighted (byte 27 = xTalk RCV). Uses `addEventListener` so it coexists with the
  MIDI monitor's `onmidimessage`.

---

## 🔬 Offset Hunting — COMPLETE

All visible per-pad parameters in the kit editor are confirmed. No more hardware sessions needed.

**Unknown pad offsets** 9/10, 22/23, 29/30, 42/43, 47, 55, 56–60 have no corresponding
user-visible UI parameter — treated as reserved/internal. Do not write to them.

**Cycle mode (Round Robin/Random)** and **filter type (Lo/Hi Pass)** are `.sin` instrument
file properties, not `.skt` kit parameters.

**SysEx:** The module responds to a dump request with a 236-byte Alesis-proprietary trigger
config message (F0 00 00 0E …). This data covers per-input sensitivity, scan time, and MIDI
mapping — stored in module firmware, not on SD card. Decoding this further would require MIDI I/O
architecture changes and is tracked separately below.

### Trigger-dump byte map (hardware hex-diff session, 2026-07-06)

Method: capture baseline `.syx` → change ONE trigger setting on the module → re-Send → diff.
Header is `F0 00 00 0E 48 0D …`. **The payload is 7-bit SysEx MSB-packed**: any value >127 has
its 8th bit relocated into a shared packing byte, so raw byte reads are only valid for values
≤127 (which is why byte 27=xTalk=0 read correctly before).

| byte | setting | encoding | status |
|---|---|---|---|
| 22 | MSB / high-bit packing byte | carries 8th bits of nearby data bytes (bit4 = byte-25 sensitivity MSB) | ✅ |
| 25 | trigger sensitivity | **value × 2**, low 7 bits (MSB → byte 22) | ✅ |
| 26 | *(unknown)* | constant 96 in dumps seen | ❓ |
| 27 | xTalk RCV | raw value | ✅ (previously the only mapped byte) |
| 28 | *(unknown)* | constant 23 | ❓ |
| 29 | retrigger / mask time | raw value | ✅ |
| 30 | *(unknown)* | constant 0 | ❓ |
| 31 | trigger threshold | raw value | ✅ |

Bytes 25–31 look like one input's trigger block (sensitivity/xtalk/retrigger/threshold interleaved
with unknowns). Sensitivity was reported *global* on this module; per-input scope of the others
is TBD (the test module's screen is damaged, so per-input navigation was avoided). Encoding proof:
sens 30→60, 59→118, 90→180 (180 packs to byte25=52 + byte22 bit4=16). Baseline `.syx` and all
diff dumps archived under `~/Documents/strike_backups/20260706-220609/`.

---

## 🚀 Next Up

### Remaining Kit FX enumerations **[easy, hardware/screen-driven]**
The FX editor ships with gaps that need the module screen (not the official editor —
it shows reverb type as a bare number):
- Reverb type names for indices 0–21 other than 2=Big Gate, 3=Close Mic (read them off
  the module's Kit FX page dropdown in order)
- EQ LF/HF freq index tables (known anchors: LF 10=58 Hz, 11=66 Hz; HF 77=8.7 kHz,
  78=9.1 kHz; full range 20 Hz–18.5 kHz) — until then the editor exposes raw indices

### Drop clutch transform **[medium — needs one listening test]**
One-click hi-hat instrument transform for double-bass playing: duplicate a hi-hat .sin and
invert/remap its pedal-open ranges (msmp mapping bytes 10/11) so a released pedal plays
closed sounds — frees both feet for kick work. The module itself has no such feature.
Blocked only on a hardware listening test that the hh_min/hh_max semantics behave as
documented (strike4j hypothesis); the rr=-2 pedal-function mappings (chick/splash) need
careful handling in the transform.

### Velocity editor polish **[easy, feedback-driven]**
Tune the zone-lane feel after hands-on use: drag grab radius, audition loudness curve,
hi-hat pedal-position second lane, possibly per-zone sample replacement UI.

### ~~Drum map realism overhaul~~ ✅ done (2026-07-06) **[medium, art-driven]**
Made the SVG drum map look like a real kit: realistic top-down `<use>` sprites per shape
type in `DRUM_MAP_DEFS` (red-sparkle shells, dark mesh heads, chrome hoops/lugs, cymbal
lathing + sheen + bell, electronic-cymbal graphite, hi-hat pedal, drop shadows). Sprites
key off the existing shape types and scale via `translate()+scale()`, so drag, mirror
pads, relabel, zoom, and MIDI hit-flash (now a brightness pulse) all keep working. Rim is
a hoop-only overlay that scales to register on its drum; the bell is a dome centred on the
ride — both drawn last (on top) with transparent centres so clicks fall through to the
parent, and both drag together via `PAD_COMPANIONS`. All in `renderDrumMap()` + SVG defs.

### ~~Full pad editability — "mock up your exact kit"~~ ✅ done (2026-07-06) **[medium]**
Every pad is now fully editable so the map can mirror a real physical kit. `padOverrides`
gained `rot` + `finish`; sprite transform is `translate→rotate→scale` and finish is a CSS
`filter` on the `<use>` (`DRUM_FINISHES` / `CYM_FINISHES`, `finishSetFor()`). On-map gold
handles resize + rotate the selected pad (`startHandle()` + `dragState.handle`; Shift snaps
to 15°); the pad panel mirrors this with size/rotation sliders (`setPadSize`, `setPadShape`)
and a finish swatch picker. Overlays inherit their parent's rotation/finish (and rim its
size) via `editTargetOf()`. `exportLayout()` / `importLayout()` save/load the arrangement as
a JSON file (buttons by Reset layout). Possible follow-ups: per-finish real sparkle/wrap
textures (currently hue/brightness filters), and free per-axis (non-uniform) resize.

---

## 🧪 Experimental (approved backlog, 2026-07-05)

Ordered by wow-to-effort; #1 first — it makes everything else better.

1. ~~**Virtual module mode**~~ ✅ **done** — play the kit being edited from the real pads
   (or number keys 1–0): `GET /api/kit_playback` manifest → Web Audio engine honoring
   velocity zones, round-robin/random cycling, Layer A/B xfade, per-layer level+pan,
   semitone+fine pitch, mute-group choke, and Mono/Poly. Decay is approximated (gain
   envelope) and vel→loudness uses a fixed curve; module FX and the vel→filter/pitch/decay
   response curves are **not** simulated (documented in README + the button tooltip).
   Verified without hardware via `tools/test_playback_manifest.py` and synthetic
   browser hits (OfflineAudioContext renders). Kills the edit → SD → reload loop entirely.
2. ~~**"More like this" similarity search**~~ ✅ **done** — one-time audio fingerprints
   for all library instruments; click the **≈** on any instrument (or a pad layer) →
   the N closest-*sounding* alternatives, ranked, cross-group. Fixes browsing 168 snares.
   Feature vector (5, all stdlib, sample-rate-aware): spectral **centroid** (Hz), 85%
   spectral **rolloff** (Hz), **zero-crossing rate** (no-FFT brightness proxy), **brightness**
   (energy fraction >2 kHz), and RMS-envelope **decay time** (s). Spectral features come from
   a hand-rolled radix-2 FFT over a Hann-windowed frame at the attack (no numpy). Each
   instrument is fingerprinted from its **hardest-velocity ("full hit") sample** — the
   mapping with the highest vmax, which dedupes round-robins to one file. Vectors are cached
   in `library/fingerprints.json` (keyed by sin_rel, invalidated by the WAV's mtime+size and
   a schema version); missing/broken WAVs are skipped, not fatal. **The read-only factory
   content (byte-identical on every module) ships pre-fingerprinted** as a committed base
   layer `factory_fingerprints.json` (~470 KB — derived numbers, not audio), regenerated by
   `tools/build_factory_fingerprints.py` when FP_SCHEMA changes; factory entries validate on
   size only (WAV mtimes differ between cards) so similarity works with zero sample sync and
   no first-run batch, and the user sidecar layers custom samples on top. Batch build runs in a
   background thread with a progress bar (mirrors the SD-sync plumbing); single clicks
   fingerprint lazily so the feature works before the batch finishes. k-NN is brute-force
   euclidean over **z-scored** features (so no Hz-scaled feature dominates a 0–1 one) — no
   SIN-group hard filter, so a bright crash surfaces bright long-decay cymbals from any
   folder. Read-only: no WAV/`.sin`/`.skt` is ever modified. Routes: `GET /api/similar`,
   `GET /api/fingerprint_status`, `POST /api/fingerprint_build`. Test: `tools/test_fingerprint.py`.
3. **Local kit designer** (was "Natural-language kit builder") **[medium]** — auto-assemble a
   kit from a *vibe*, but **no LLM** (the ethos filter demotes API/accounts/cost). The LLM was
   only ever the fuzzy front-end; the real engine is the deterministic fingerprint + tag search
   from #2. So: adjective chips / facet sliders (bright↔dark from spectral centroid, tight↔boomy
   from decay), tag filters, and "fill this pad with something like *X*" via similarity → real
   files picked from `avail` only (no hallucination). ~70% of the wow, zero setup, and the
   slider/chip UI is touch-friendly (feeds Mobile). Needs an adjective→feature-range map
   ("bright"→high centroid, "tight/dry"→short decay, "boomy"→low centroid + long decay). Scope v1
   to layer-A assignment; params/FX later. Natural-language *text* stays an **optional** thin
   layer someone could bolt on with their own key — never required.
4. **Kit-from-loop** **[hard]** — drop a drum loop WAV → onset-detect, slice, auto-build
   .sin per hit (quiet/loud variants become velocity layers), assign to pads.
5. **Loupedeck CT integration** **[easy]** — dials → selected pad's level/pitch/decay/
   cutoff via existing `/api/set_param`; both ends already exist.
6. **Practice telemetry** **[medium]** — log MIDI hits vs. live-loop metronome: timing
   accuracy, velocity consistency, per-pad heatmaps, session stats.
7. **Sample lab** **[medium]** — in-browser WAV mangling pre-import (pitch, reverse,
   layer-blend, transient shaping via OfflineAudioContext) → render → .sin.
8. ~~**Kit time machine**~~ ✅ **done** — persistent, navigable version history that
   outlives reloads (the durable counterpart to the in-memory 20-step undo). Full-`.skt`
   snapshots are stored server-side in `library/snapshots/` keyed by kit (bytes are KB,
   not samples; they round-trip byte-identical through `parse_skt`/`build_skt`). Auto-snap
   on **Load** and **Save**, a debounced auto-snap during editing (20 s idle), and a manual
   **Snapshot now** button; identical consecutive states are deduped by SHA-256 and
   retention caps 50 non-pinned per kit / 30 days (pin to keep forever). Timeline modal
   (Kits menu → **Kit time machine…**) lists snapshots newest→oldest with a scrubber; the
   diff engine (`_diff_pad_lists`) now diffs **any two** snapshots (or vs. current), and
   **Restore** loads a chosen snapshot back as a normal, undoable mutation. Routes:
   `GET /api/snapshots`, `POST /api/snapshot|snapshot_diff|snapshot_restore|snapshot_delete|snapshot_pin`.
   Verified by `tools/test_time_machine.py`.
9. **Community kit registry** **[low — DEMOTED by the no-hosting/no-accounts ethos]** — a static
   index of shared bundles with in-app browse/install was the idea, but it needs sample hosting
   + curation (bundles carry WAVs) and is chicken-and-egg (useless empty). Shrink to at most a
   "share/import a bundle link" (the bundle export/import already exists); a real registry only if
   a community materialises.

---

## 🎛️ Pad & Assignment

- ~~**Swap pads**~~ ✅ done
- ~~**Batch assign from CSV**~~ ✅ done
- ~~**Batch parameter apply**~~ ✅ done

---

## 🔊 Audio & Preview

- ~~**Waveform thumbnail**~~ ✅ done (lazy IntersectionObserver, `/api/waveform`)
- ~~**Visual velocity curve**~~ ✅ done at instrument level (response-curve panel with
  drag-to-set depth + velocity-zone lane in the .sin editor; kit-layer vel→* now also
  confirmed at off 15–18/35–38 and exposed as sliders). Zone create/delete done too: split/+RR/✕ per
  mapping row via msmp rebuild with cloned unknown bytes (`rebuild_sin_zones`)
- ~~**Velocity preview slider**~~ ✅ done
- ~~**Layer blend preview**~~ ✅ done (▶ A+B button in pad detail when both layers assigned)
- ~~**Sample normalization on import**~~ ✅ done (server-side; checkbox in WAV import form)
- ~~**Auto-map by loudness**~~ ✅ done (checkbox in WAV import form; `wav_peak()` measures
  each file, sorts quiet→loud, `_vel_bands` assigns ranges — mirrors official Auto-Map)

---

## 📂 Instrument Browser

- ~~**Search by tags**~~ ✅ done
- ~~**Broken path detection**~~ ✅ done

---

## 🗂️ Kit Management

- ~~**Kit compare / diff**~~ ✅ done
- ~~**Kit time machine**~~ ✅ done (persistent snapshots + timeline + any-two diff + restore)
- ~~**Kit size meter**~~ ✅ done

---

## 📤 Import / Export

- ~~**Export MIDI map PDF**~~ ✅ done
- ~~**Batch kit export**~~ ✅ done

---

## 🖥️ UI / UX

- ~~**Zoom on drum map**~~ ✅ done
- **Mobile-friendly layout** → **promoted to top priority; see § 📱 Mobile / iPad-first above.**

---

## 🔧 Developer / Power User

- ~~**Hex inspector panel**~~ ✅ done
- ~~**Plugin / script runner**~~ ✅ done

---

## 📦 Packaging & Distribution

> ⚠️ **Largely mooted by the pure-web pivot** (see § 🏛️ Architectural direction). If the app
> becomes a single self-contained `.html`, there's nothing to package or sign — you host/ship one
> file. Keep the PyInstaller notes below only as the fallback if the Python app is kept for desktop
> instead of ported.

Turn the "bunch of scripts" into a one-click app. The stdlib-only discipline makes the
**core bundling easy** (no third-party deps → no hidden-import hell, no native wheels,
small bundle). Do the prep as **one clean commit on `main` AFTER the feature branches
merge** — not a 5th branch (it touches path handling that every branch would conflict on).

**1. Frozen-path split [medium — the prerequisite, do first].** When PyInstaller freezes
the app, `__file__` points into a read-only temp dir (`sys._MEIPASS`) that's wiped on exit.
Split read-only resources from writable user data:
- Add a `_res(name)` helper: `sys._MEIPASS if getattr(sys,'frozen',False) else Path(__file__).parent`.
- `factory_fingerprints.json` → read-only, bundle it (`--add-data`), resolve via `_res()`.
- `library/` (kits, tags.json, user `fingerprints.json`, snapshots) → **writable**, must live
  next to the exe or in a per-user dir (`%APPDATA%\StrikeRemapper`, `~/Library/Application
  Support/…`), **never** in `_MEIPASS`. The 2-layer fingerprint store already fits this:
  baked layer bundles, user sidecar goes to user-data.
- Worth doing even un-frozen (more robust path handling).

**2. Subprocess-to-Python features [medium].** The hex inspector, plugin/script runner, and
template runner spawn `sys.executable` on loose `tools/*.py`. Frozen, `sys.executable` is the
exe (not python) and `tools/` isn't bundled → they break. Fix: refactor the ones that matter
(`hex_explorer`, `make_metal_kit`) into importable in-process functions, or gate the Tools-menu
runner off when `frozen`.

**3. Build & ship [easy-ish].** `pyinstaller --onedir --add-data "factory_fingerprints.json;."
strike_remap.py` (prefer `--onedir` over `--onefile` — starts faster and trips AV
false-positives far less). PyInstaller can't cross-compile: build the `.exe` on Windows and the
`.app` on macOS separately. Auto-open-browser + port handling already exist.

**4. Distribution — unsigned is fine, ship on GitHub [decision: source-first].** Code-signing
is **optional**; it only removes an OS friction warning, it does not gate distribution.
- **Primary:** ship source + `python strike_remap.py` (zero-friction for anyone with Python;
  no signing, works everywhere). MIT-license it.
- **Convenience:** unsigned binaries as GitHub Release assets + a one-line "if your OS warns
  you, here's the bypass" note. Windows → SmartScreen "unknown publisher" (More info → Run
  anyway); macOS → Gatekeeper (Settings → Privacy & Security → Open Anyway).
- **Signing/notarization** (Windows cert; Apple Developer ID + notarization, $99/yr) →
  revisit ONLY if it gets popular enough that the macOS friction is a real barrier. Not now.

---

## 🚫 Out of Scope (for now)

- **Real-time module parameter sync** — requires SysEx reverse engineering via USB traffic
  capture; write-to-SD + kit reload on module is the pragmatic workaround
- **Trigger sensitivity / xTalk / scan time editing** — backup/restore + hex inspector now
  ship via Web MIDI (see Done), which removed the python-rtmidi blocker. *Editing individual
  values* is still out: it needs the remaining ~200 bytes of the 236-byte dump mapped
  (hex-diff method: change one setting on the module → Send → compare captures — the new
  modal makes this easy) and confirmation the module accepts a modified dump.
- **SysEx type/preset full enumeration** — Reverb type list, FX type list, LF/HF freq tables,
  comp preset list all need to be read from the official editor UI. Low effort but not
  blocking anything until kit-level FX UI is built.
