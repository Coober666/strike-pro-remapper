# Hands-on acceptance sessions

Run one session at a time and record its result below. These are prepared procedures,
not completed hardware tests. Start with H1–H3; H4–H6 need deliberate reconnects,
temporary libraries or disposable media. Use the tested build's revision in every
record. Keep kit libraries, browser MIDI backups and reusable pad profiles separate.

The existing Mac installation has **Open Editor**, **Pair iPad**, and **Stop Editor**
shortcuts in the desktop's Strike Editor folder. The Windows beta uses
**Strike Remapper.exe**. For another source installation follow [first run](BETA_START.md)
and [host setup](HOST_LAUNCHER.md). A browser closes independently of the host.

## H1 — iPad and iPhone workflow

Allow about 10–15 minutes per device. Have the USB host awake, a copied kit library,
and the phone/tablet on the same trusted network. Record the actual model, OS and browser.

1. Scan the host's current pairing QR. Confirm the address starts with `http://`.
   Open the editor, then the Drum MIDI toolkit. Pairing must work without installing
   a mobile app or giving the mobile browser direct USB access.
2. Load the synthetic demo. Name it, add a tag and note, Save session, then reload.
   Reopen the saved take; the demo should retain 96 hits and your annotations.
3. Export its JSON and a report. Find both in Files, then import the JSON in another
   browser/device. Confirm event count, notes and labels; browser shelves need not
   mirror each other automatically.
4. Create a named pad profile with one manually entered channel/note, apply a label,
   and export/import the profile separately. A session backup does not back up the
   reusable profile shelf.
5. With a copied kit, test scrolling, pad/layer selection, Arrange mode, resize,
   rotation and returning to normal scrolling. Test an explicit sample-preview tap
   at a comfortable listening volume. Record anything that scrolls, assigns or plays
   unexpectedly. This step edits only the host's working library if you choose Save.
6. Make a two-song setlist, reorder it, add notes and Save. Reopen from another paired
   page, export JSON and batch preview, and print/save its show sheet. Verify the
   files in Files. Batch preview does not deploy anything.

Expected: controls fit, intended gestures work, downloads are usable, saved state
survives reload and unsaved state is never described as saved. Do not mark an iPhone
passed because the iPad passed. H2 adds actual host-MIDI capture.

## H2 — Pad zones and hi-hat mapping

Allow 5–10 minutes. Prepare a list of connected physical pads and the zones you use;
do not assume a factory MIDI map. Select the explicit module input on the Wi-Fi host.

1. Record ten separated medium hits on one zone, then Stop and export JSON. Name
   the take with the pad and zone. Note the observed channel/note and any extra notes.
2. Repeat for head/rim or bow/edge/bell zones that physically exist. Test a cymbal
   choke separately and record the actual message type; do not assume it is a note.
3. Capture ten soft and ten hard hits on one zone as separate named takes. Keep the
   same sticks and posture. Compare distributions without treating MIDI velocity
   as measured loudness or assuming an intentional hit always produced one event.
4. For the hi-hat, capture fully closed, intermediate and open positions plus slow
   pedal travel and a foot action. Record controller number, observed minimum/maximum
   and which end corresponds to open. The Strike has shown CC4; direction and usable
   physical range still need confirmation.
5. Use Learn next hit, play one zone and confirm the candidate before Apply pad name.
   Export the completed profile. Save/export each take before Release host copy.

Expected: the selected input records and exports intact; each named zone has evidence.
Unexpected messages are findings, not automatic proof of crosstalk or missed hits.

## H3 — Listening and balance

Allow 10–15 minutes with a copied kit and representative local samples. Record the
kit, pad/layer and listening path. Missing factory audio must remain unmeasured.

1. Audition the original kit: soft/hard hits, A/B transitions, round-robin variation,
   mute/choke behavior and the FX you actually use. Note a short baseline.
2. Analyze local samples in Kit Balance. Listen current/proposed for one suggestion.
   Apply only that selection and confirm one Undo restores the original level.
3. Compare the full kit again. The half-second preview and numerical estimates cannot
   certify musical balance, sustained tails or module loudness.
4. When ready to authorize a module write, save under a distinct test name and deploy
   to a disposable/confirmed test destination. Reload that kit on the Strike and play
   it. Confirm both layer assignments and the intended change against the baseline.

Expected: audition, Apply and Undo agree; missing samples are explained. Record module
playback separately from browser preview. No new FX type/frequency names are confirmed
by this test unless separately verified with controlled evidence.

## H4 — Connection interruption and recovery

Allow 10 minutes. Save/export existing work first. Use a disposable kit/take and
interrupt one connection at a time; no kit deployment may be running.

1. During host MIDI recording, play a short phrase, hide/lock the mobile page, then
   return and Recover host take. Save/export what remains. Hiding requests Stop;
   the missing-poll fallback stops the input after 15 seconds. The host keeps a
   stopped take for 10 minutes, not indefinitely.
2. Make a fresh capture, play a phrase, then deliberately disconnect the USB cable.
   Record the error and event count. Received events should stay exportable and a
   driver failure should be labelled partial. Reconnect, refresh inputs and explicitly
   choose/Record again; recording must not resume automatically.
