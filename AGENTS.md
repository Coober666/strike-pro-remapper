# Strike Pro Remapper — Project Brief

**This file is the canonical instruction set for every coding agent** (Codex, Claude Code,
or anything else) — CLAUDE.md is just a pointer here. Read this whole file before changing
code, and keep it current when you change how things work.

Standard-library Python web app (`strike_remap.py`) for editing Alesis Strike Pro drum kit files
(`.skt`). Runs an HTTP server on port 8765; all HTML/CSS/JS is embedded as `HTML = r"""..."""`.

**Conventions CI enforces** (you don't have to remember these, but know why they fail):
- Every no-arg `tools/test_*.py` runs automatically in CI (auto-discovered; nothing to
  register). Only `test_roundtrip.py`/`test_sin_roundtrip.py` are invoked explicitly with
  fixture arguments — if you add another test that needs arguments, give it its own CI step.
- `python tools/extract_viewer.py --check` fails the build if `web/viewer/` drifts from the
  embedded UI. After ANY change to the HTML/CSS/JS inside `strike_remap.py`, run
  `python tools/extract_viewer.py` and commit the regenerated files alongside your change.
- `npm run lint:js` extracts the embedded editor JavaScript to `.build/embedded.js`, then
  runs pinned ESLint rules and `node --check` against that exact artifact.
- `npm run test:browser` generates synthetic fixtures and runs the pinned Playwright/Chromium
  suite against an isolated `.build/browser-library`; `set_library_root()` redirects every
  writable sidecar before the server starts, and the suite must never inspect the developer's
  real library or connected cards.
- Node tooling resolves Python through `tools/python.mjs`. Set `PYTHON` to an executable path
  (paths containing spaces are supported) to override the platform defaults.

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
| Binary parser/writer | `strike_remapper/formats.py`; compatibility imports in `strike_remap.py` |
| Mutable server state | `state` dict (kit_path, pads, instruments, avail, dirty, history) |
| HTTP handlers | `Handler.do_GET` / `do_POST` — all `/api/*` routes |
| Frontend | Embedded string `HTML`; pure JS, no framework |

**All mutations follow this pattern:**
1. Call a pure Python function (`assign_instrument`, `clear_all_pads`, etc.) that edits `state`
2. Handler returns `{pads: _pad_view(...), dirty, undo_count, history_labels, message}`
3. JS updates `pads` array then calls `renderDrumMap()` + `renderPadDetail()`

## Layout (workspace rail + persistent visual editor + contextual panel)

The editor shell is a three-column grid: a 66px workspace rail, the persistent drum-map
workspace, and one contextual panel. Pad, Sounds, FX, History, and Tools switch the right
panel without replacing the map. The module input bay is docked below the map so a selected
jack and every zone it drives remain visible together. The selected pad's Layer A/B rack is
also part of the central workspace.

CSS: `.main { grid-template-columns: 66px minmax(500px, 1fr) minmax(330px, 390px); }`.
At ≤900px the rail remains beside the map and the contextual panel moves below it; at
≤620px the rail becomes a sticky horizontal strip and the shell stacks vertically.

The Sounds panel keeps its assignment target and filters outside the independently
scrolling `#inst-list`. `renderInstruments()` restores a visible row by section/path
and offset when the search/tag/sort key is unchanged, including when recents insert
rows. Assignment never silently advances Layer A to B. Sound names are explicit
assignment buttons; preview and surrounding row space do not assign. Inline path
arguments use `inlinePathArg()`, including names with apostrophes. Preview callbacks
must match the current audio instance before clearing it or reporting failure.
Touch/coarse-pointer sound and layer controls have 44px minimum targets. Browser
regressions live in `tests/browser/workflow-polish.spec.js` and use synthetic media.

Map interactions use Pointer Events captured on the stable root SVG, since pad
children are replaced during dragging. Touch scrolls/selects normally; Arrange pads
enables drag/resize/rotate with `touch-action:none`. Pointer cancellation restores
the original overrides. Velocity dragging also captures its pointer and converts
screen coordinates to SVG coordinates. Keyboard pads and confirmation focus are
covered by `tests/browser/zz-recovery-touch.spec.js`.

## Setlist Builder

The embedded Setlist Builder dialog opens from Start/Kits; generated viewer links stay
hidden. `strike_remapper/setlists.py` owns versioned human-readable local documents in
`library/setlists/<uuid>.json`. GET `/api/setlists` lists saved documents and local kits;
POST actions save/delete/check/copy_kit run under STATE_LOCK and the existing Wi-Fi editor
ownership guard. There is no batch-deploy action. Lists hold at most 128 entries; the
library holds 50 lists; imports/requests are bounded to 1 MB. SHA-256 revisions reject
stale overwrites/deletes; saves use fsync and atomic replacement. A copied setlist/import
gets a new ID. In-browser drafts need explicit Save or Export and are separate from kit
recovery. Lost write responses are never retried automatically.

Kit references are relative to library/kits; never accept absolute/traversal paths or
follow links outside the library. Listing excludes autosaves; copies use exact saved
bytes and exclusive creation, reject case-insensitive collisions, and never load/mutate
the active kit. Local checks parse saved .skt files, require exact round trip, validate
assigned references, and use local .sin / factory-catalog positive evidence only.
Unknown references remain unverified. Local sample headers are inspected through library_assets.py (safe relative paths, no symlinks, bounded metadata reads). Shared files are counted once in the exportable batch preview; missing/ambiguous/truncated files block a row. No SD discovery or card-space checks
occur; do not call a local pass deployment-ready. Filename plans use conservative ASCII,
optional three-digit ordering, at most 26 characters including .skt, reserved-name guards
and case-insensitive duplicate detection. Source names never change. Printing uses the
last local-check snapshot, escaped text and an explicit limitation statement.
Tests: tools/test_setlists.py and tests/browser/zz-setlists.spec.js (Chromium/iPad WebKit).
Removing a song restores focus to the adjacent Remove button (or the kit selector
when empty); cancelling a kit copy returns focus to that song's Copy button.

## General MIDI toolkit

`web/midi-toolkit/` is a separate ES-module page, exposed by an exact asset allowlist
at `/midi` and `/midi/{app,core,storage}.js` plus `styles.css`. Normal host guards and
Wi-Fi pairing apply. It never uses kit editor APIs/state and needs no active Strike kit.
Start/Tools links are hidden in the generated read-only viewer.
`core.js` provides versioned session validation and pure analysis; `storage.js` stores
sessions/metadata atomically in browser IndexedDB; `app.js` captures one explicitly
selected Web MIDI input with `sysex:false`. Do not open/read MIDI outputs or send data.
Visual replay is a playhead/event review only. Paired pages also offer host capture:
`host.js` calls `/wifi/midi/inputs` and POST `/wifi/midi`, independent of kit ownership.
`midi_capture.py` owns one bounded take per host, tied to the paired cookie and a
per-tab capture ID. Start is idempotent while retained; commands never auto-retry.
Poll by event offset (1024/event batch); 15 seconds without polling stops the input,
and the stopped take remains in memory for 10 minutes. Logout revokes it and server
close shuts the worker down. Page hiding requests Stop best-effort; lease is fallback.
`midi_input.py` isolates optional python-rtmidi in a subprocess, constructs only MidiIn,
filters to complete channel messages, bounds its callback queue, and timestamps on
the host monotonic clock. Close/join outside the recorder lock. The Python application
remains stdlib-only unless the user installs `requirements-midi.txt` for this feature.
Session v1 has optional `captureStatus` (complete/partial); preserve it in saves/exports
and mark active browser captures partial on MIDI disconnection, including while paused.
Disconnection after normal Stop must not downgrade a completed take. Show partial copies
after network/driver failure. Recover retained events explicitly;
never automatically start a new take or reacquire after host restart. Native driver
behavior has limited Mac/Strike acceptance: real capture plus idle pause/resume,
lease expiry, ownership and reopen checks (see `docs/MAC_HARDWARE_ACCEPTANCE_2026-10-14.md`).
Other hosts and physical disconnect behavior remain unverified. Tests inject drivers: `test_midi_capture.py`,
`test_wifi_editor.py`, and `tests/browser/wifi-midi.spec.js`.
`midi_setup.py` checks optional package metadata and input enumeration without opening
a port or installing anything. The paired `/wifi/midi/setup` route and optional CLI
`python -m strike_remapper.midi_setup` distinguish missing package, driver error, no
inputs and visible inputs; enumeration never proves input-open success. Driver access
can still fail when Record is used. The report omits the Python executable/user path
and pairing information, but includes input names and bounded driver error text.
`profiles.js` validates user-named pad maps; `profile-ui.js` handles explicit apply/save,
portable JSON and MIDI Learn candidates. No preset manufacturer maps or MIDI writes.
Learn consumes only new received positive Note Ons during recording, requires Apply,
and never replays old events into learning. Wi-Fi can deliver a queued hit: confirm
the candidate. Session v1 optionally embeds a validated `padMap` snapshot, independent
of the profile store and retained across host polling; names do not affect statistics.
`drum-midi-profiles-v1` localStorage is bounded to 25 profiles / 128 KB, with 128 unique
channel/note pairs per profile. Invalid imports/storage cannot replace current data;
failed saves leave export available. Profile names/labels render only as text.
Profile overwrite/delete confirmations re-read saved content before writing and reject
changes made while the dialog was open, preserving the current profile for export.
This localStorage check is not an atomic multi-tab transaction like session storage.
Session v1 also accepts bounded `tags`, `notesText` and an `exercise` key defined in
`metadata.js`; old sessions default to empty values. Preserve annotations across host
polling. Exercises are user-selected instructions, never scored or marked completed.
`organization.js` validates portable session backup JSON: 25 sessions / 200k events /
32 MB file bound. `storage.js` restores new IDs in one readwrite transaction, with a
count guard; never overwrite existing sessions or commit a partial batch. Metadata
and session records stay in sync. Search uses saved metadata, and backups use saved
records from one readonly transaction. Browser-local unsaved work is separate.
Saved MIDI sessions carry a local revision in both IndexedDB stores. Read the session
and revision together; compare revisions inside the same readwrite transaction as
save/delete. Reject stale or deleted targets, retain current edits, and offer Save as
new copy. Legacy records without a revision start at zero; portable session JSON is
unchanged. Copy/restore use new IDs and preserve the 25-session limit. Browser tests
cover two-tab conflicts, concurrent transactions, legacy records and aborted retries.
Analysis focus is a channel/note view, never event deletion: filters in summarize,
compare, charts/replay/report retain original pause boundaries and duration. JSON/CSV,
overview totals and controller list always retain the full take. Reset focus on a
new/load capture. Tests include capacity/transaction-abort restore and empty comparisons.

`tools/build_beta.py` creates an exclusive-output portable source ZIP from an allowlist;
it must never package libraries, secrets, captures, Git state or development dependencies.
Manifest hashes cover all files except the manifest itself. Unix launchers normalize LF
and carry executable bits. `test_beta_package.py` verifies reproducibility from identical
inputs, hashes, exclusions and an extracted paired host with external temporary library
and disabled card discovery. This is not a signed installer or physical OS acceptance.
Note On velocity zero is Note Off; always separate channel/note. Never infer missed
physical hits or trigger faults from MIDI alone. Pause time is excluded and timing
is not calibrated. Bound captures/imports (20 active minutes, 50k events, 8 MB JSON),
reject invalid imports without replacing current work, and retain export after storage
failure. Tests: `npm run test:midi` and `tests/browser/midi-toolkit.spec.js`; injected
WebKit MIDI is simulated and does not establish physical mobile compatibility.

## Host lifecycle and recovery

`launch_editor.py` is an optional Tk desktop window backed by `strike_remapper/host.py`.
It starts only one service, defaults to localhost, and uses the existing paired handler
when Wi-Fi is selected. It never takes over an occupied port or moves existing libraries.
Reject the source application's root as a library even on a fresh extraction with no
library child. Existing source checkouts still point users to their library subfolder;
the frozen Windows package continues to reject all libraries inside its app folder.
Preferences remember the chosen library/address, but Wi-Fi starts off every run. QR
encoding is vendored, unmodified MIT Project Nayuki code; see `strike_remapper/vendor/`.
No QR service receives the pairing token. The GUI/QR scan still need physical acceptance.
The scrollable setup/pairing area keeps host controls in a fixed footer. Windows CI
runs `tools/test_host_window.py` against real Tk widgets and a disposable loopback host;
`STRIKE_REQUIRE_TK=1` makes unavailable Tk/display fail that job (other headless runs skip).
If the post-drain recovery flush fails, `Host.recovery_pending` retains the worker and
active kit. Retry Stop flushes again; start cannot switch libraries until this succeeds.
The window offers Retry recovery save and keeps closing blocked while recovery fails.
Host startup catches common wrong-library selections before creating files. Setup failures
are covered by `test_launcher_setup.py`. `test_library_portability.py` uses copied apps,
fresh processes and external synthetic libraries to verify backup/restore and relocation;
`STRIKE_PREVIOUS_APP` optionally selects an older extracted application for version testing.
Wi-Fi connection loss, unconfirmed save responses and suspended tabs pause editing.
On reconnect, reload the host kit before allowing writes; never replay a failed POST.
`wifiNeedsReload` tracks that requirement and visibility/online events check ownership.

All editor POST handlers run under `STATE_LOCK`. The host-owned `RecoveryWorker` uses
the same lock, writes atomic local autosaves every 60 seconds, and flushes after pending
requests finish on normal shutdown. Imported kits use their display name before a first
save. Load/new/import preserve dirty state before replacement; failed preservation blocks
the switch. Recovery loads remain dirty, normalize the original kit name/save target, and
snapshot current work before recovering another version. Never restore a recovery target
to a removable-card save path automatically. Browser autosave is supplemental, uses
`kitDirty`, and reports failures. Tests: `test_recovery_interruptions.py` and
`test_host_launcher.py`, always with temporary libraries and loopback networking.

## Accessibility and isolated installation checks

Generated pad and Kit FX rows acquire accessible names from their visible labels
through `labelParameterRows`. Parameter rerenders preserve the currently focused
control by its stable onchange attribute, including layer rack controls; do not
restore focus to a stale request sender. Kit FX uses a native dialog with its own
keyboard scope. Let Space activate focused native controls before audition shortcuts.
`setMsg` mirrors action/error feedback into a polite live region; per-hit MIDI
feedback passes announce=false. Preserve these behaviors in generated viewer files.
Regression coverage: tests/browser/zzzz-accessibility.spec.js (Chromium and WebKit).

`tools/check_source_package.py` checks a real ZIP/sidecar, then runs paired startup,
save/recovery and headless setup help in a fresh isolated Python process. Source CI
runs this in a pinned unprivileged offline Linux container. The Python-free
`tools/check_windows_clean.ps1` harness uses fresh temporary libraries and retains
evidence. A successful developer-machine run is not clean-Windows-OS acceptance.

**JS gotcha:** `togglePopover` is a native browser method on `HTMLElement` — the custom
popover toggler is named `menuToggle(id)` to avoid the conflict.

**Visual system (June 2026 overhaul):** graphite surfaces + brass-gold accent; tokens in
`:root` at the top of `<style>`. Selection = CSS drop-shadow glow on the pad `<g>`. Pad
layout overrides live in the active physical setup profile, including
`mirror: {dx, dy}` which
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
mid-drag). Physical setup profiles are independent of kits and auto-save changes to the
active profile. `exportLayout()` / `importLayout(file)` export/import the active setup as
JSON (`format: 'strike-remap-layout'`; import filters to `VALID_PAD_IDS` and tolerates a
bare overrides object). The factory profile is an immutable reset point; users can create,
apply, duplicate, and delete their own profiles in the Setup profiles modal.

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

