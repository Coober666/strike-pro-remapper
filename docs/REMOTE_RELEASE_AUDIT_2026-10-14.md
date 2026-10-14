# Remote release audit — October 14, 2026

Windows desktop checks used synthetic MIDI and temporary libraries. They did not
access the connected Strike, its cards or the running Mac editor. Real Mac evidence
is recorded separately in [the hardware record](MAC_HARDWARE_ACCEPTANCE_2026-10-14.md).

## Capture recovery

A reproduced browser MIDI defect marked a take complete after its input disconnected
during recording. Active and paused takes now retain all received events with partial
status, including after save, reload and JSON export. A take stopped normally before
disconnection remains complete. Reports describe missing MIDI events without assuming
the capture came from a host computer.

Validation: 58 Chromium/iPad-WebKit toolkit and Wi-Fi MIDI cases passed. Coverage
includes lost start/stop/poll responses, delayed polls, hidden pages, retained-take
recovery, storage failures, pause boundaries and the 50,000-event limit. New assertions
failed with complete rather than partial status before the fix. Sixteen MIDI core
tests and JavaScript lint passed.

## Representative capacity measurements

These are local development measurements, not minimum device requirements or mobile
hardware acceptance. The synthetic take contains 50,000 events over 1,000 seconds:
one controller event in five, with the remainder note-ons across 24 note numbers.
Its JSON is 1,592,080 bytes. Pure operations used Node 24.13.0 on Windows, one warm-up
followed by seven measured calls. The backup contains four copies, 200,000 events total.

| Operation | Median | Maximum |
| --- | ---: | ---: |
| Validate take | 23.30 ms | 34.28 ms |
| Summarize take | 23.35 ms | 27.95 ms |
| Export all events CSV | 137.33 ms | 158.42 ms |
| Generate report | 21.36 ms | 24.42 ms |
| Validate backup | 41.91 ms | 51.91 ms |

Fresh browser contexts imported and saved the same take through the real UI:

| Browser engine | Import through rendered counts | Save through confirmation |
| --- | ---: | ---: |
| Chromium | 331 ms | 79 ms |
| iPad-sized WebKit on Windows | 238 ms | 304 ms |

Both rendered at most 1,000 timeline dots, reported no page errors, fit a 390-pixel
viewport and opened the file chooser using the keyboard. These single-run browser
timings include automation overhead and are not performance guarantees.

A temporary library held 2,001 synthetic kits and 50 setlists of 128 rows each.
Five listing calls had a 1,918.67 ms median and 2,004.34 ms maximum. The result
contained 2,000 kits, the truncation flag and all 50 setlists; serialized output was
747,488 bytes. This checks the setlist listing path, not sample scanning or SD reads.
No performance change was made from these measurements.

## Keyboard continuity

Cancelling a song-specific kit copy previously hid the focused form without returning
focus to its launcher. Cancel/Escape now restores the song's Copy button. Removing a
song focuses the adjacent Remove button, or the kit selector when the list becomes
empty. Twelve setlist browser cases passed across Chromium and iPad WebKit, including
keyboard-only cancellation and consecutive removals. Viewer extraction and standalone
viewer build validation passed after regenerating the embedded UI.

## Backup and upgrade checks

The fresh-process source rehearsal passed from the preserved older release to
ce076e8 and back using a restored backup copy. Recovery bytes, edited snare level,
tags, sample sentinel and backup hashes were preserved. Existing CI also covers
failed atomic recovery, blocked kit switches, and retrying a failed final Stop save
before changing libraries.

Verified Windows packages 75295a9 and ce076e8 were extracted into separate temporary
folders with Python removed from the child process environment. Each package saved
a synthetic kit and recovery through its smoke check. Both packaged inspectors then
produced identical reads of both versions' saved/recovery kits. Restored backup-copy
and original backup hashes stayed unchanged, as did both application payloads.
This covers packaged utility compatibility and fresh writes; interactive GUI upgrade
on a separate machine remains H6.

## Isolated Mac restart

