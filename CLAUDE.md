# Strike Pro Remapper — Project Brief

Single-file Python web app (`strike_remap.py`) for editing Alesis Strike Pro drum kit files
(`.skt`). Runs an HTTP server on port 8765; all HTML/CSS/JS is embedded as `HTML = r"""..."""`.

**README.md is user-facing and must stay current**: whenever a feature ships, a format
discovery lands, or the verification status of an offset changes, update README.md in the
same commit (Features list, Format status table, or Credits as appropriate).

## Quick start

```powershell
# Windows
python strike_remap.py        # opens browser at http://localhost:8765
# After any code change, restart. Do NOT kill all python.exe blindly — other python
# processes (e.g. Windows-MCP) may be running; match on command line:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object CommandLine -match 'strike_remap' |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Process python strike_remap.py
```

```bash
# macOS
python3 strike_remap.py &
# After any code change, restart:
pkill -f strike_remap.py && python3 strike_remap.py &
```

## Architecture

| Layer | Where |
|---|---|
| Binary parser/writer | `parse_skt()`, `build_skt()` — top of file |
| Mutable server state | `state` dict (kit_path, pads, instruments, avail, dirty, history) |
| HTTP handlers | `Handler.do_GET` / `do_POST` — all `/api/*` routes |
| Frontend | Embedded string `HTML`; pure JS, no framework |

**All mutations follow this pattern:**
1. Call a pure Python function (`assign_instrument`, `clear_all_pads`, etc.) that edits `state`
2. Handler returns `{pads: _pad_view(...), dirty, undo_count, history_labels, message}`
3. JS updates `pads` array then calls `renderDrumMap()` + `renderPadDetail()`

## Layout (3-column grid, responsive)

```
┌──────────────────── header (56px) ────────────────────────────┐
│ Strike Pro Remapper | [Kits▾] [Save▾] [Dup] [Clear] ... [⚠SD]│
├───────────────────────────────────────────────────────────────┤
│ Left (280px)       │ Center (1fr)      │ Right (360px)         │
│ Back panel jacks   │ Drum map SVG      │ Tag chips + search    │
│   (collapsible)    ├───────────────────│ Instrument browser    │
│ Pad detail panel   │ Live loop         │                       │
│   (fills rest)     │   (below drums)   │                       │
└────────────────────┴───────────────────┴───────────────────────┘
```

CSS: `.main { display: grid; grid-template-columns: 280px 1fr 360px; height: calc(100vh - 56px); }`
**Critical:** all three direct children need both `grid-column: N` AND `grid-row: 1` — without
`grid-row: 1`, explicit `grid-column` triggers auto-placement into separate rows.

At ≤768px the columns stack vertically: center (drum map) → left (pad editor) → right (browser).

**JS gotcha:** `togglePopover` is a native browser method on `HTMLElement` — the custom
popover toggler is named `menuToggle(id)` to avoid the conflict.

**Visual system (June 2026 overhaul):** graphite surfaces + brass-gold accent; tokens in
`:root` at the top of `<style>`. Selection = CSS drop-shadow glow on the pad `<g>`. Pad
layout overrides live in `padOverrides` (localStorage), including `mirror: {dx, dy}` which
draws a zone twice (Y-splitter support) — both copies share the zone; mirror drags
independently (`startDrag(e, id, isMirror)`).

