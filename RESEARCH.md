# Strike Editor — Browser Replacement: Research & Reference

> Generated from community forum research, official Strike Editor User Guide (v1.2), competitor analysis, and architectural review. Written as a project reference doc.

-----

## Background

The Alesis Strike Editor is a desktop app (Windows/macOS) that connects to the Strike/Strike Pro module via USB to edit kits and instruments. It requires a physical module connection at all times, has a history of macOS compatibility failures, and is generally regarded by the community as functional but painful to use. This document captures what the original editor does, what users want, what competitors do better, and what the technical blockers are for a browser-based replacement.

-----

## What the Official Strike Editor Does

### Kit Editor

- Graphical kit layout — click a pad zone to select it
- Two layers (A and B) per zone, each assigned an instrument
- Per-layer controls:
  - Amp: Level (0–99), Pan (-50 to +50), Decay (0–99)
  - Pitch: Semi (-12 to +12 semitones), Fine (-50 to +50 cents)
  - Filter: Type (LoPas/HiPass), Cutoff (0–99)
  - Velocity-to: Volume, Filter, Decay, Tune (all -99 to +99)
- Per-zone controls:
  - FX send levels (Reverb, FX1, FX2, EQ/Comp on/off)
  - Playback mode (Mono/Poly)
  - Priority (Low/Medium/High)
  - Mute Groups (Off, 1–9)
  - MIDI Note (0–127), MIDI Channel (1–16), Gate Time, Note Off behavior
- Per-kit shared FX:
  - EQ/Compressor (LF/HF gain+freq, compression type, threshold, output)
  - Reverb (Type 0–99, Level, Size, Color)
  - FX1 + FX2 (flanger, chorus, vibrato, delay variants with sub-parameters)

### Instrument Editor

- Build instruments from WAV samples
- Define velocity ranges (1–127), assign samples per range
- Cycle mode: Round Robin or Random (anti-machine-gun)
- Hi-hat cymbal instruments: 3–5 layers (Open, Semi-Open x1-3, Closed) mapped to pedal position (0–127)
- Hi-hat pedal instruments: Chick/Stomp + Splash functions
- Auto-Map: analyzes sample loudness, auto-assigns to velocity ranges
- Quick Instrument: one-click single-sample instrument creation

### File Management

- All saves write directly to SD card via live USB connection
- Save = .skt (kit) or .sin (instrument) file on SD card
- Export = ZIP archive for sharing/backup
- Import = ZIP only (not drag-and-drop from filesystem)
- Samples must be 16-bit or 24-bit WAV, 44.1/48/96 kHz, mono or stereo
- 48 kHz recommended (native module rate)

### Constraints Baked Into the Format

- File names: 26-character maximum
- Folder depth: module shows only one subfolder level for Kits and Instruments
- Instruments must live in a subfolder inside /Instruments/ — cannot be placed at root
- Sample paths are absolute — moving or renaming any sample file breaks all instruments referencing it
- Kit size limit: 200MB per kit

-----

## Community Pain Points (What Users Hate)

### 1. Requires Physical Module Connected at All Times

The single most-requested improvement across every forum. You cannot prep or edit kits away from your kit. The editor scans the SD card on every launch through 5+ sequential passes before anything is usable. A dedicated community thread exists asking for a standalone offline mode.

### 2. Notoriously Slow Startup

A dedicated forum thread exists titled "Strike Editor — VERY SLOW!" Cold starts on large SD cards take a long time due to sequential scan passes: internal drive → kit files → instrument files → sample files.

### 3. Mac Compatibility Is Unreliable

Multiple users report the editor failing to connect on MacBook Pros. A dedicated thread asks whether it works on macOS 12 at all. At least one user switched modules entirely because Alesis never responded to support emails about the Mac issue.

### 4. No Undo/Redo

Make a bad edit and there's no way back. This is deeply felt even if rarely mentioned explicitly.

### 5. Only 2 Layers Per Zone

Power users layering acoustic samples over electronic sounds hit this ceiling constantly.

### 6. No Visual Velocity Curve Editor

Everything is 0–99 knobs. No graphical representation of how velocity maps to volume, pitch, or filter response.

### 7. No Waveform Display

Sample preview is audio-only — no visual representation of the sample shape.

### 8. No Copy/Paste Between Zones

Setting 3 toms to the same tuning/FX requires doing it manually three times.

### 9. No Batch Operations

No way to apply the same EQ, tuning offset, or FX setting across multiple zones at once.

### 10. Rigid File Structure With No Relinking

Moving or renaming any sample breaks every instrument that references it. No way to relink broken paths — you just get a "path not found" error.

### 11. "Disk Not Ejected Properly" OS Warnings

Every save triggers an OS warning because the module writes directly to the SD card, bypassing normal OS file I/O.

### 12. No Community Kit Sharing

No discovery, no sharing, no library. Third-party sites (like VExpressions for Roland) fill this gap commercially, which tells you how much demand exists.

### 13. No Trigger Sensitivity Editing in Software

Threshold, sensitivity, and crosstalk settings are module-only. No software access.

### 14. Kit-Level FX Only

Reverb and FX are per-kit, not per-pad. You can adjust send levels per zone, but the actual reverb/effect is shared across the whole kit.

-----

## Competitor Landscape

### Roland TD Manager / V-Drums Workshop