A separate loopback host used the deployed d768546 code and a temporary library;
card discovery was disabled. Unpaired requests returned 401 and a wrong Origin
returned 403. Normal Stop saved a synthetic unsaved kit. Restarting on the same port
rotated pairing, rejected the old cookie/link, accepted fresh pairing and preserved
recovery bytes. The live LAN editor, real library and module were untouched.

Existing CI covers session expiry, stale writer rejection, explicit handover,
reload token rotation, suspended-page refresh and uncertain Save responses.

## Prepared acceptance and distribution

[Hands-on sessions H1–H9](HANDS_ON_ACCEPTANCE.md) now provide ordered device,
playing, listening, interruption, disposable-media, Windows, Pi/other-module and
outside-beta procedures plus a result form. First-run documentation now distinguishes
the verified Mac input capture from other untested combinations. Preparation does
not mark those hardware gates complete.

All ten PR #68 CI checks passed on ce076e8, including source and Windows packages.
The subsequent documentation changes do not alter that tested runtime.

Physical iPad/iPhone, separate-machine Windows USB, Linux/Pi, Command/Nitro,
listening and disruptive hardware checks remain distinct acceptance gates.

## Second remote pass: saved work and first run

Two toolkit tabs could silently overwrite a saved session, and an older tab could
delete a newer saved version. Session reads now retain a revision; updates and deletes
compare it within their IndexedDB write transaction. Deleted targets cannot be
resurrected by a stale Save. Save as new copy preserves the current take independently
without replacing the newer saved version. Existing records without revisions upgrade
on their next save; portable JSON stays unchanged.

Profile overwrite/delete confirmations also re-check the stored profile after the
dialog closes. A change made during the confirmation blocks that action and leaves
the current pad names exportable. This closes the observed confirmation window;
localStorage profile updates are not atomic multi-tab transactions.

The host previously rejected a source application folder only when it already had
a library child. A fresh extraction could therefore become the library itself. The
host now rejects that root before creating any files or binding a port, while retaining
the existing-library hint for older checkouts.

Each failure was reproduced before its fix. The session changes passed 66 MIDI/Wi-Fi
browser cases; the subsequent profile fix passed eight focused profile cases across
Chromium and iPad WebKit. Six host lifecycle tests, the fresh-process library portability
test, the extracted-source package test and JavaScript lint passed. These checks use
synthetic libraries and browser storage; the live Mac installation was not restarted.

## Bundled help and CI save timing

The Windows ZIP now includes a Help folder with 12 selected public guides, an index,
and two screenshots. Guides are generated as plain text for Notepad, preserving code
examples and rewriting included-guide references to local filenames. Other evidence
links point to the build's repository revision. The allowlist excludes captures and
private evidence; package manifests cover every help file.

The d8b0549 PR workflow passed, but its separate push workflow exposed a test race:
the disconnect regression clicked Save and immediately reloaded before waiting for
the IndexedDB commit. It now waits for Saved in this browser before reloading, matching
the documented workflow. Three repetitions per browser passed after the correction.
Two help-package checks passed, covering the delivered guides, local references,
Unicode text and unchanged command examples.

All ten checks passed on e34814c. Its clean local Windows package passed extracted
runtime/GUI/library recovery checks; the ZIP checksums and all 1,045 Windows and 70
source payload hashes were verified. These packages include the help guides.

## Kit Balance preview ordering

A delayed Listen current response could replace a newer Listen proposed preview.
The failure was reproduced with an explicitly delayed response before the fix.
Preview callbacks now require the current request generation and analysis report;
superseded successes and failures cannot play or replace the current status. Closing
or reopening the dialog, starting analysis, and applying changes invalidate pending
previews and stop the current voice.

Four deterministic scenarios cover a newer Listen, an obsolete failure, dialog
reopening and a new analysis. All 14 release-polish browser cases passed across
Chromium and iPad WebKit, including existing selection/Undo and lost-response checks.
JavaScript lint, viewer regeneration and standalone viewer build validation passed.
Audio uses an instrumented synthetic context: this verifies callback ownership,
not audible quality or physical mobile audio acceptance. The live Mac was untouched.