Python API: `strike_remapper.formats` owns `parse_sin(data)` and
`patch_sin(data, params, cycle_random, mappings)`; `strike_remap` re-exports them for
compatibility. The patcher
writes only known offsets, preserving every unknown byte. `tools/test_sin_roundtrip.py`
verifies no-op + identity patches are byte-identical across the whole library.

Relink: `relink_suggestions()/relink_apply()` + `/api/relink_suggest|relink_apply` —
rewrites strings in `state['instruments']` (the kit str table), one undo entry.
Bundles: `export_bundle()/import_bundle()` + GET `/api/export_bundle`, POST
`/api/import_bundle` (base64 zip) — zip mirrors library layout (kit/, instruments/<rel>,
samples/<wav_rel>) so no path rewriting; import never overwrites existing files.
`bundle_import.py` preflights portable paths, links, duplicate/case-ambiguous names,
supported-entry CRC/decompression and limits in temporary staging before publication.
Limits: 512 MiB ZIP/file, 16 MiB SIN, 2 GiB total and 10,000 ZIP entries. Destinations
must remain in the library with no symlink/reparse components; validate again before
exclusive creation. Existing kits get numbered copies, identical assets skip, other
conflicts keep existing files. On handled copy failure remove only the newly opened
partial file; earlier completed files stay and ImportStopped reports the count. This
is not a crash-atomic multi-file transaction. Cleanup failures identify the incomplete
file; listing failures must not hide completed imports. Never auto-retry uploads.
Tests: `tools/test_bundle_import.py` and bundle browser cases use disposable libraries.
Export holds STATE_LOCK through archive construction, then releases it before network
transfer. This serializes editor mutations, not changes made by external programs.
Populate lazy inventory and prefer local edited SINs over shadow card inventory.
Validate portable source references and reject linked children/case-ambiguous ZIP names;
reuse importer size limits so completed exports can be imported. Card reads use
read_card_bytes. Missing assets remain explicit in manifest.json and the HTTP warning
count; never label an incomplete bundle a self-contained backup. The browser fetches
the full ZIP before requesting a download, keeps errors in-page, suppresses duplicate
clicks and never retries automatically. Use RFC 5987 UTF-8 download filenames and
no-store responses. Tests: tools/test_bundle_export.py and browser bundle export cases.
`export_kits_report()` reads saved library kits under STATE_LOCK using the current
four-part parser and pad dictionaries. Preserve report fields, exclude autosaves and
record unreadable/malformed files in warnings instead of silently dropping them.
The JSON report is not an importable backup and excludes unsaved edits; state that in
download feedback. Both export UIs keep failures in-page and require explicit retry.

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
- `strike_remapper.audio.normalize_wav(wav_data)` → `(bytes, peak_db_str)` —
  peak-normalize 16/24-bit PCM WAV; `strike_remap` re-exports the audio helpers
