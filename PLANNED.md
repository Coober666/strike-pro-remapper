# Release priorities

Current direction: ship a dependable Strike editor, then add general drum-MIDI utilities.
Native iPhone/iPad apps and direct mobile USB remain paused. Historical viewer-first
research is preserved in [the roadmap archive](docs/ROADMAP_ARCHIVE.md), not a release gate.

## Implemented in the current polish branch; physical acceptance pending

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

The separate MIDI toolkit branch adds local generic MIDI capture, saved browser sessions,
visual replay, velocity/controller measurements, session comparison and portable exports.
It is the measurement foundation for #30, not Trigger Coach advice. Physical capture
and module-specific recommendations remain unverified or deferred. The follow-on Wi-Fi
toolkit branch adds paired host input capture, host timestamps and retained-take recovery;
its native driver and real mobile/device acceptance still need physical testing.
The setup/profile follow-on adds read-only host diagnostics, confirmed MIDI Learn,
portable user-named profiles and capture snapshots of pad names. No factory maps are
assumed. Diagnostics and learning have simulated coverage; real input access and
physical Strike/Command/Nitro mapping remain acceptance work.

1. Physically test the launcher on Windows and the existing Intel Mac, including its
   Python/Tk installation, QR scanning, correct library choice and normal Stop/recovery.
2. Test real iPad/iPhone touch, scrolling, audio gestures and reconnects. Automated
   Chromium/WebKit tests support development but do not establish device compatibility.
3. Exercise interrupted deployment and restoration using disposable media, then confirm
   the copied kit and both layers on the Strike.
4. Package/sign desktop releases after the launch and storage paths pass acceptance.
   Test upgrades while preserving a library outside the application folder.
5. Invite a small outside beta to independently install, edit, save, deploy and restore.
6. Add a focused general MIDI utility once the Strike workflow is dependable; do not
   broaden into an unverified universal module editor.

## Open issue mapping

- #54: factory activation implemented; broader host/module hardware verification remains.
- #56: Wi-Fi editing and touch changes implemented; physical mobile acceptance remains.
- #35: card resilience has automated coverage; disposable-media interruption testing remains.
- #57: Raspberry Pi host spike remains hardware-unverified.
- #55: direct iPad USB research remains paused with native mobile development.
- #28–30: Setlist Builder, Kit Balance Assistant and Trigger Coach are future work.

The physical iPad → Intel Mac → Strike save/deploy/playback record is in
[WIFI_EDITOR.md](docs/WIFI_EDITOR.md). No newer polish or launcher behavior inherits that
hardware acceptance automatically.
