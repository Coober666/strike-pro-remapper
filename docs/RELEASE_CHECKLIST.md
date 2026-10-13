# First outside beta acceptance

Use a copied library and disposable SD card for interruption tests. Record OS, browser,
Python, app commit, module model and the actual result; simulations do not prove hardware
support. Preserve the existing verified iPad → Intel Mac → Strike record separately.

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

## Hands-on gates still required

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

Signed installers, automatic updates, and native mobile/direct-USB apps are not included
in this beta. Do not describe simulated browser tests as device acceptance.
