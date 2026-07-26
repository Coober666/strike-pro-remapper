# Strike Pro Remapper — vNext Product Direction

## Outcome

vNext turns Strike Pro Remapper from a powerful editor into a clear, safe, end-to-end workflow for drummers:

**Start → Build → Prepare → Deploy → Diagnose**

The application already has the difficult technical foundation: lossless binary round trips, offline kit and instrument editing, library repair, snapshots, audio analysis, MIDI monitoring, and hardware-tested SD-card handling. The next phase prioritizes product clarity and trust over adding more isolated controls.

## Product principles

1. **Local-first and offline.** Core workflows require no account, cloud service, API key, or hosted dependency.
2. **Protect the drummer's content.** Destructive or hardware-facing actions are previewable, backed up, verified, and recoverable.
3. **Progressive disclosure.** Everyday kit work is obvious; research and expert tooling remain available without dominating the main workflow.
4. **One clear source of truth.** The public repository is canonical, and user-facing documentation stays synchronized with shipped behavior.
5. **Hardware-aware, not hardware-dependent.** Users can work locally without the module, then deploy when the module or SD card is available.
6. **Keep the single-file distribution promise.** Internal improvements should not create new setup requirements for users.

## Product structure

### Start

Help users choose the correct first action without searching through menus.

Primary actions:

- Edit an existing kit
- Copy the library from the Strike module or SD card
- Import a kit, bundle, or sound pack
- Create a new kit

The start experience also shows:

- User-card and preset-card status
- Local kit and instrument counts
- Recent kits
- Recoverable autosaves
- A concise explanation that local editing works without an SD card

### Build

The existing editor remains the main workspace. Later vNext improvements add:

- Quick Instrument wizard
- Kit Balance Assistant
- Clear Basic and Advanced groupings
- More visible source and destination context

### Prepare

Turn edited kits into an organized performance collection.

The first feature is Setlist Builder:

- Create named setlists
- Add and reorder kits
- Duplicate kits for song-specific edits
- Generate module-friendly numeric prefixes
- Validate every kit before deployment
- Deploy only the content required by the selected setlist

### Deploy

Replace ambiguous hardware saving with a guided **Deploy to Module** workflow.

Deploy to Module has two deliberately separate phases:

1. **Preflight:** read-only analysis that reports what would happen.
2. **Deployment:** backup, temporary write, verification, and atomic replacement.

### Diagnose

Build on existing MIDI and audio analysis:

- Library health dashboard
- Kit Balance Assistant
- Trigger Coach
- Storage and duplicate-sample analysis

## Milestone 1 — Task-based start screen

### User story

As a first-time or returning user, I want the application to tell me what I can do from the current state so I can begin without reading documentation or hunting through menus.

### Required states

- No local library and no SD card
- Local library present, no SD card
- User card present
- User and preset cards present
- Recoverable autosave present
- Recently opened kits available
- Empty or unreadable card
- Sync previously completed

### Behavior

When no kit is loaded, the start screen replaces the ambiguous empty-editor state. Choosing an action transitions into the existing editor or existing import/sync flow. Existing users can bypass it and reopen it with a Home action.

### Acceptance criteria

- A user can start a useful workflow without opening a dropdown menu.
- The screen never implies that an SD card is required for local editing.
- Recovery is visually prioritized when unsaved work is available.
- Card status uses friendly source names rather than raw paths.
- All actions reuse existing backend operations.
- Keyboard navigation and narrow/tablet layouts are supported.
- Existing load, create, import, sync, and recovery behavior remains unchanged.
- Browser smoke tests cover the principal startup states.

### Technical direction

Prefer a thin orchestration layer over new backend behavior. Compose existing session, status, kit-list, import, sync, and recovery data into one startup view model. Avoid duplicating card detection or library scanning.

## Milestone 2 — Deploy to Module preflight

### User story

As a drummer preparing to use a kit on the module, I want to know whether the kit is complete and exactly what will be written before anything changes on my SD card.

### Proposed boundary

The first implementation is read-only:

    preflight_deploy(kit, destination) -> report

The report should include:

- Destination identity and classification
- Kit destination path
- Files that would be created
- Files that would be replaced
- Missing instruments
- Missing WAV samples
- Kit size and module-limit status
- Invalid or suspicious paths
- Name and compatibility warnings
- Existing snapshot and backup availability
- Blocking errors versus advisory warnings

### Acceptance criteria

- Running preflight performs no writes, including probe or backup writes.
- Identical inputs produce an equivalent report.
- Every blocker includes a user-facing remedy.
- The interface clearly distinguishes safe, warning, and blocked states.
- The existing content/writability card classifier remains the authority for destination identity.
- A complete fixture kit passes preflight in CI.
- Fixtures cover missing WAVs, missing instruments, oversized kits, preset-card targets, and replacement collisions.

## Milestone 3 — Verified Deploy to Module

### User story

As a drummer, I want the application to back up and verify my content while deploying so an interrupted or invalid write cannot silently damage my working kit.

### Deployment sequence

1. Re-run preflight immediately before deployment.
2. Create a recoverable backup of every replaced destination.
3. Write new content to temporary files on the destination volume.
4. Reparse generated .skt and .sin files.
5. Verify expected references and sizes.
6. Atomically replace final destinations where the platform permits.
7. Retain a deployment receipt and backup location.
8. Report when it is safe to eject.

### Safety requirements

