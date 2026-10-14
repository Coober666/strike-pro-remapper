# First outside beta acceptance

Use a copied library and disposable SD card for interruption tests. Record OS, browser,
Python, app commit, module model and the actual result; simulations do not prove hardware
support. Preserve the existing verified iPad → Intel Mac → Strike record separately.

Use [the prepared hands-on sessions and result form](HANDS_ON_ACCEPTANCE.md) for
device, playing, listening, reconnect, media, Windows, Pi and outside-beta checks.
For the pinned October 14 candidate, see the [completed automated gate record](RELEASE_REVIEW_2026-10-14.md#verified-candidate-gates)
and [exact download/first-test handoff](BETA_CANDIDATE_2026-10-14.md). The boxes below
remain a reusable checklist for the eventual release revision.

## Automated gates

- [ ] CI passes on the release commit: format round trips, regression tests, browser
  workflows, lint, parser parity and read-only viewer generation.
- [ ] Kit switching preserves dirty edits; failed writes preserve the last good recovery.
- [ ] Imported kits recover with their original name and remain unsaved until Save.
- [ ] Wi-Fi handover rejects stale writers, and failed recovery never claims success.
- [ ] Pointer cancellation restores layout; keyboard Cancel cancels; narrow layouts fit.
- [ ] Host lifecycle, occupied port, pairing and expired previous-run tokens pass.
- [ ] Windows Tk controls start/stop the real host using a disposable library; failed
  final recovery can be retried and blocks closing/library changes. Controls fit short windows.
- [ ] Lost Save responses never replay writes; reconnect/suspended-page flows reload
  current host state, and old sessions/tokens fail after a host restart on the same port.
- [ ] Copied external libraries survive fresh-process upgrade, backup and rollback
  rehearsal; backup file hashes remain unchanged. Record the previous release tested.
- [ ] Setlist reorder/copy/check/print keeps source kits and active editor state intact;
  stale saves, failed writes, malformed imports and duplicate planned names are handled.

## Hands-on gates still required

Partial evidence: [October 14 Mac/Strike checks](MAC_HARDWARE_ACCEPTANCE_2026-10-14.md)
verify real capture, idle input lifecycle and card discovery. They do not complete
the physical disconnect, newest mobile UI, listening or Windows USB gates below.
The current Mac uses browser-launch shortcuts because its Python lacks Tk.

For each candidate, also run the packaged-source smoke test and follow the
[beta first-run walkthrough](BETA_START.md). Record the manifest revision.

- [ ] A new Windows user launches, chooses a persistent library and opens the editor.
- [ ] The Intel Mac launcher starts with its installed Python/Tk and retains library choice.
- [ ] iPad and iPhone cameras scan the QR code; pairing succeeds over HTTP.
- [ ] Real touch scrolling, arrange/resize/rotate, velocity controls and audio work on iPad.
- [ ] Close the browser, stop normally, restart, and recover the last unsaved edit.
- [ ] Restart Wi-Fi / wake the host; reconnect without presenting stale edits as saved.
- [ ] On disposable media, exercise full-disk, interrupted copy and backup restoration.
- [ ] Deploy a copied kit, reload it on the Strike, and confirm sound and layer assignment.
- [ ] Upgrade and roll back application files while keeping a copied library intact.
- [ ] Another person completes install, edit, save, deploy and restore without developer help.
- [ ] Host MIDI setup/Record succeeds with real OS input drivers; unplugging retains the take.
- [ ] On real iPad/iPhone, learn pad names, annotate a take, filter one pad and export it.
- [ ] Transfer a session backup and reusable pad profile to another browser/device; verify
  notes, event counts and labels. Browser data and the host kit library are separate backups.
- [ ] On real iPad/iPhone, arrange and save a setlist, reopen it from another paired page,
  export/import it with copied kits, and print/save its show sheet. Batch deploy is deferred.

Signed installers, automatic updates, and native mobile/direct-USB apps are not included
in this beta. Do not describe simulated browser tests as device acceptance.

## New remote preparation tools

- [ ] On real iPad/iPhone, download a collection preview and troubleshooting report; confirm both can be found in Files.
- [ ] Listen to representative real Strike kits before/after selected Kit Balance changes. Check missing local factory samples, mute behavior, A/B transitions and one-step Undo. Compare module playback after normal individual-kit deployment.
- [ ] Download a successful CI source-beta artifact, verify its checksum, extract to a new folder and follow the first-run walkthrough on a separate library.
- [ ] Batch deployment remains disabled until actual destination preflight and disposable-media interruption/restore acceptance are implemented.
