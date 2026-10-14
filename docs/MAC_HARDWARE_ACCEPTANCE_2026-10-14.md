# Mac + Strike acceptance — 2026-10-14

Late-2016 Intel MacBook Pro, macOS Monterey 12.7.6, Alesis Strike USB connected.
Python 3.14.3; python-rtmidi 1.5.8 built successfully in a dedicated virtual
environment (CoreMIDI backend). System Python and Homebrew packages were not upgraded.

## Verified

- Clean source package acd4b8a installed beside the previous editor. A disposable
  library passed save, recovery, bundled utility, HTTP assets and pairing checks.
- Real input capture through the authenticated Wi-Fi MIDI API: 90.277 seconds,
  921 channel events, 430 positive-velocity note-on messages, 18 distinct note
  numbers, velocities 1–127, and controller 4 (hi-hat pedal). The user played pads
  and moved the pedal. Capture completed, was exported and released. This does not
  establish missed-hit/crosstalk rates or prove every physical zone independently.
- Exactly one explicit factory activation request exposed a 7.9 GB read-only
  factory card while the 15.9 GB user card remained mounted. Updated editor listed
  118 local-library kits, 117 factory-card kits and 13 user-card kits.
- All 126 existing library .skt/.sin/.json files matched their pre-update hashes;
  no files in that set were added. No kit save/deploy, firmware change or factory
  file write was performed. Normal user-card detection uses its existing temporary
  create/delete writability probe; factory detection does not use that probe.
- Real LAN browser testing from Windows to the Mac, using iPad-sized WebKit:
  unpaired setup API returned 401; pairing/demo/host-setup worked; actual Strike
  input was listed; no page errors or horizontal overflow. Five consecutive fresh
  toolkit navigations passed after the connection-queue fix. This is browser-engine
  coverage, not acceptance on a physical iPad/iPhone.

## Unattended input lifecycle follow-up

At 16:44–16:45 UTC, the same deployed host and real Strike CoreMIDI input passed:

- A second paired browser was denied both reading another browser's take (403)
  and replacing it with a new take (409).
- Pause held the active duration constant; Resume continued recording.
- Leaving the capture unpolled for 18 seconds triggered the 15-second lease:
  recording stopped, and the original browser could recover the retained take.
- Discard allowed a fresh capture. Logout released that capture, after which the
  second browser could start, stop and discard its own take.

These were idle captures with zero received events, so this checks real-driver
lifecycle and retained metadata, not event recovery during playing or physical
USB disconnection. Both test pairings were logged out, and the editor stayed up.
No MIDI output, card API, kit mutation or factory activation was invoked.

## Defects found and fixed

The /midi?demo=1 route lost its host-MIDI marker because the Wi-Fi wrapper matched
an exact URL instead of the parsed path. Commit 0dcfe31 fixes it and adds both
pairing-boundary and browser assertions for host controls.

Both WebKit and Chromium encountered connection resets while loading the ES-module
graph over the LAN. The Mac server inherited a backlog of five connections. Commit
d768546 raises it to 64; repeated real-LAN loads then passed. Final Mac deployment
 uses clean source revision d768546de236b6f6a181e4a5a702a0f4f6047ae3.

## Operation and remaining work

The Mac's Python lacks Tk. Browser-based Open Editor, Pair iPad (private QR), and
Stop Editor shortcuts were provided in a Strike Editor folder on its desktop.
They use the isolated MIDI environment, validate the managed process before stopping,
keep the old source deployments, and prevent idle system sleep while the host runs.
No login/background auto-start service was installed.

Still outstanding: physical iPad/iPhone acceptance of the newest workflows;
USB unplug/replug and module power-cycle recovery; independent pad/zone and hi-hat
range mapping; listening acceptance for playback and balance suggestions; updated
packaged Windows direct-USB MIDI/SD tests; native Mac distribution/signing and the
unverified FX/EQ enumerations. Earlier successful iPad deployment evidence remains
separate from this no-kit-write session. Native mobile development is still paused.

Private pairing credentials, raw performance data and local library paths are
excluded from this repository record. The raw take is saved separately for the user.
