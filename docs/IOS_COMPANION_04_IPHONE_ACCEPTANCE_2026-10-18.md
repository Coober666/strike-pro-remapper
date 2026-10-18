# Companion 0.4 iPhone acceptance — October 18, 2026

Limited attended checks on a physical iPhone 17 running iOS 26.6.2, using
Companion 0.4.0 (4) built from `35cd6dbfa7f936c903dd9ca6ea9f1c794165bd64` with
installed Xcode 27.1. Software checks and owner observations are separated below.
This is not complete device, accessibility or module acceptance.

## Build and installation evidence

- Existing owner-selected development signing was supplied as a local build
  override; the shared project and original checkout's signing settings were
  unchanged. No account/team/device identifiers or profiles are committed.
- The physical-device build succeeded; `codesign --verify --deep --strict`
  passed. The bundle identified itself as 0.4.0 (4), and installation succeeded.
  The existing development profile expires October 24, 2026; a fresh profile/build
  will be needed after expiry. This is not a distribution or notarization result.
- The first foreground launch was denied because the phone had auto-locked.
  After the owner unlocked it, launch succeeded. Developer Mode and pairing were
  already enabled; no security settings were changed for this follow-up.
- Ignored local build/install/launch evidence and synthetic fixtures are retained
  under `.build/ios-device-20261018-04/` in the original checkout. These local files
  may contain signing/device metadata and are not public artifacts.

## Owner-confirmed UI checks

1. **Try demo** displayed Soundcheck, Song 1 of 4. **Next** displayed Paper
   Satellites, Song 2 of 4. Choosing **Extra large** visibly enlarged the notes.
2. A programmatic terminate-and-launch started a fresh app process. The owner
   confirmed Paper Satellites, Song 2 of 4, with extra-large notes still selected.
   This verifies selection/reading-size persistence with the bundled demo.
3. **Kit inspector → Try synthetic kit** displayed the pad-zone list. Snare Head
   showed Layer A `Synthetic/Snare.sin`; scrolling showed Layer B
   `Synthetic/Brush Snare.sin`.
4. **Done** returned to Paper Satellites, Song 2 of 4, with the larger notes.
5. The owner accepted an AirDrop of `Strike-Companion-Kit-Check.skt`, an exact
   copy of the committed synthetic Demo.skt (1944 bytes). Strike Companion opened
   automatically and displayed that filename's pad-zone list. Snare Head details
   opened successfully. This is attended external `.skt` Open In evidence.
6. While those details were open, the owner accepted `Strike-Kit-Rejection.skt`,
   containing deliberately invalid synthetic text. Companion displayed **Kit
   couldn’t be opened**. After **OK**, the owner confirmed that the original
   Snare Head details remained open.

The agent did not independently view or automate the phone's UI. These are the
owner's reported observations, paired with local build/install/launch receipts.
No personal kit library, sounds or cards were used. The original setlist and kit
imports remain read-only; this session does not independently verify phone-side
source-file checksums or prove any referenced sound exists.

## Remaining scope

Physical persistence of an externally imported setlist after its source is
removed, performance-view preference persistence, Close setlist, successful
in-app Files/provider imports, physical iPad, VoiceOver and inspector large-type/
rotation acceptance remain separate checks. Prior 0.3 rotation/reading checks are
historical evidence, not automatic acceptance of every 0.4 screen.

The inspector has no binary writer/export/editing, playback, sound resolution,
host connection, MIDI or deployment. Kits remain in memory across inspector
navigation, not across process launches. See the separate
[simulator acceptance](IOS_COMPANION_04_SIMULATOR_ACCEPTANCE_2026-10-18.md) for
format contracts, injected failures and simulated phone/tablet workflows.
