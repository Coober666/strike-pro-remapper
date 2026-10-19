# Release priorities

Current direction: ship a dependable Strike editor, then add general drum-MIDI utilities.
Native iPhone/iPad Companion now supports setlist viewing and local session restoration.
The first standalone editing milestone adds confirmed per-pad settings, existing-reference
assignments, undo/redo and verified export to a new `.skt` copy. Imported originals
stay untouched; edits are memory-only until export. The native workspace adds a
selectable standard drum map and zone switching. The next priority is direct native
MIDI input, then proving module-storage access, toward iPad + Strike operation
without a computer. See [the native editor plan](docs/NATIVE_STRIKE_EDITOR_PLAN.md).
Sound libraries, playback, kit-edit recovery and direct mobile storage remain future work.
Physical iPad/Files-provider and module acceptance of native edited copies remain open. Historical viewer-first
research is preserved in [the roadmap archive](docs/ROADMAP_ARCHIVE.md), not a release gate.

## Integrated on main; physical acceptance pending

PRs #60–64 merged October 13, 2026; CI passed on integrated commit `3cab90e`.
The historical roadmap draft #24 was closed as superseded by this plan and the
remaining feature issues. This records software integration, not new hardware evidence.

- Connection/card/library status, explicit Save versus Deploy, and Wi-Fi editing ownership.
- Persistent pad/zone and A/B target, touch sound controls, stable search/scroll and previews.
- Host-owned atomic recovery, imported-kit recovery, preserved edits on kit changes,
  failed-write protection, and duplicate new-kit-name protection.
- Pointer-based map arrangement, cancellation, zoom buttons, keyboard selection and
  confirmation focus management. Normal touch mode preserves page scrolling.
- Optional Python/Tk host window with Start/Stop, persistent library choice, Open editor,
  offline pairing QR, and diagnostics without the pairing token. This is not an installer.
- Upgrade/rollback instructions and a [beta acceptance checklist](docs/RELEASE_CHECKLIST.md).
- Reconnect/suspended-tab state refresh, unconfirmed-save handling, first-run guidance,
  and automated backup/relocation rehearsal (real version boundary tested from `afdca93`).

## Next gates

The [October 14 candidate review](docs/RELEASE_REVIEW_2026-10-14.md) reconciles all eight
open issues and the #66 → #67 → #68 stack. Runtime candidate `d56baec` passed all ten
CI checks and verification of the actual CI downloads. The [beta handoff](docs/BETA_CANDIDATE_2026-10-14.md)
pins its downloads, hashes and first test. Merge/release integration and the physical
acceptance sessions remain distinct gates.

The integrated MIDI toolkit adds local generic MIDI capture, saved browser sessions,
visual replay, velocity/controller measurements, session comparison and portable exports.
It is the measurement foundation for #30, not Trigger Coach advice. Real Mac/Strike
CoreMIDI capture is verified, including notes and hi-hat CC4. Idle ownership,
pause/resume, lease expiry and reopen checks also passed. See the bounded
[October 14 evidence](docs/MAC_HARDWARE_ACCEPTANCE_2026-10-14.md).
The Wi-Fi toolkit adds paired host input capture, host timestamps and retained-take
recovery; other OS drivers, physical disconnection and newest mobile workflows still
need testing. Module-specific recommendations remain deferred.
The setup/profile follow-on adds read-only host diagnostics, confirmed MIDI Learn,
portable user-named profiles and capture snapshots of pad names. No factory maps are
assumed. Diagnostics and learning have simulated coverage; Mac/Strike input access
is verified, while physical Strike/Command/Nitro pad mapping remains acceptance work.
The session workflow pass adds searchable notes/tags, atomic batch backup restore,
pad-focused analysis and optional unscored capture exercises. A portable source-beta
builder and first-run guide support release rehearsal; Python installation, signing
and physical module/mobile acceptance remain separate gates.

1. Test the unsigned Windows bundle on an independent machine and with a connected
   module. The current Intel Mac uses tested browser-launch shortcuts and an isolated
   CoreMIDI environment; its Python lacks Tk. Mac Tk distribution, physical QR scanning
   and user acceptance of normal Stop/recovery remain separate work.
2. Test real iPad/iPhone touch, scrolling, audio gestures and reconnects. Automated
   Chromium/WebKit tests support development but do not establish device compatibility.
3. Exercise interrupted deployment and restoration using disposable media, then confirm
   the copied kit and both layers on the Strike.
4. Finish distribution/signing after the launch and storage paths pass acceptance.
   PR #67 supplies a tested unsigned Windows ZIP with Python/Tk/MIDI bundled; PRs #66
   and #67 remain open, with #68 adding saved-work and import/export hardening.
   Test upgrades while preserving an external library.
5. Invite a small outside beta to independently install, edit, save, deploy and restore.
6. Add a focused general MIDI utility once the Strike workflow is dependable; do not
   broaden into an unverified universal module editor.

## Open issue mapping

- #28: local Setlist Builder merged in #65; #66 extends local checks: host-persisted lists, song
  notes, touch/drag ordering, exact kit copies, portable JSON, local saved-kit checks,
  deterministic filename plans and printable show sheets. Batch deployment through the
  existing deploy pipeline, card collision/space checks and physical acceptance remain.
- #54: factory activation implemented; broader host/module hardware verification remains.
- #56: Wi-Fi editing and touch changes implemented; physical mobile acceptance remains.
- #35: card resilience has automated coverage; disposable-media interruption testing remains.
- #57: Raspberry Pi host spike remains hardware-unverified.
- #55: direct iPad USB research remains deferred; the native kit inspector does not access USB.
- #29: Kit Balance Assistant has a local sample-based MVP: bounded RMS/peak measurements, same-group and A/B warnings, audition and explicit one-Undo level adjustments. Physical listening acceptance remains open.
- #30: MIDI measurement foundation is integrated; evidence-based Trigger Coach advice remains.

The physical iPad → Intel Mac → Strike save/deploy/playback record is in
[WIFI_EDITOR.md](docs/WIFI_EDITOR.md). No newer polish or launcher behavior inherits that
hardware acceptance automatically.