- Preset-card destinations are always blocked.
- No final destination is replaced until its temporary file verifies.
- An interruption leaves either the previous valid file or a recoverable temporary/backup file.
- Partial deployment is reported explicitly.
- Deployment receipts contain paths and hashes, not sample contents.
- The user can open the backup location and restore the previous deployment.
- Existing ordinary Save behavior remains available for local editing.

### Acceptance criteria

- CI covers successful deployment, verification failure, replacement, rollback, and interrupted-write simulation.
- Windows and macOS path behavior is tested.
- No deployment path can bypass preflight.
- The completion state identifies the module/card, deployed kit, backup, and safe-eject status.

## Milestone 4 — Setlist Builder MVP

### User story

As a gigging drummer, I want to arrange song-specific kits in performance order and deploy the exact collection needed for a show.

### MVP scope

- Create, rename, duplicate, and delete local setlists.
- Add existing kits to a setlist.
- Drag kits into order.
- Duplicate a kit before making song-specific edits.
- Generate optional numeric filename prefixes.
- Display preflight status per kit.
- Detect duplicate output names.
- Export a printable setlist summary.
- Deploy the selected setlist through Deploy to Module.

### Explicit non-goals for MVP

- Live MIDI kit switching
- Tempo automation
- Cloud synchronization
- Shared collaborative setlists
- Automatic song recognition
- Sample-content deduplication during deployment

### Acceptance criteria

- Reordering never modifies source kits.
- Generated deployment names are deterministic and module-safe.
- A setlist with blockers cannot deploy until the blockers are resolved or the affected kit is removed.
- Setlists remain useful while the module is disconnected.
- Setlist data is portable and human-readable.

## Milestone 5 — Kit Balance Assistant

### User story

As a drummer, I want help finding unexpectedly loud, quiet, dark, bright, or clipping-prone kit pieces so I can create a coherent kit faster.

### MVP scope

Use existing waveform, peak, fingerprint, and mapping data to produce advisory analysis:

- Relative loudness outliers
- Layer A/B balance warnings
- Crossfade discontinuities
- Clipping-risk warnings for stacked layers
- Tom and cymbal consistency comparisons
- Suggested per-layer level adjustments
- Audition before applying
- One undoable batch application

### Guardrails

- Never modify WAV data in the MVP.
- Present suggestions as estimates, not hardware truth.
- Show the measurement basis for each recommendation.
- Keep every applied change undoable and snapshot-compatible.

## Milestone 6 — Trigger Coach

### User story

As a drummer, I want the application to analyze how my pads trigger during real playing and suggest module settings without experimentally writing unknown SysEx values.

### MVP scope

- Guided capture session per pad
- Velocity histogram
- Missed-hit and double-trigger indicators
- Crosstalk timing correlation
- Hot-zone and consistency indicators
- Before/after session comparison
- Suggested sensitivity, threshold, retrigger, and crosstalk changes for manual entry on the module
- Exportable diagnostic summary

### Guardrails

- MVP is advisory and does not write trigger settings.
- Suggestions explain their evidence and confidence.
- SysEx restore remains separately labeled as experimental.
- Raw MIDI capture stays local and is not uploaded.

## Supporting initiatives

These support vNext but should not block the first four milestones:

- Quick Instrument wizard: drop WAVs, auto-map, create an instrument, and assign it to the selected pad.
- Library health dashboard: missing, unused, duplicated, oversized, and orphaned content.
- Portable Windows and macOS release artifacts.
- Hosted read-only viewer with a bundled demonstration kit.
- Authenticated LAN/tablet controller with an explicit pairing step.
- Basic/Advanced presentation that moves developer and research utilities out of the everyday path.

## Recommended implementation order

1. Start screen
2. Deploy to Module preflight
3. Verified Deploy to Module
4. Setlist Builder MVP
5. Kit Balance Assistant
6. Trigger Coach

The first release boundary may contain milestones 1–3. That produces a complete improvement by itself: a new user understands how to begin and can move a validated kit onto the correct module storage with visible safeguards.

## Success measures

- A fresh user can begin editing without consulting the README.
- A user can explain the difference between local Save and Deploy to Module.
- No deployment occurs without a passing preflight.
- Every replaced module file has a recoverable backup.
- A setlist can be created and prepared while offline.
- Advanced capabilities remain available without dominating first-run use.
- Existing binary round-trip and hardware-safety guarantees remain green.

## Out of scope for this roadmap

- Replacing the Strike module as a low-latency performance instrument
- Cloud accounts or hosted user libraries
- An LLM dependency for kit creation
- Editing unknown binary offsets without hardware confirmation
- A complete architecture rewrite before user-facing workflow improvements

## Tracking issues

- [#25 — Task-based start screen](https://github.com/Coober666/strike-pro-remapper/issues/25)
- [#26 — Read-only Deploy to Module preflight](https://github.com/Coober666/strike-pro-remapper/issues/26)
- [#27 — Verified Deploy to Module workflow](https://github.com/Coober666/strike-pro-remapper/issues/27)
- [#28 — Setlist Builder MVP](https://github.com/Coober666/strike-pro-remapper/issues/28)
- [#29 — Kit Balance Assistant MVP](https://github.com/Coober666/strike-pro-remapper/issues/29)
- [#30 — Trigger Coach advisory MVP](https://github.com/Coober666/strike-pro-remapper/issues/30)