- `batch_assign_csv(assignments)` — assign multiple pads from `[{pad_id, layer, sin_rel}]`
  after validating all row shapes, pad IDs and A/B layers. Missing instruments remain
  reported skips; malformed rows reject the whole batch without state/history changes.
  Plan final assignments before one Undo snapshot; no-op imports do not dirty the kit.
  The browser accepts two/three comma-separated fields, rejects malformed lines before
  POST, serializes file imports and rejects a changed pad snapshot during file reading.
  Lost responses are not replayed; paired editing pauses until host state is refreshed.
  Tests: `tools/test_csv_assignment.py` and CSV cases in `zzz-release-polish.spec.js`.
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
- **The SD card stops answering for seconds at a time; it does NOT disconnect** (issue #35).
  Under sustained host access the Strike card goes unresponsive in bursts. Established from
  the Windows event log, not guessed: 40× `disk` event 153 ("The IO operation … for Disk N was
  retried") plus event 51 on the Strike disk, and **zero** surprise-removal (157) or
  Kernel-PnP arrival/removal events. The device never leaves the bus; the storage stack times
  out and retries and the volume dismounts under open handles (exactly what `WinError 1006`
  says). It looks like a disconnect in Explorer, so do not trust that impression — check the
  event log. Reads fail with `EINVAL` or `WinError 55/1006`.
  **Read card files through `read_card_bytes()`, never `Path.read_bytes()`** — it retries on
  `_is_transient_volume_error()`. Waits (`_CARD_RETRY_DELAYS`, ~5s total) are sized for the
  observed outage; sub-second retries all land inside the same one and fail together.
  `get_volumes()` waits the same window before reporting a previously-seen card as missing, so
  an outage cannot raise a false `no_user_card` blocker. Recoveries print a `[card]` line to
  the server console — that log is the only way to tell a recovered outage from a clean run.
  Observed only with the official Strike Editor closed, and intermittent on a timescale of
  hours, so a single clean run proves nothing. Test: `tools/test_card_resilience.py`.
- **The module exposes both card LUNs at all times.** With the editor closed, `Get-Disk` shows
  two `ALESIS STRIKE` USB disks: the user card online, and a second one reporting **`No
  Media`**. That second entry is the factory/preset LUN — present but empty until the official
  editor handshakes. Useful for diagnosing preset-card questions (see #33).
  **Activation mapped October 12, 2026:** one `F0 00 00 0E 48 0E 33 03 01 F7`
  SysEx sent to the Strike exposed the factory card with the editor closed, including
  after a user-confirmed module power cycle on Intel macOS Monterey. See
  `docs/FACTORY_SD_ACTIVATION.md` for evidence and limits. The explicit **Activate factory
  card** dialog sends this packet through Web MIDI with SysEx permission. It is local-only
  (localhost/loopback), filters for connected Strike outputs, skips sending if already mounted,
  and confirms `/api/status` card discovery with a 15-second deadline. No startup activation,
  automatic retry, backend MIDI bridge, or deactivation. Keep the read-only viewer blocked.
  Tests: `tests/browser/factory-card.spec.js` (simulated hardware). Do not infer a
  deactivation packet or general live-sync protocol.
- **iPad Wi-Fi factory controller** is a separate opt-in service:
  `python -m strike_remapper.factory_bridge --bind <private LAN IPv4>`. It exposes only
  static controller assets, authenticated output discovery, fixed activation, and job
  status. Never relax the full editor's localhost guard for this feature. Pairing uses
  a fresh process token, exact Host/Origin checks, and no CORS. Native MIDI runs in a
  bounded subprocess (CoreMIDI / WinMM / Linux amidi); only the captured activation packet
  is sendable. Jobs deduplicate the latest 64 IDs and serialize activation; failures never
  auto-retry. Card discovery uses read-only OS flags and factory content shape, **no write
  probes**, and does not prove USB identity. Never claim Windows/Linux/iPad hardware
  validation from simulated tests. See `docs/IPAD_FACTORY_CONTROLLER.md` and
  `tools/test_factory_bridge.py`; `tests/browser/factory-controller.spec.js` runs in
  Chromium and iPad WebKit. Direct-USB native iPad app work is paused and not included.
- **Full Wi-Fi editor** is a separate opt-in `strike_remapper.wifi_editor` entry point.
  It subclasses `Handler` with pairing/session and exact Host/Origin guards; normal
  `strike_remap.py` remains localhost-only. Every editor API and stream requires a valid
  HttpOnly, SameSite=Strict session; writes additionally require matching Origin.
  Pairing and sessions are process-scoped; logout revokes one session, expiry is 12 hours.
  `--library-root` persists host files independently of releases. Browsers share the
  existing single active-kit state: one editing client at a time. LAN HTTP does not
  encrypt traffic; do not expose publicly. The Wi-Fi HTML marks the root element so
  factory activation uses the native host controller, while local Web MIDI is unchanged.
  `tools/test_wifi_editor.py` checks auth boundaries; `tests/browser/wifi-editor.spec.js`
  checks actual editing/saving on an isolated library in Chromium and iPad WebKit.
  **Editing ownership:** `make_handler` holds a process-local token bound to a paired
  session. `/wifi/editor` acquires/resumes or explicitly transfers it. Every full-editor
  POST must carry `X-Strike-Editor`; checking ownership and the complete handler run
  share a lock with transfer/logout. Reload rotates the per-tab resume token; the
  frontend reloads host state before enabling edits on takeover. Other pages are
  view-only snapshots, not collaborative clients. The separate fixed `/api/activate`
  command still uses pairing auth. Localhost behavior is unchanged. Never infer UI
  disabling alone protects writes; keep the host checks and stale-token tests.
  **Connection/save polish:** `/api/status` also returns `library_path`. Connection
  details refresh card discovery explicitly, not on a card-polling loop. Save confirms
  the library copy; Deploy success asks for a module kit reload, and failure preserves
  uncertainty about partially completed writes. New tests are in
  `tests/browser/workflow-polish.spec.js` and `tools/test_wifi_editor.py`.
  **Physical iPad → Intel Mac → Strike verified October 12, 2026:** user changed
  SEVENzREC snare Layer A from BJ DWMaple Center to BJ DWBallad Center, saved on the
  Mac, deployed from iPad, and confirmed playback. Independent reads verified Save
  changed only the library kit, then Deploy made the user-card kit byte-identical.
  Layer B stayed NAC14inMaple Center. See `docs/WIFI_EDITOR.md` for evidence and limits.
  A separate missing-user-card incident was a macOS `loginwindow` mount veto followed
  by eject (`0xF8DA0008`), before the full editor started. Unlock/safe eject/USB reconnect
  recovered both cards without a module power cycle. The underlying policy reason was
  not established; do not assert a lock-screen rule, alter SIP, or guess protocol bytes.
- **Content shape alone cannot identify the factory card** (issue #39). A personal copy of the
  factory library on any drive has the same `Kits/<CATEGORY>/*.skt` shape, and picking it
  silently would bake the wrong inventory into a captured preset manifest. When several
  factory-shaped volumes are mounted, `_pick_module_volume()` prefers the one whose
  `_volume_device_key()` matches the user card's — both of the module's cards are LUNs of one
  USB device, so they share a vendor/product (`ALESIS`/`STRIKE`) while an unrelated drive does
  not. That key comes from `IOCTL_STORAGE_QUERY_PROPERTY` opened with `dwDesiredAccess=0`, so
  it needs no admin rights and touches no media. **Windows only** — elsewhere it returns None
  and classification degrades to the old first-wins behaviour, never to an error. Do not let
  device probing raise: it sits in the path that decides which card gets written.
- `check_paths()` — return sin_rel paths in current kit not found in avail
- **`state['avail']` is populated lazily — never reason about what is "missing" without
  `_ensure_avail()` first.** It is empty until something scans, so a caller that treats an
  unscanned library as an empty one reports a perfectly healthy kit as entirely broken. This
  really happened: relink reported 18 broken references on a kit that actually has 9.
  `check_paths()`, `relink_suggestions()` and `_deploy_plan()` all go through the guard.
- **Relink suggests in tiers and always states its basis** (issue #40). Filename matching
  alone returns nothing when a kit was authored against a different sound library — the right
  sound is on the card under an unrelated name. `relink_suggestions()` falls back through:
  `name` (exact then `difflib` stem ≥ 0.6) → `sound` (`_knn_rank` against the *surviving layer
  on the same pad*, found by `_relink_evidence()`, filtered to the pad's family) → `category`
  (same family, a labelled guess). Every suggestion carries `basis` + `why`, and the UI
  pre-selects **only** `name` rows — auto-selecting a stack of guesses that one click applies
  is the hazard here. Family comes from `_instrument_groups()`, which reads the committed
  `factory_catalog.json` group byte and falls back to the folder name; never parse every
  candidate `.sin` (a filesystem read each, across the whole library).
  Test: `tools/test_relink.py`.
- `load_tags()` / `save_tags()` / `set_instrument_tags()` — `library/tags.json` sidecar
- **Deploy asset resolution has three states, not two** (issue #33). The module's factory
  card needs activation (use the explicit Activate factory card action or official editor), so an
  unresolvable path does NOT mean the file is gone. In `_deploy_plan()`'s `add_asset()`:
  resolved on a mounted volume →
  `available`/`copy`/`present`/`conflict` as before; unresolvable but listed in the preset
  manifest → `available`; otherwise → `unverified`, which rolls up into ONE `warning` issue
  and **never blocks** (writing the `.skt` is harmless — the module resolves paths itself).
  Only `no_kit`, `no_user_card`, `unsafe_asset_path`, `asset_conflict` and
  `insufficient_space` are blockers. `load_preset_manifest()` / `_preset_manifest_has()` /
  `capture_preset_manifest()` mirror the two-layer fingerprint pattern: writable
  `library/preset_manifest.json` over the committed `factory_catalog.json` keys as a
  fallback. **Capture stays user-initiated** — `_looks_like_preset_root()` cannot tell the
  real card from a preset-shaped mirror, so auto-capture could bake in a wrong inventory.
  The manifest may only ever upgrade a reference to `available`, never prove absence.
- **"More like this" similarity search** (audio fingerprints; READ-ONLY, never writes any
  WAV/.sin/.skt). Feature vector `FP_FEATURES` = 5 stdlib, sample-rate-aware features:
  `centroid` (Hz), `rolloff` (85%-energy, Hz), `zcr` (crossings/s, no-FFT brightness proxy),
  `brightness` (energy fraction >2 kHz), `decay` (s for RMS envelope to fall 20 dB).
  - `_fft(re, im)` — hand-rolled in-place iterative radix-2 FFT (no numpy; stdlib-only rule).
    `_read_wav_mono(path, secs)` reads ≤~1.5 s of a 16/24-bit PCM WAV → mono floats + rate.
  - `strike_remapper.audio.extract_fingerprint(wav_path)` → feats dict | None;
    `strike_remap` re-exports the pure DSP helpers. Spectral features come from one
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

## localStorage keys

Prefixed: `strike_pad_overrides` (legacy/current-profile compatibility),
`strike_setup_profiles_v1`, `strike_workspace`, `strike_favorites`, `strike_recent`,
`strike_instSort`, `strike_hoverPreview`, `strike_autoPreview`,
`strike_previewVol`, `strike_previewVel`.

Legacy unprefixed UI state still in use: `loop_state`, `loopPanelOpen`,
`patchCollapsed`.

## File format constraints (from official editor research)

- **Filename max:** 26 characters
- **Folder depth:** module shows only one subfolder level under `Kits/` and `Instruments/`
- **Instruments must be in a subfolder** inside `/Instruments/` — cannot be at root
- **Sample paths are absolute** — moving/renaming any WAV breaks all instruments referencing it
- **Kit size limit:** 200 MB per kit
- **WAV format:** 16-bit or 24-bit, 44.1/48/96 kHz, mono or stereo; 48 kHz recommended

## File layout

```
strike_remap.py              # runnable application, HTTP/UI, and compatibility imports
strike_remapper/
  audio.py                   # state-independent WAV utilities and fingerprint DSP
  formats.py                 # pure binary format parsers/writers; no app-state imports
factory_fingerprints.json    # committed: baked similarity vectors for the factory library
factory_catalog.json         # committed: baked catalog of every factory .sin (name/group/mappings) for the web viewer
library/                     # git-ignored — populate from SD card or copy between machines
  kits/                      # saved .skt kit files
  instruments/               # .sin metadata files (and optionally WAVs alongside)
  samples/                   # WAV files synced from SD via "Sync full library from SD"
  snapshots/                 # Kit time machine: <id>.skt blobs + index.json metadata
  recent_kits.json           # successful kit opens for the start screen (newest first)
  tags.json                  # instrument tag sidecar {sin_rel: [tag, ...]}
  fingerprints.json          # "More like this" audio-fingerprint sidecar (keyed by sin_rel)
  preset_manifest.json       # factory-card inventory captured while the official editor exposed it
  deploy-backups/            # module kits replaced by Deploy to Module, kept before overwrite
web/                         # pure-browser port (stage 1 = read-only viewer). See web/README.md
  bytes.js skt.js sin.js     # JS parsers (read-only), Python-parity tested
  similar.js                 # JS k-NN similarity port, Python-parity tested
  viewer/                    # the read-only Web Viewer v1 (dev = served over HTTP)
    index.html app.css       # GENERATED by tools/extract_viewer.py from strike_remap.py's
    app.js                   #   embedded HTML — never hand-edit; re-run the extractor (CI-gated)
    engine.js                #   client-side read-only replacement for the /api server (fetch interceptor)
  test_parsers.mjs test_similar.mjs  # Node parity tests (vs tools/dump_*_expected.py), in CI
dist/                        # git-ignored — build output: strike_viewer.html (single self-contained file)
docs/
  screenshot.png             # README hero screenshot (captured from the running app)
  QA_PLAYBOOK.md             # fresh-start UAT procedure (agent-run, human-in-the-loop; phases A–D)
  ARCHITECTURE_STABILIZATION.md  # phased safety/decomposition roadmap
tests/
  browser/                   # Playwright workflows + deterministic server lifecycle
tools/
  browser_test_server.py     # isolated real-app server for Playwright (no physical cards)
  python.mjs                 # portable PYTHON/python3/py resolver for Node tooling
  test_python.mjs            # deterministic interpreter-resolution contracts
  extract_embedded_js.py     # write .build/embedded.js for ESLint/node --check
  extract_viewer.py          # regenerate web/viewer/* from the embedded UI; --check in CI
  hex_explorer.py            # annotated hex dump tool for .skt files
  make_metal_kit.py          # generates a baseline metal kit from library instruments
  test_roundtrip.py          # verifies parse→build is byte-for-byte lossless
  test_sin_roundtrip.py      # verifies parse_sin/patch_sin preserve .sin files exactly
  test_audio.py              # deterministic 16/24-bit WAV utility contracts
  test_fingerprint.py        # verifies the fingerprint extractor + k-NN + factory-layer logic
  test_library_isolation.py  # proves test re-rooting cannot write into the prior library
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
package.json/package-lock.json  # pinned Playwright + ESLint development tooling only
AGENTS.md                    # this file — canonical agent instructions (all providers)
CLAUDE.md                    # pointer that imports AGENTS.md for Claude Code
```

## Web viewer (pure-browser port, stage 1)

Read-only kit explorer built from the **same UI code as the editor**, no Python server at
runtime. Deliverable: a single `dist/strike_viewer.html` (`python tools/build_viewer.py`,
~2.5 MB) that runs from a double-click / `file://` — everything (catalog, fingerprints, JS,
CSS) is inlined; the bundle makes **zero** relative fetches (so `file://`'s fetch block is moot).

- `web/viewer/index.html`, `app.css` + `app.js` are **generated by `tools/extract_viewer.py`**
  from strike_remap.py's embedded HTML/`<style>`/`<script>` — never hand-edit them. The only
  permitted divergences (encoded in the extractor): 4 `window.VIEWER` guards in app.js, the
  appended `viewer-mode` CSS block (everything from its marker line to EOF in app.css), and
  index.html's title/link/engine.js head swaps. After changing the embedded UI, run
  `python tools/extract_viewer.py` and commit the result; CI runs `--check` and fails on drift.
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

## Beta identity and support

`support.py` reads the packaged manifest, or bounded Git commands only when the app root has .git. Reports allowlist OS/Python, build identity and editor counts; never include library paths, kit names, addresses, credentials, exceptions or captured data. GET /api/support_report retains normal host/pairing guards and never discovers cards. CI source-beta waits for all three test jobs, builds a clean checkout and uploads a ZIP/checksum without publishing a release.

## Kit Balance Assistant

`balance.py` is state-independent analysis of local files through library_assets.py. It measures first-0.5-second PCM windows, at most eight highest-velocity mappings/layer and 96 unique WAVs. RMS uses channel energy, never stereo downmix; medians compare at least three same-instrument-group/same-layer peers. A/B boundary differences and worst-case overlapping peak sums are estimates. Suggestions are capped at 6 dB and level 1–127; muted/unmeasured layers get no suggestion.

POST /api/balance analyze/apply uses STATE_LOCK and the existing paired ownership guard with an 8 KB body bound. Apply recomputes evidence and validates a token covering kit bytes, revision, SIN bytes, measured WAV bytes/metadata and report. Only server-provided selected levels may be applied. Validate all selections before one _push_history, then change known level offsets; no audio writes. GET balance_preview serves a bounded local sample window. Native dialog UI requires unchecked explicit selection, offers current/proposed audition, and never retries failed writes. New tests: test_balance.py, zzz-release-polish.spec.js. Physical listening acceptance remains open.

Balance preview callbacks check both a request generation and the analysis report.
A newer Listen, dialog close/cancel/reopen, analysis or Apply invalidates pending audio
and errors and stops the current voice. Browser regressions delay responses explicitly
and use a synthetic audio context; they do not establish listening acceptance.
Analysis success/error callbacks also check the dialog generation. Closing/reopening
invalidates the old report without cancelling a server mutation; the busy flag remains
held until the request settles. Apply responses still reconcile the host's kit state.

## Windows folder beta

Build with Python 3.11 x64 and requirements-build-windows.txt using tools/build_windows.py.
The windowed Strike Remapper.exe and private console _internal/StrikeHelper.exe share
bundled modules/data. runtime.worker_command selects source or frozen helper; never use
sys.executable -m in a frozen app. Console helpers launch hidden and retain JSON pipes.
desktop_worker only dispatches named MIDI modes, allowlisted utilities and explicit
release probes. Utilities receive the chosen external library; frozen libraries inside
the app folder are rejected before probing/writing. Package data excludes user libraries.
check_windows_package.py verifies hashes, extracts fresh, removes Python/Tk environment
paths and tests bundled Tk/MIDI plus synthetic library save/recovery without opening
MIDI ports or discovering cards. This is not physical hardware or clean-OS acceptance.
The launcher Open editor starts then opens; Try a demo starts and opens synthetic MIDI.
Wi-Fi demo pairing uses an exact view=demo flag, never a user-provided redirect URL.
Manual updates only. Source entry points remain supported. No automatic activation.
Windows builds also generate Help/*.txt from an explicit public-guide allowlist in
tools/package_help.py, copying two selected screenshots. The text keeps command blocks
intact, points included-guide links at packaged filenames, and uses revision-specific
repository links for omitted evidence. Do not package private captures or whole evidence
directories. These files are covered by PACKAGE-MANIFEST hashes; package checks require
the main help entry points. No runtime Markdown dependency is needed.

Wi-Fi toolkit HTML matching uses the parsed URL path, so /midi?demo=1 keeps its
data-host-midi marker and host input/setup controls. Query strings do not bypass pairing.

_Server uses a backlog of 64 for parallel toolkit module loads over the LAN;
macOS with the default five showed connection resets during real browser checks.