3. Turn the mobile device's Wi-Fi off and back on during a disposable editing session.
   Reconnect and reload host state before further edits. An unconfirmed Save must
   never be silently replayed. Inspect the library to determine whether it arrived.
4. Stop/restart the host normally. Scan the new QR; the previous link/session must
   fail. Confirm a disposable unsaved kit has a recovery entry, but export unsaved
   setlists and MIDI takes before restarting because their recovery rules differ.
5. Host sleep/wake and module power cycling are separate, explicitly arranged tests.
   Record mounts and inputs afterward. Do not infer success from USB reconnect alone.

If a take cannot be recovered, export the received partial copy before Forget. Do not
activate the factory card repeatedly to troubleshoot an unrelated connection failure.

## H5 — Disposable media and restoration

Arrange this session explicitly with an expendable SD card and a distinct test kit.
Record the selected destination identity/capacity and back up its entire contents first.
Do not use the working card, factory card, or system drive for failure injection.

1. Complete one normal deployment and compare destination kit bytes with the saved
   source. Reload/play the kit on the module before introducing a failure.
2. On the disposable card only, arrange insufficient free space for the planned copy.
   Preflight should explain the shortage and leave existing destination files intact.
   Record what was planned and what changed; do not fill the host system disk.
3. In a separately approved interruption run, remove connectivity during a deliberate
   test deployment. Treat the destination as uncertain, regardless of how the UI looks.
   Retain the error and compare file hashes after reconnecting.
4. Restore from the untouched backup to a working test copy/card. Verify hashes, kit
   loading and playback. A backup existing on disk is not proof that restoration works.

Batch deployment remains disabled. This procedure covers the individual deployment
pipeline and does not authorize unattended card writes or arbitrary power cuts.

## H6 — Windows installation and USB

Use a separate Windows machine without Python when available; keep library files
outside the extracted application folder. Follow [Windows beta](WINDOWS_BETA.md).

1. Verify the ZIP checksum, extract everything and open Strike Remapper.exe. Try a
   demo and Open editor. Record launch/reputation/firewall prompts without disabling
   system security. Confirm Stop closes the host and preserves disposable recovery.
2. Choose an external copied library. Save a test kit, Stop, back up the library,
   extract the next package into a new folder and select that working library.
   Confirm kits, tags, snapshots and recovery. Roll back using a copy of the backup.
3. With the Strike connected, run Host setup check and explicitly capture a short
   take. Only then test factory activation once if needed, verifying read-only factory
   discovery alongside the user card. Do not interpret successful enumeration as
   successful recording or storage access.
4. Use H5 for deployment acceptance, and H1 for Windows-hosted mobile pairing.

## H7 — Linux or Raspberry Pi host

Have the actual Pi/Linux machine, network access and an identified module available.
Record CPU architecture, OS, Python and installed MIDI backend; Mac evidence does not
establish Linux support. For initial preparation, use the repository's pinned MIDI
requirements and [MIDI setup guide](MIDI_TOOLKIT.md), installing into a dedicated venv.

1. Launch the terminal Wi-Fi host against an empty/copied external library and the
   machine's private LAN address. Keep the port on the trusted network.
2. Pair another device; run Host setup check, enumerate and explicitly capture input.
   If setup fails, keep its report and stop before proposing device permissions or
   driver changes. Do not run the entire editor as root as a workaround.
3. Confirm Stop/restart, new pairing and external-library recovery. Record SD mount
   access separately. Only an explicitly approved Strike test should send the known
   factory activation packet; no other module should receive it.

## H8 — Command and Nitro profiles

Photograph or transcribe the exact model labels first, including whether either Nitro
is a Pro. Connect one identified module at a time. Repeat H2 with its visible input,
then export a profile named for that exact module and setup. Test ten hits per zone,
pedal/controller movement and any actual choke behavior. Keep ambiguous zones unnamed.

Expected: useful generic MIDI recording, profiles and comparison. This does not establish
kit-file editing, trigger-setting writes or Strike factory-card support for those modules.

## H9 — Outside beta

Give a tester the tested build, checksum and first-run guide, plus a copied library or
the synthetic demo. Ask them to install without coaching, save/reload a demo, export a
backup, make a setlist and stop/restart. Record every place they need help. Hardware
Save/Deploy/Restore acceptance requires their identified module and backed-up test media.

Ask: What did you expect? What happened? What wording or step was unclear? Where did
you find your saved work? Collect build/OS/browser and an exact reproduction sequence.
Use the troubleshooting report; omit pairing tokens and private audio/library files.

## Result form

Copy this for each device and session. Prepared, blocked and not-run are distinct from pass.

```text
Session ID (H1–H9):
Date and tester:
Build revision / ZIP checksum:
Host OS / Python / MIDI package:
Mobile model / OS / browser, if applicable:
Module exact model / firmware / connection, if applicable:
Working library or disposable media confirmed:
Steps actually performed:
Expected result:
Observed result, event counts or hashes:
Result: pass / fail / partial / blocked / not run
Evidence: exported report/take/profile or screenshot, with private tokens removed
Next action:
```

Native iPhone/iPad applications and direct mobile USB remain paused. These procedures
exercise the browser editor and USB host; they do not restart native app development.