**Drum map sprites (July 2026 realism port):** `DRUM_MAP_DEFS` holds 11 reusable `<use>`
sprites (`lug`, `drumcore`, `s-snare/-tom/-floor/-rim/-kick/-cymbal/-cym-e/-bell/-hfoot`),
each modelled at native radius ~100 centred on 0,0 (red-sparkle shells, mesh heads, chrome
hoops/lugs, cymbal lathing+sheen+bell, graphite e-cymbal, hi-hat pedal). `renderDrumMap()`
places one per pad via `<use href="#s-{type}" transform="translate(cx,cy) scale(rx/100,ry/100)">`
(hfoot uses a uniform `rx/56` scale). Rim/bell are **overlays**: pushed to a separate
`overlays[]` array rendered last so they sit on top with transparent centres → clicks fall
through to the parent. `drumParentOf(id)` (first companion of a base type) makes a rim scale
to its drum's hoop and a bell centre on its ride; both still drag together via
`PAD_COMPANIONS`. MIDI hit-flash (`.map-pad.midi-hit`) is a brightness pulse (the old
`ellipse` stroke rule couldn't reach `<use>` shadow content). `PAD_COLORS` is now unused by
the map but kept for reference.

**Full pad editability ("mock up your exact kit", July 2026):** `padOverrides[id]` now also
carries `rot` (degrees) and `finish` (key). Sprite transform is
`translate(cx,cy) rotate(rot) scale(rx/100,ry/100)`; finish is a CSS `filter` on the `<use>`
from `DRUM_FINISHES` / `CYM_FINISHES` (`finishSetFor(type)` picks the set; hue-rotate works
because chrome/mesh are desaturated). Overlays read `rot`/`finish` (and rim also rx/ry) from
their base pad, so a drum + rim / ride + bell stay one piece. `editTargetOf(id)` redirects an
overlay's edits to its parent. On-map gold handles (`.pad-handle`, rendered last, outside
`.map-pad`) drive resize/rotate via `startHandle()` + a `dragState.handle` branch in
`svgMouseMove`/`svgMouseUp` (Shift snaps rotation to 15°). Panel mirrors them:
`setPadSize(id, scale)` (scale × the type's `PAD_TYPE_SIZES` default) and
`setPadShape(id, key, val, redrawPanel)` (redrawPanel=false so a slider isn't torn out
mid-drag). `exportLayout()` / `importLayout(file)` save/load `padOverrides` as JSON
(`format: 'strike-remap-layout'`; import filters to `VALID_PAD_IDS`, tolerates a bare
overrides object) — buttons live next to Reset layout.

**Script block placement:** `<script>` is at ~line 42k in the HTML string; DOM elements defined
AFTER the script cannot be referenced during script evaluation — use inline `onclick=` not
`addEventListener` for elements placed after the script.

## Key payload offsets (relative to `inst` block payload)

```
LAYER_A_IDX_OFF = 4    # uint16 LE — instrument index (0xFFFF = none)
LA_LEVEL_OFF    = 6    # uint8  — level 0-127
LA_PAN_OFF      = 7    # int8   — pan -50 to +50  ✅ CONFIRMED (hard-left → 0xce = -50)
LA_DECAY_OFF    = 8    # uint8  — Decay 0-99  ✅ CONFIRMED (screenshot: K1H Decay=99=payload[8])
# off 9–10       — unknown
LA_PITCH_OFF    = 11   # int8   — pitch semitones -12 to +12  ✅ CONFIRMED via hex diff
LA_FINE_OFF     = 12   # int8   — fine pitch -50 to +50 cents  ✅ CONFIRMED via hex diff
LA_FCUT_OFF     = 13   # uint8  — Filter Cutoff 0-99  ✅ CONFIRMED via hex diff
LA_FFLAG_OFF    = 14   # uint8  — Filter Enable flag 0/1  ✅ CONFIRMED via hex diff
LA_VEL_DEC_OFF  = 15   # uint8  — Velocity→Decay 0-127   ✅ CONFIRMED via hex diff
LA_VEL_PCH_OFF  = 16   # uint8  — Velocity→Pitch 0-127   ✅ CONFIRMED via hex diff
LA_VEL_FLT_OFF  = 17   # uint8  — Velocity→Filter 0-127  ✅ CONFIRMED via hex diff
LA_VEL_VOL_OFF  = 18   # uint8  — Velocity→Volume 0-127  ✅ CONFIRMED (screenshot + hex diff)
# off 19–20      — unknown (off 20 = 127 in all kits seen)
LA_LOOP_OFF     = 21   # uint8  — Loop mode 0=Off, 1=On  ✅ CONFIRMED via hex diff
# off 22–23      — unknown
LA_VEL_MIN_OFF  = 19   # uint8  — Layer A vel range min 0-127  ✅ CONFIRMED (mirrors LB off 39=XFADE_VEL)
LA_VEL_MAX_OFF  = 20   # uint8  — Layer A vel range max 0-127  ✅ CONFIRMED (mirrors LB off 40=always 127)
LAYER_B_IDX_OFF = 24   # uint16 LE
LB_LEVEL_OFF    = 26   # uint8
LB_PAN_OFF      = 27   # int8   ✅ CONFIRMED (mirrors off 7)
LB_DECAY_OFF    = 28   # uint8  — Decay 0-99  ✅ CONFIRMED (mirrors off 8)
# off 29–30      — unknown
LB_PITCH_OFF    = 31   # int8   ✅ CONFIRMED (mirrors off 11)
LB_FINE_OFF     = 32   # int8   — fine pitch -50 to +50 cents  ✅ CONFIRMED (mirrors off 12)
LB_FCUT_OFF     = 33   # uint8  ✅ CONFIRMED (mirrors off 13)
LB_FFLAG_OFF    = 34   # uint8  ✅ CONFIRMED (mirrors off 14)
LB_VEL_DEC_OFF  = 35   # uint8  — Velocity→Decay  ✅ CONFIRMED by +20 symmetry from LA
LB_VEL_PCH_OFF  = 36   # uint8  — Velocity→Pitch  ✅ CONFIRMED by symmetry
LB_VEL_FLT_OFF  = 37   # uint8  — Velocity→Filter ✅ CONFIRMED by symmetry
LB_VEL_VOL_OFF  = 38   # uint8  — Velocity→Volume ✅ CONFIRMED (screenshot cross-ref)
XFADE_VEL_OFF   = 39   # uint8  — Layer B vel minimum / xfade threshold ✅ CONFIRMED via hex diff
# off 40          — Layer B vel max (always 127 in all kits seen)
LB_LOOP_OFF     = 41   # uint8  — Loop mode 0=Off, 1=On  ✅ CONFIRMED (mirrors off 21)
# off 42–43       — unknown
REVERB_OFF      = 44   # uint8  — FX Reverb send 0-99  ✅ CONFIRMED (was mistakenly XFADE_VEL_OFF)
FX1_OFF         = 45   # uint8  — FX1 send 0-99        ✅ CONFIRMED via hex diff
EQ_COMP_OFF     = 46   # uint8  — EQ/Comp enable 0/1   ✅ CONFIRMED via hex diff
# off 47          — unknown
PRIORITY_OFF    = 48   # uint8  — Priority 0=Low,1=Med,2=High  ✅ CONFIRMED via hex diff
MUTE_GRP_OFF    = 49   # uint8  — mute/choke group 0=off,1-9=groups  ✅ CONFIRMED via hex diff
NOTE_OFF_OFF    = 50   # uint8  — Note Off: 0=Sent,1=None,2=Alt  ✅ CONFIRMED via hex diff
MIDI_CHAN_OFF   = 51   # uint8  — MIDI channel 0-indexed (0=ch1…15=ch16)  ✅ CONFIRMED
MIDI_NOTE_OFF   = 52   # uint8  — GM MIDI note (0-127)  ✅ CONFIRMED
GATE_TIME_OFF   = 53   # uint8  — Gate time  ✅ FULL LUT CONFIRMED via hex diff:
                       #   0–99 = Free gate length in ms (per official editor guide p.8),
                       #   100=Sync:32, 101=Sync:32T, 102=Sync:16, 103=Sync:16T,
                       #   104=Sync:8, 105=Sync:8T, 106=Sync:4, 107=Sync:4T,
                       #   108=Sync:2, 109=Sync:2T, 255=OFF
PLAY_MODE_OFF   = 54   # uint8  — Playback mode: 0=Mono, 1=Poly  ✅ CONFIRMED via hex diff
# off 55          — unknown; NOT cycle mode (cycle mode is a .sin property, not .skt)
# off 56–60       — unknown 5-byte block (all 0xFF in every kit seen; no visible UI param maps here)
FX2_OFF         = 61   # uint8  — FX2 send 0-99  ✅ CONFIRMED via hex diff
NO_INSTRUMENT   = 0xFFFF
```

**Do NOT write to uncertain offsets** — hex_explorer.py marks unknowns. Wrong writes corrupt
kit files silently.

**All visible per-pad parameters in the kit editor are now confirmed.** Unknown offsets 9/10,
22/23, 29/30, 42/43, 47, 55, 56–60 do not correspond to any user-visible UI parameter —
treat as reserved/internal. Do not write to them.

## Kit-level FX layout (in `kit_raw`, offsets within the 52-byte header block)

Each FX block is 12 bytes; Reverb block is 4 bytes. All confirmed via hex diff.
**Editable** via `set_kit_fx(param, value)` / `_KIT_FX_PARAM_MAP` + POST `/api/kit_fx_set`;
UI is the Kit FX editor modal (Kits menu). `kit_raw` is included in undo snapshots.
Comp presets: `SKT_COMP_PRESETS` (order from official editor guide; 0=Master 1, 1=Radio 1
hex-diff-anchored). Reverb type names: `SKT_REVERB_TYPES` (only 2=Big Gate, 3=Close Mic).

```
# --- Reverb (4 bytes) ---
kit_raw[16] = Reverb type index (2=BigGate; other values TBD)
kit_raw[17] = Reverb Size 0–99    ✅ CONFIRMED
kit_raw[18] = Reverb Color 0–99   ✅ CONFIRMED (value 50 matches screenshot)
kit_raw[19] = Reverb Level 0–99   ✅ CONFIRMED

# --- FX1 block (12 bytes, [20–31]) ---
kit_raw[20] = FX1 type index (0=Mono Flanger; others TBD)
kit_raw[21] = FX1 Level 0–99      ✅ CONFIRMED
# kit_raw[22–25] = unknown (4 bytes, always 0 in test kit)
kit_raw[26] = FX1 Feedback 0–99   ✅ CONFIRMED
# kit_raw[27] = unknown (1 byte, always 0)
kit_raw[28] = FX1 Depth 0–99      ✅ CONFIRMED
kit_raw[29] = FX1 Rate 0–99       ✅ CONFIRMED
# kit_raw[30–31] = unknown (2 bytes, always 0)

# --- FX2 block (12 bytes, [32–43]) ---
kit_raw[32] = FX2 type index (0=Mono Flanger; others TBD)
kit_raw[33] = FX2 Level 0–99      ✅ CONFIRMED
# kit_raw[34–37] = unknown (4 bytes, always 0)
kit_raw[38] = FX2 Feedback 0–99   ✅ CONFIRMED
# kit_raw[39] = unknown (1 byte, always 0)
kit_raw[40] = FX2 Depth 0–99      ✅ CONFIRMED
kit_raw[41] = FX2 Rate 0–99       ✅ CONFIRMED
# kit_raw[42–43] = unknown (2 bytes, always 0)

# --- EQ / Compressor (8 bytes, [44–51]) ---
kit_raw[44] = Compressor preset index (0=Master 1, 1=Radio 1, …)  ✅ CONFIRMED
kit_raw[45] = Comp Threshold dB (int8, e.g. 0xF1=−15)             ✅ CONFIRMED
kit_raw[46] = HF Gain dB                                           ✅ CONFIRMED
kit_raw[47] = LF Gain dB                                           ✅ CONFIRMED
kit_raw[48] = LF Freq index (10=58Hz, 11=66Hz; sequential)        ✅ CONFIRMED
kit_raw[49] = Comp Output dB                                       ✅ CONFIRMED
kit_raw[50] = HF Freq index (77=8.7kHz, 78=9.1kHz; sequential)   ✅ CONFIRMED
# kit_raw[51] = 0x00 (unknown; possibly padding or EQ enable flag)

# Type index known values (more can be inferred from UI dropdown order):
# Reverb types: 2=BigGate, 3=CloseMic
# FX types:     0=Mono Flanger, 1=Stereo Flanger, 3=Mono Chorus 1
```

**Complementary statistical notes (June 2026, 133-kit scan — consistent with the above):**
- kit_raw[22:24] (their "unknown, always 0 in test kit") looks like a **u16 LE delay-time
  in ms** for delay-family FX types: 140 ms in Tonight's Air (slapback), 800 ms in
  Jungle Jam (delay). FX2 mirror at kit_raw[34:36].
- Full FX type enum is likely the manuals' effects table order, 0-based with no Off entry
  (matches 0=Mono Flanger, 1=Stereo Flanger, 3=Mono Chorus 1): 0 MonoFlanger,
  1 StereoFlanger, 2 XoverFlanger, 3 MonoChorus1, 4 MonoChorus2, 5 StereoChorus,
  6 XOverChorus, 7 MonoVibrato, 8 Vibrato, 9 MonoDoubler, 10 Doubler, 11 MonoSlapback,
  12 Slapback, 13 MonoDelay, 14 Delay, 15 XOverDelay, 16 PingPong; 0xFF observed = off.
- Reverb type byte ranges 0–21 across presets (22 reverb types).

**Round-trip is verified lossless.** `tools/test_roundtrip.py` confirms `parse_skt()` →
`build_skt()` reproduces byte-for-byte identical output. Run any time a new offset write is added.

## .sin instrument format (INST block decoded)

Layout from the strike4j project (github.com/cbuschka/strike4j), verified against all 1749
library .sin files with zero exceptions. Chunks: `INST` (24-byte params) → `msmp` (sample
mappings) → `str ` (zero-terminated WAV paths).

```
INST payload:  [1] group (0-19, see SIN_GROUPS)   [6] level      [7] pan (int8)
               [8] decay        [11] semi (int8)  [12] fine (int8)
               [13] cutoff      [14] hipass flag  [15-18] vel→decay/pitch/filter/level (int8)
               [21] loop flag   (other bytes constant: 0 except [2]=1, [20]=0x7f)
msmp payload:  [0] cycle (0=round-robin 1=random)  [2] mapping count, then 28-byte mappings:
               [0:2] str index (u16)  [3] vel min  [4] vel max  [7] rr index
               (signed: 0xFE = hi-hat pedal function)  [10] hh-open min  [11] hh-open max
```

Python API: `parse_sin(data)`, `patch_sin(data, params, cycle_random, mappings)` — patcher
writes only known offsets, preserving every unknown byte. `tools/test_sin_roundtrip.py`
verifies no-op + identity patches are byte-identical across the whole library.

Relink: `relink_suggestions()/relink_apply()` + `/api/relink_suggest|relink_apply` —
rewrites strings in `state['instruments']` (the kit str table), one undo entry.
Bundles: `export_bundle()/import_bundle()` + GET `/api/export_bundle`, POST
`/api/import_bundle` (base64 zip) — zip mirrors library layout (kit/, instruments/<rel>,
samples/<wav_rel>) so no path rewriting; import never overwrites existing files.

Editing: `sin_detail()/sin_update()/sin_revert()` + `/api/sin_detail|sin_update|sin_revert`.
Edits always target the library copy (`_sin_abs` prefers `library/instruments/` because a
mounted SD card shadows identical rel paths in `state['avail']`); SD presets are read-only.
First edit per session backs up original bytes in `state['sin_backups']` for Revert.
UI: ⚙ button on instrument rows + pad detail layers → `openSinEditor()` modal (`sin-modal`).
Velocity visuals inside the modal: `renderZoneLane()` (drag split points — moves every
edge sharing the boundary incl. RR band mates and abutting zones; click = audition via
`/api/wav?sin=&idx=N`, per-mapping WAV by `find_wav_for_sin_idx`) and `renderVelCurve()`
(depth visualization for vel→* params; drag = set depth; tabs via `setCurveParam`).
Zone create/delete: `rebuild_sin_zones()` + POST `/api/sin_zones` — rebuilds msmp/str;
each output zone clones the 28-byte block of an original mapping (`src` index) so unknown
bytes always come from a real sibling; str table keeps original order, new samples append;
file re-padded to 4 bytes. Verified semantically lossless across all 1749 instruments.
UI: ✂ split / +RR / ✕ buttons per mapping row (sends pending param edits in the same call).

## Important Python functions

- `_push_history(label)` — snapshot state before any mutation (max 20 steps)
- `_history_labels()` — returns newest-first list of action labels for the undo panel
- `_pad_view(pads, instruments)` — serializes pad state to JSON for the frontend
- `refresh_available()` — rescans SD + library for `.sin` files into `state['avail']`
- `build_skt(kit_raw, pads, instruments, tail)` — reassembles binary from state
- `set_pad_param(pad_id, param, value, coalesce=False)` — updates a single pad parameter;
  handles `mute_grp`, `midi_chan`, and `gate_time` specially (outside `_PARAM_MAP`), all
  others via `_PARAM_MAP = {name: (offset, fmt, lo, hi)}`; bumps `state['param_rev']`;
  `coalesce=True` skips the history push when the last undo entry is the same pad+param
  (dial/encoder streams → one undo step per twist)
- `selected_view()` — external-controller view: `state['sel_pad']` + la_level/la_pitch/
  la_decay/la_fcut + `rev`. Routes: GET `/api/selected`, POST `/api/select` {pad_id}.
  Browser mirrors selection via `postSelect()` (hooked in `updateAssignBanner()`) and polls
  `/api/selected` every 1.5 s to pick up dial edits (Loupedeck StrikeDials in the
  loupedeck-homelab repo consumes this)
- `kit_playback_manifest()` — GET `/api/kit_playback`. One manifest for the loaded kit
  feeding the browser **Virtual module** engine: per pad `{id,label,midi_note,mute_grp,
  play_mode,layers}`; each assigned layer `{sin_rel, skt:{level,pan,pitch,fine,decay,
  vel_min,vel_max}, sin:{level,pan,semi,fine,decay,loop}, cycle_random, mappings:[{idx,
  vmin,vmax,rr,hh_min,hh_max,wav_url,size}]}` + top-level `rev`/`kit`/`total_bytes`.
  Reuses `_pad_view()` offset constants + `parse_sin`/`find_wav_for_sin_idx` (mapping index
  i == `/api/wav` idx). Layer B `vel_min` = `xfade_vel`, `vel_max` = 127. Broken WAV →
  `wav_url: null`; per-instrument parse failure → `layer.error` (rest still builds).
  `_push_history()` now bumps `param_rev` (was set_pad_param-only) so assignment edits also
  invalidate the manifest for pollers. Tests: `tools/test_playback_manifest.py`.
- `set_kit_fx(param, value)` — writes one kit-level FX param into `kit_raw` via `_KIT_FX_PARAM_MAP`
- `normalize_wav(wav_data)` → `(bytes, peak_db_str)` — peak-normalize 16/24-bit PCM WAV
- `batch_assign_csv(assignments)` — assign multiple pads from `[{pad_id, layer, sin_rel}]`
- `swap_pads(pad_id_a, pad_id_b)` — swap full payloads between two pads
- `batch_set_param(pad_ids, param, value)` — apply one param to many pads (single undo entry)
- `diff_kit(path)` — compare another .skt against current state, returns per-pad diff.
  The comparison core is now `_diff_pad_lists(a_pads, a_insts, b_pads, b_insts)` (+
  `_diff_pad_info` / `_DIFF_KEYS`), so the same engine backs kit-vs-kit and
  snapshot-vs-snapshot diffs. Output keeps the `{diff:[{id, changed:{key:{current,other}}}
  | {id, only_in:'current'|'other'}]}` shape (renderers now guard `only_in`).
- **Kit time machine** (persistent snapshots) — `SNAP_DIR = library/snapshots/` holds one
  `<id>.skt` per snapshot (full kit bytes, round-tripped through `parse_skt`/`build_skt`,
  never touches uncertain offsets) plus `index.json` metadata; grouped by `_kit_key()`
  (kit filename, else `state['kit_display']`, else `untitled`).
  - `create_snapshot(label, kind, pinned)` — dedupes on SHA-256 vs. the kit's latest
    snapshot, applies retention, returns the entry (or `{deduped:True}`). `_auto_snapshot()`
    is the never-raises wrapper called from `load_kit`/`load_kit_bytes`/`create_new_kit`
    (kind `load`) and `save_kit` (kind `save`); the browser fires a debounced kind `auto`.
  - `_prune_snapshots(idx)` — retention: `SNAP_MAX_PER_KIT` (50) non-pinned per kit +
    `SNAP_MAX_AGE_DAYS` (30); pinned snapshots are exempt and their files deleted on prune.
  - `list_snapshots(all_kits=)`, `diff_snapshots(a, b)` (ids or `'current'`),
    `restore_snapshot(id)` (an **undoable** `_push_history` mutation — does not clobber),
    `delete_snapshot(id)`, `set_snapshot_pin(id, pinned)`. `_SNAP_LOCK` guards index writes.
  - Routes: `GET /api/snapshots` (`?all=1`), `POST /api/snapshot|snapshot_diff|
    snapshot_restore|snapshot_delete|snapshot_pin`. Test: `tools/test_time_machine.py`.
- `check_paths()` — return sin_rel paths in current kit not found in avail
- `load_tags()` / `save_tags()` / `set_instrument_tags()` — `library/tags.json` sidecar
- **"More like this" similarity search** (audio fingerprints; READ-ONLY, never writes any
  WAV/.sin/.skt). Feature vector `FP_FEATURES` = 5 stdlib, sample-rate-aware features:
  `centroid` (Hz), `rolloff` (85%-energy, Hz), `zcr` (crossings/s, no-FFT brightness proxy),
  `brightness` (energy fraction >2 kHz), `decay` (s for RMS envelope to fall 20 dB).
  - `_fft(re, im)` — hand-rolled in-place iterative radix-2 FFT (no numpy; stdlib-only rule).
    `_read_wav_mono(path, secs)` reads ≤~1.5 s of a 16/24-bit PCM WAV → mono floats + rate.
  - `extract_fingerprint(wav_path)` → feats dict | None. Spectral features come from one
    Hann-windowed `_FP_FFT_SIZE`(4096)-pt FFT at the loudest sample; `_decay_time()` from a
    10 ms-block RMS envelope.
  - `_representative_wav_for_sin(sin_rel)` → picks the **hardest-velocity ("full hit")**
    sample: the mapping with the highest `vmax` (dedupes round-robins), falling back to the
    first listed WAV; resolves via `_find_wav_in_roots`.
  - **Two layers.** Read-only **factory base** `factory_fingerprints.json` (`FACTORY_FP_PATH`,
    committed at repo root — the factory content is byte-identical on every module, so its
    ~1,748 vectors ship with the app; ~470 KB of derived numbers, not audio, so no copyright
    issue). Writable **user sidecar** `library/fingerprints.json` (`FP_PATH`) for custom/new
    samples. `_fp_lookup()` = user wins over factory; `_fp_all_items()` = merged union (user
    overrides). `load_factory_fingerprints()`/`_fp_factory` (never saved);
    `load_fingerprints()`/`save_fingerprints()` (atomic tmp-rename)/`_fp_cache`/`_fp_lock`
    (user only). Entry `{v: FP_SCHEMA, wav_rel, size, feats[, mtime][, factory:true]}`.
  - `_fp_entry_valid()` — user entries invalidate on WAV **mtime+size**; **factory** entries on
    **size only** (their WAV mtimes differ between cards/copies, so an mtime check would discard
    the whole baked set) and are trusted when the WAV is absent — that's what lets similarity
    work with the samples unsynced. `_compute_fp_entry()`, `ensure_fingerprint(sin_rel, force=)`
    (lazy per-instrument compute so a click works before the batch finishes; new entries land in
    the user sidecar; `feats=None` marks a missing/broken WAV — skipped, not fatal).
  - `tools/build_factory_fingerprints.py` regenerates the baked file (needs the factory
    library mounted; incremental by size, `--force` to recompute) — rerun when FP_SCHEMA or
    the feature vector changes. Excluded from the in-app Tools runner (`list_tools` skip set).
  - Batch build mirrors the SD-sync plumbing: `_fp_build_state`/`_fp_build_lock`,
    `_run_fingerprint_build()` (reuses valid entries, saves every 100), `start_fingerprint_build()`.
  - `_knn_rank(query_key, corpus_items, n)` — pure k-NN: **z-score** standardises each feature
    across the corpus (so a Hz feature can't dominate a 0–1 one) then ranks by euclidean
    distance. `similar_instruments(sin_rel, n)` builds the corpus from `_fp_all_items()` feats
    ∩ avail (no SIN-group filter — cross-group is the point) and calls it. Filtering by avail
    means only actually-usable instruments (their `.sin` present) are suggested — so the baked
    layer shines when `.sin` files are synced but the WAVs are not.
  - Routes: GET `/api/similar?sin=&n=`, GET `/api/fingerprint_status`, POST `/api/fingerprint_build`.
    Test: `tools/test_fingerprint.py` (synthetic bright/dark + long/short-decay WAV fixtures).

## Important JS globals

```js
pads            // array of pad objects from _pad_view()
avail           // {rel_path: abs_path} instrument map
instTags        // {sin_rel: [tag, ...]} from /api/tags
activeTagFilter // currently active tag chip filter (null = all)
kitName         // current kit filename
libSavePath / sdSavePath
selectedPad     // {id, layer} — active assignment target
undoCount / undoLabels
favorites       // Set persisted in localStorage
recentInst      // array persisted in localStorage
instSort        // 'az' | 'used' | 'recent', persisted
hoverPreview / autoPreview  // booleans, persisted
instMtimes      // {rel: mtime float} from /api/instruments
brokenPaths     // Set of sin_rel strings not found in avail
batchMode       // bool — batch-select mode active
batchSelected   // Set of pad IDs selected for batch apply
svgView         // {x,y,w,h} — current drum map viewBox (zoom state)
_velDrag        // drag state for velocity xfade control (null when idle)
_blendCtx       // Web Audio AudioContext for blend preview (lazy-created)
// Virtual module engine (play the edited kit from the pads; near the MIDI code):
vmActive        // toggle state (button #vmod-btn)
vmManifest      // last GET /api/kit_playback response
vmCtx           // one persistent AudioContext (hit path uses pre-decoded buffers only)
vmBuffers       // Map wav_url → AudioBuffer | in-flight Promise (decode cache)
vmVoices        // live voices [{padId, layer, muteGrp, gain, src}] for choke bookkeeping
vmRR            // Map "padId:layer:band" → next round-robin index
vmHH            // last hi-hat pedal (CC#4) value, 127 = open
vmRev           // last manifest rev seen (poll loop refetches manifest when it changes)
window.vmLastHit // debug: {padId, vel, layers:[{layer,mappingIdx,wavUrl,gain,pan,rate,choked}]}
```

**Virtual module engine:** `toggleVirtualModule()` → fetch manifest → `vmPreload()` (eager
under `VM_PRELOAD_LIMIT` 100 MB, else lazy). `vmTrigger(manifestPad, vel)` is the hit path:
layer A/B by `skt.vel_min/vel_max` (B min = xfade), `vmCandidates()`/`vmPick()` for
velocity-zone + RR/random + hi-hat (CC#4) selection, gain = level·sin.level·(vel/127)^1.5,
`StereoPannerNode`, `playbackRate` from semi+fine, `vmChoke()` for mute-group + Mono. MIDI via
`vmOnMidi` wired with `addEventListener` (coexists with the monitor's `onmidimessage`);
number keys 1–0 = keyboard fallback at the `#vm-vel` slider. `vmRefreshManifest()` fires from
the `/api/selected` poll when `param_rev` changes.

Key render functions: `renderDrumMap()`, `renderPadDetail()`, `renderInstruments()`,
`renderKitList()`, `renderPatchPanel()`, `updateAssignBanner()`, `renderTagChips()`,
`renderKitFx()` (kit FX modal), `renderTrigModal()` (SysEx trigger-settings backup modal;
own MIDIAccess with `{sysex:true}`, listens via `addEventListener` to coexist with the
MIDI monitor's `onmidimessage`)

Key action functions: `swapPad()`, `batchToggle()`, `batchApply()`, `checkPaths()`,
`showDiffModal()`, `printMidiMap()`, `importAssignCSV()`, `previewBlend()`,
`startVelDrag()` / `_applyVelDrag()`, `velXfadeControl()`, `editTagsInline()`

**"More like this" (frontend):** the **≈** affordance on instrument rows
(`renderInstItem`) and pad-detail layer rows → `openSimilar(rel)` (GET `/api/similar`) →
`renderSimilar(data)` fills `#similar-modal` (`#sim-body`); clicking a neighbour's name
pivots the search, A/B buttons `directAssign` to the selected pad, ▶ reuses
`previewInstrument`. `buildFingerprints()` (POST `/api/fingerprint_build`) +
`_pollFingerprintStatus()` drive the in-modal progress bar (`#sim-build`), reusing the
`.sync-progress`/`.sync-bar` CSS. `_simRel` holds the active query; there is **no**
`strike_`-prefixed localStorage key (fingerprints live server-side in the sidecar).

**Kit time machine (frontend):** `openTimeMachine()` → `loadTimeMachine()` (GET
`/api/snapshots`) → `renderTimeMachine()` fills the `#tm-modal` list + scrubber. `tmSnaps`
(newest-first) / `tmSel` hold state; `tmSnapshotNow()`, `tmScrub()`/`tmSelect()`,
`tmDiffVsCurrent()` / `tmCompare()` (→ `_tmRenderDiff()`), `tmRestore()` (applies
`data.pads` + re-renders, refreshes the kit-FX modal like `undoLast`), `tmDelete()`,
`tmPin()`. `scheduleAutoSnapshot()` is a 20 s debounce called from `setDirtyState()` when
`dirty` (server dedupe makes redundant fires no-ops). Snapshots persist server-side, so
there is **no** `strike_`-prefixed localStorage key for them.

## localStorage keys (prefix: `strike_`)

`theme`, `padOverrides`, `loopState`, `favorites`, `recent`, `instSort`,
`hoverPreview`, `autoPreview`, `patchPanelOpen`, `loopPanelOpen`

## File format constraints (from official editor research)

- **Filename max:** 26 characters
- **Folder depth:** module shows only one subfolder level under `Kits/` and `Instruments/`
- **Instruments must be in a subfolder** inside `/Instruments/` — cannot be at root
- **Sample paths are absolute** — moving/renaming any WAV breaks all instruments referencing it
- **Kit size limit:** 200 MB per kit
- **WAV format:** 16-bit or 24-bit, 44.1/48/96 kHz, mono or stereo; 48 kHz recommended

## File layout

```
strike_remap.py              # entire application (~5500 lines)
factory_fingerprints.json    # committed: baked similarity vectors for the factory library
factory_catalog.json         # committed: baked catalog of every factory .sin (name/group/mappings) for the web viewer
library/                     # git-ignored — populate from SD card or copy between machines
  kits/                      # saved .skt kit files
  instruments/               # .sin metadata files (and optionally WAVs alongside)
  samples/                   # WAV files synced from SD via "Sync full library from SD"
  snapshots/                 # Kit time machine: <id>.skt blobs + index.json metadata
  tags.json                  # instrument tag sidecar {sin_rel: [tag, ...]}
  fingerprints.json          # "More like this" audio-fingerprint sidecar (keyed by sin_rel)
web/                         # pure-browser port (stage 1 = read-only viewer). See web/README.md
  bytes.js skt.js sin.js     # JS parsers (read-only), Python-parity tested
  similar.js                 # JS k-NN similarity port, Python-parity tested
  viewer/                    # the read-only Web Viewer v1 (dev = served over HTTP)
    index.html app.css       # index.html + app.css/app.js are EXTRACTED VERBATIM from
    app.js                   #   strike_remap.py's embedded HTML — do not diverge; re-extract if the Python UI changes
    engine.js                #   client-side read-only replacement for the /api server (fetch interceptor)
  test_parsers.mjs test_similar.mjs  # Node parity tests (vs tools/dump_*_expected.py), in CI
dist/                        # git-ignored — build output: strike_viewer.html (single self-contained file)
docs/
  screenshot.png             # README hero screenshot (captured from the running app)
  QA_PLAYBOOK.md             # fresh-start UAT procedure (agent-run, human-in-the-loop; phases A–D)
tools/
  hex_explorer.py            # annotated hex dump tool for .skt files
  make_metal_kit.py          # generates a baseline metal kit from library instruments
  test_roundtrip.py          # verifies parse→build is byte-for-byte lossless
  test_sin_roundtrip.py      # verifies parse_sin/patch_sin preserve .sin files exactly
  test_fingerprint.py        # verifies the fingerprint extractor + k-NN + factory-layer logic
  test_time_machine.py       # exercises snapshot create/dedupe/diff/restore/retention
  build_factory_fingerprints.py  # regenerate committed factory_fingerprints.json (needs SD)
  build_factory_catalog.py   # regenerate committed factory_catalog.json (needs SD/library)
  build_viewer.py            # assemble dist/strike_viewer.html (inlines catalog+fingerprints+JS+CSS); --check in CI
  dump_parser_expected.py    # dumps Python parser output for the JS parity test
  dump_similar_expected.py   # dumps Python k-NN rankings for the JS similarity parity test
  make_fixtures.py           # generates synthetic tests/fixtures/ for CI (WAVs + .skt/.sin)
  example_assignment.csv     # sample CSV for batch pad assignment testing
  scan_mute_groups.py        # scan preset kits for mute group usage (needs SD)
  analyze_offsets.py         # statistical offset analysis tools
PLANNED.md                   # feature backlog (all medium items now done)
RESEARCH.md                  # community research, official editor reverse-engineering notes
FORMAT.md                    # public .skt/.sin format spec — keep in sync with offset tables here
CLAUDE.md                    # this file
```

## Web viewer (pure-browser port, stage 1)

Read-only kit explorer built from the **same UI code as the editor**, no Python server at
runtime. Deliverable: a single `dist/strike_viewer.html` (`python tools/build_viewer.py`,
~2.5 MB) that runs from a double-click / `file://` — everything (catalog, fingerprints, JS,
CSS) is inlined; the bundle makes **zero** relative fetches (so `file://`'s fetch block is moot).

- `web/viewer/app.css` + `app.js` are **byte-for-byte extracted** from strike_remap.py's
  embedded `<style>`/`<script>` — keep them verbatim (only diff = 3 `window.VIEWER` guards in
  app.js + an appended `viewer-mode` CSS block). If the Python UI changes, re-extract; don't
  hand-edit the copies.
- `web/viewer/engine.js` intercepts `window.fetch('/api/*')` and serves the **read paths only**
  (mirrors the Python `Handler` shapes); every mutating route returns `{error:'Read-only viewer'}`,
  binary/audio routes 404. `window.VIEWER=true` + `body.viewer-mode` hide all editing affordances.
- Dev: serve the repo root over HTTP and open `web/viewer/index.html` (ES modules + relative
  fetch of the two factory JSONs). Bundle: `build_viewer.py` flattens the modules into one
  classic-script scope (strips `import`/`export` + `[bundle-strip-begin/end]` blocks) and injects
  `window.FACTORY_CATALOG`/`window.FACTORY_FINGERPRINTS`. **Watch for top-level name collisions**
  across the flattened files — classic `<script>`s share one global scope (unlike dev ES modules);
  the bundler fails loudly on any collision.
- OUT of v1 (deferred): all editing/writing, save, File System Access, MIDI, audio preview,
  custom-WAV fingerprinting. Next stages (writers with a byte-equality CI gate, then editing)
  are gated on real interest — see PLANNED.md § Architectural direction.

## What's implemented

Everything in PLANNED.md easy/medium categories is done. See PLANNED.md for the full list.

**Hardware-blocked items** (need module connected for hex diff verification):
- Enumerate the remaining reverb type indices (only 2=Big Gate, 3=Close Mic named) and
  confirm the inferred FX type enum beyond the three hex-diff anchors (0, 1, 3)
- Enumerate the EQ LF/HF frequency tables (only 4 index→Hz points known)
- All per-pad and kit-FX offsets are already hardware-confirmed (May 2026) — see FORMAT.md

## SD card setup

Two volumes expected: "NO NAME" (user, writable) and "NO NAME 1" (preset, read-only).
`get_volumes()` → `(user_root, preset_root)`. Cross-platform:
- **Windows:** scans drive letters D–Z for an `Instruments/` subdirectory
- **macOS:** scans `/Volumes/` for same

Instrument `.sin` files live under `<volume>/Instruments/`. Kits under `<volume>/Kits/`.
SD volume detection searches one level deep (catches Ventoy `STORAGE/` subfolder).
