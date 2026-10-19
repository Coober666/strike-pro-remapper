# Companion 0.5 simulator acceptance — October 18, 2026

This records synthetic verification of the first native kit-copy editing milestone.
The iPhone/iPad app shares the existing Swift library and version-1 setlist format.
Imported originals are read only; exporting creates a new uniquely named `.skt`.

## Source and tools

Tested source: `333a9d11f1c6b0784983264578efae6203c691d1`.
Xcode 27.1 (27A9275), installed iOS 27.0 iPhone 17e and iPad Pro 13-inch (M5).

Each simulator passed 16 unit tests and 11 UI tests: **54 passed, zero failures,
zero skips** across the pair. The receipt covers all 30 native/build inputs,
reports unchanged source hashes and exit code zero for both devices. A separate
comparison after completion confirms those inputs still match the tested source.

Evidence stays local in ignored `.build/ios-kit-editing-awake-final/`: logs,
xcresults, the 30-input source receipt and screenshot exports. The Mac was unlocked
and temporarily kept awake for the final run. Screenshots were inspected on phone
portrait/landscape and wide iPad layouts. The helper stopped only simulators this
work started; the preexisting iPad mini simulator was retained. No physical device
was installed or configured in this run.

## Verified behavior

- 169 Python/Swift editing cases compare exact output bytes using the Python
  editor's confirmed parameter map and binary writer. All 38 supported pad
  parameters, signed/range boundaries, MIDI channel conversion, gate-time gaps,
  existing-reference assignments and Unassigned agree. Invalid edits leave bytes
  and history unchanged.
- No-op reassembly and edits retain KIT and string blocks, reserved bytes,
  variable payload lengths and opaque tail. Large 4096-byte chunks and a
  16-bit assignment above index 255 are covered. Unknown values remain raw until
  explicitly changed. Unknown zones, duplicate IDs and empty string-table slots
  remain inspectable/copyable with editing disabled.
- Undo/redo restores exact bytes, retains at most 20 small patches, ignores
  no-ops, rejects invalid edits without losing redo, and clears redo on new edits.
  Velocity bounds cannot be inverted. Header FX and Layer B maximum stay untouched.
- Exports exclusively create a 21-character ASCII filename, flush and read back
  the same descriptor, decode it and compare exact bytes. Collisions and symbolic
  links cannot overwrite existing files. Injected partial/truncated writes clean
  up this attempt's file; another process's replacement is retained and reported.
  Invalid destinations/data fail without changing the source or current edits.
- File-presenter observers verify that imports and new-copy exports request no
  saves of original/unrelated documents. The regression detects the former
  default-read/merge coordination behavior and passes with the corrected modes.
- UI checks apply/cancel numeric edits, reject unsupported values, change both
  layer assignments, edit signed pan, undo/redo, retain edits after Done, and keep
  the setlist/song independent. Replacing a validated dirty kit requires explicit
  discard; cancellation and failed imports retain current work/history.
- Both simulator sizes complete edit → local Files-folder export → reopen the
  exact newly created file and display the changed value. Picker cancellation
  retains the open setlist or edited kit. Existing setlist persistence, navigation,
  search, notes sizing, performance view, rotation and import regressions remain covered.

The Mac companion app, standalone contracts, independent package consumer and
ad-hoc signature verification passed at `44ea3ef5a1820af4e07b25e5f226179933c995f6`;
its shared core and Mac-specific sources are unchanged in the final tested source. Twelve Python
format/build-helper tests, 17 inspector fixtures, the 169 editing oracle cases,
and three synthetic kit round trips pass. No personal kit library, sounds or
cards were read. The original checkout's local signing file remains hash-identical.

The receipt helper's earlier parent-directory exclusion bug is fixed: exclusions
apply inside native inputs, allowing complete source hashes from nested `.build`
worktrees. A dedicated regression checks this and detects source changes. The
older 0.4 acceptance note now qualifies its one-input receipt accurately.

## Remaining acceptance

CI is separate evidence on PR #77. Xcode 16.4 intentionally skips the two existing
Open In launch tests; Xcode 27 must execute them. Other contracts run on both.

Kit edits are memory-only until export and are not restored after process exit.
Export before closing the app; Done retains edits while it remains open. Handled
write failures retain edits, and retries are explicit. Process interruption can
leave an incomplete new copy. A local byte check does not establish cloud sync,
sound availability or module playback.

Physical iPad, external Files providers, VoiceOver/Dynamic Type and module checks
remain attended acceptance gates. Continue one manual step at a time, beginning
with connecting an unlocked iPad using a data cable. Sound libraries, audio,
direct USB/MIDI, deployment and kit-edit recovery are outside this milestone.
