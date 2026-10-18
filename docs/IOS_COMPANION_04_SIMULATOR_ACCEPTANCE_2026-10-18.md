# Companion 0.4 simulator acceptance — October 18, 2026

This records local synthetic verification of session persistence and the first
read-only kit inspector. It does not extend the attended 0.3 iPhone acceptance to
new physical-device workflows.

## Tested source and tools

The complete run tested commit `121fbb343b0f6f2b279a6d5fa4729cf41d13fb89` with
Xcode 27.1 (27A9275), using installed iOS 27.0 iPhone 17e and iPad Pro 13-inch (M5)
simulators. Both devices passed nine unit tests and seven UI tests: **32 tests,
zero failures, zero skips**. The helper receipt reports unchanged source hashes
and exit code zero for each device. Logs, xcresults, screenshots and the receipt
are retained locally under the ignored `.build/ios-inspector-final/` output.

The subsequent UI-only refinement increases the gap between the inspector's two
layer columns from the default to 32 points. The focused iPad inspector
UI recheck passed, and its screenshot was inspected; the full-run result above refers to the named commit.

## Covered behavior

- Restore a validated app-owned setlist copy, selected song, notes size and
  performance view. Restoration works after the source file is removed; search
  starts empty. The cold-launch UI check verifies song and performance view;
  the model check verifies the exact reading size and document contents.
- Failed imports preserve the open and saved session. Corrupt, unsupported and
  oversized snapshots do not restore or silently overwrite the saved bytes.
  An invalid attempted save preserves the last good snapshot. A blocked save
  path retains current work, reports the failure and supports an explicit retry.
  Close setlist removes the saved document and preserves reading preferences.
- Seventeen committed synthetic kit cases agree with the Python parser for valid
  files. Swift checks header/payload/tail bytes, references, signed values,
  unknown zones, unresolved string indices, every truncation boundary before the
  opaque tail, malformed blocks and count/size limits. Import failures retain
  the current kit/selection. Valid and invalid source bytes are never changed.
- Open a synthetic kit through the inspector and through explicitly targeted
  Open In; inspect both layers and return to the same setlist/song. Wide iPad
  shows list/detail together; iPhone uses list/detail navigation. An initial
  test found Done missing on pushed details; the corrected destination toolbar
  passed the complete run. Screenshots were inspected on both device sizes.
- Existing setlist import/rejection, Files cancellation, search, performance view,
  navigation, rotation and scroll reset remain covered by the full UI suite.

The existing Mac app bundle, standalone contracts, independent Swift-package
consumer and ad-hoc signature verification passed on the same source commit.
The Python format/build-helper suites passed eleven tests; the separate no-arg
kit fixture check also passed. No private kit library, sound files or cards were
read. Personal signing settings remain local and uncommitted.

## Limits and next attended checks

CI is separate evidence and must be checked on the PR. The legacy Xcode 16.4 job
explicitly skips the two document-handoff UI tests because its automation does
not deliver file URLs; model import contracts and the other UI tests still run.
The modern Xcode job must run both handoff tests.

The phone was not replaced during the initial simulator run. A subsequent
[attended iPhone session](IOS_COMPANION_04_IPHONE_ACCEPTANCE_2026-10-18.md) verified
demo song/reading-size restoration, synthetic kit inspection, external `.skt`
AirDrop/Open In and invalid-kit retention. Successful in-app Files/provider imports,
physical iPad, VoiceOver and broader accessibility acceptance remain pending.
Guide any necessary installation or attended checks one step at a time.

The inspector has no writer/export/editing, sound resolution, audio, host
connection, MIDI or deployment. Retaining original bytes is not evidence for a
future binary writer's round-trip behavior. Kit inspection remains in memory;
only the independent setlist session is restored across launches.