- Better trigger curve editing with graphical velocity response curves
- More polished UI overall
- Still requires USB connection (no offline mode)
- Tighter hardware integration (Roland designs both ends)

### 2Box DrumIt Editor

- More functional offline than Strike Editor
- Cleaner sample management
- Smaller hardware install base, community has moved on

### VDrumLib (Third-Party Roland)

- Go-to tool for TD-20-era Roland users
- Limited parameter editing scope
- Cannot preview sounds — a major gap even in the best third-party tool in the space

### VExpressions (Third-Party Roland Kit Packs)

- Community workaround for the absence of kit sharing in any official editor
- People pay real money for curated kit packs
- The Alesis community has explicitly requested something equivalent for Strike

### Superior Drummer 3 / EZDrummer

- Not module editors, but set the UX bar users mentally compare against
- Waveform visualization, drag-and-drop sample management, visual velocity curves, extensive tagging/search, per-pad mixer with real sends
- This is what users imagine when they think "how it should work"

-----

## Feature Priority List

### Already Solved (Per Project Status)

- [x] Offline kit editing (no module required)
- [x] Undo / redo
- [x] SD card file management

### No Technical Blockers — Pure UI Work

- [ ] Copy/paste zone settings
- [ ] Batch apply settings to multiple zones
- [ ] Visual velocity curve editor (graphical, not knobs)
- [ ] Waveform display on sample preview (Web Audio API)
- [ ] Sample audio preview
- [ ] Sample browser with waveform thumbnails and search/filter
- [ ] Kit size meter with per-zone breakdown
- [ ] Dark mode
- [ ] Keyboard shortcuts
- [ ] Round-robin sample count visualization per velocity tier
- [ ] Kit comparison / A/B view
- [ ] Better search and tagging beyond text match

### Moderate Effort / Known Path

- [ ] MIDI monitor (real-time pad trigger + velocity display)
  - Web MIDI API, Chromium-only, requires user permission grant
  - Module sends standard MIDI note-on on pad hit — straightforward to listen for
- [ ] Sample normalization / gain staging pre-import
  - Web Audio API handles this — decode buffer, analyze, apply gain, re-encode

### Hard / Reverse Engineering Required

- [ ] Real-time module parameter sync (live knob changes reflected on module)
  - Requires cataloging MIDI SysEx messages via USB traffic capture
  - Workaround: write-to-SD-card + user triggers kit reload on module
- [ ] Trigger sensitivity / threshold / crosstalk editing in software
  - Unknown whether these params are exposed via SysEx at all
  - May be firmware-only with no external access path

-----

## Technical Blockers by Category

### USB / Hardware Access

- **WebUSB API**: Chromium-only, cannot access USB Mass Storage class devices (OS claims them at driver level) — cannot reach SD card this way
- **Web MIDI API**: Chromium-only, works for MIDI communication and SysEx if needed
- **File System Access API**: Best path for SD card — user picks mounted SD card folder once, persist handle in IndexedDB, re-request permission on subsequent sessions with one click
- **Bottom line**: Effectively Chromium-only regardless of approach

### File Format

- .skt and .sin are undocumented proprietary formats — already reverse engineered per project status
- Sample paths are absolute, not relative — important to handle gracefully in UI (warn on broken paths, offer relink)
- Folder structure rules are rigid and must be maintained exactly for module compatibility

### Real-Time Sync

- Would require MIDI SysEx reverse engineering via USB traffic capture (e.g., Wireshark for USB)
- Each parameter change would need a mapped SysEx message
- Alternative: write-files + reload workflow eliminates this blocker entirely at the cost of UX polish

### Cross-Browser

- Web MIDI and robust File System Access API = Chromium-only in practice
- Fine for this audience (drummers on Chrome/Edge is a safe assumption)
- If native file I/O or raw USB ever needed: **Tauri** is preferred over Electron (same web frontend, Rust backend, ~5MB installer vs ~150MB)

-----

## Distribution Considerations

### Current Recommendation: Browser PWA

For a tool built for personal use and potentially shared with the community, a Progressive Web App hosted on a static host (Cloudflare Pages, GitHub Pages) is the right call:

- Zero install friction — runs in browser, installable with one click
- Silent updates — users always get latest version
- No signing, no app store, no packaging
- File System Access API covers SD card management
- Web MIDI covers MIDI monitoring

### If Native Wrapper Ever Needed: Tauri

- Keep existing web frontend entirely unchanged
- Add Rust backend only for specific native calls (raw file I/O, native MIDI via `midir` crate)
- ~5MB installer vs Electron's ~150MB
- Worth considering if SysEx reverse engineering requires raw USB access

### Not Recommended: Electron

- 150MB+ installer for a niche drum editor is a hard sell
- Tauri achieves the same thing at a fraction of the size if native access is needed

-----

## Notes on Scope

- **TAM is small**: Strike Pro and SE sold well for Alesis but this is a niche instrument with a passionate user base, not a mass market
- **Community is tight-knit**: alesisdrummer.com, vdrums.com, and a few Reddit communities — word travels fast in a small space
- **Monetization not a goal**: tool exists to solve a personal problem (broken module screen + broken official editor)
- **The VExpressions model**: if a kit content marketplace were ever layered on top, there is demonstrated willingness to pay for quality curated content in this community
