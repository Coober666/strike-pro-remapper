# Native kit editor: physical iPad and NAS follow-up

Date: October 18, 2026. Signed development build 0.5.1 (6), built from
6b1be3b, on iPad Pro 12.9-inch (6th generation), iPadOS 27.0.1.
Installed simulator checks preceded the device installation; see the
[simulator follow-up](IOS_COMPANION_051_SIMULATOR_FOLLOWUP_2026-10-18.md)
for its passing coverage and retained iPad search timeout.

The owner authorized installation and live-device control. Codex operated the
physical iPad through Xcode Device Hub's live screen; the observations below are
agent-observed UI, not owner-reported confirmations or simulator results. Personal
signing settings, device identifiers, real kit names and NAS paths remain private.

## Observed workflow

- Imported an owner-provided real kit from the existing NAS connection in Files.
  The wide layout showed the zone list beside pad details and both layers.
- Selected Snare Head and opened Layer A Level. The initial value was 99; first
  focus selected the whole value and typing 73 replaced it. Explicit Apply showed
  Level 73 and Edited copy. Layer B remained 95 and unassigned; the A reference
  remained unchanged.
- Undo restored Level 99 and Original imported. Redo restored Level 73 and
  Edited copy.
- Selected the shared export folder and exported once. The app reported a new
  Kit-edit-<8 hex digits>.skt copy. Independent NAS readback found the same
  2,440-byte length and exactly one byte changed: the confirmed level byte 99→73.
  Python parse/build reproduced the exported bytes exactly. The original kit's
  SHA-256 matched its pre-test baseline throughout.
- Reopened that exact exported copy through Files, explicitly confirming replacement
  of the in-memory edited session after the export was verified. The new filename
  appeared with Original imported; Snare Head showed Level A 73, Level B 95 and
  the same assigned/unassigned references.

The exported copy remains in the shared exports folder. No original kit was
written, replaced or moved. The app was not uninstalled. Keyboard capture and the
temporary keep-awake process used for this pass were released afterward.

## Limits

This verifies this physical iPad, app build, real kit and existing NAS Files
connection. It does not establish all providers, offline synchronization,
interruption recovery, VoiceOver, instrument/sample resolution, audio playback,
MIDI, direct module storage or module reload/playback. Kit edits remain memory-only
until explicitly exported. Other numeric controls retain their simulator coverage;
this physical pass exercised direct replacement, Apply and Undo/Redo.
