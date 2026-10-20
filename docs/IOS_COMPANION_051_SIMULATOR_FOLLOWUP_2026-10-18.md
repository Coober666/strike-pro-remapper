# Companion 0.5.1 simulator follow-up — October 18, 2026

The numeric-input follow-up adds a large editable number, explicit Clear,
whole-number slider and fine ±1 adjustment. First focus selects the value for
replacement. These controls change pending text; Apply commits it, Cancel leaves
the kit unchanged, and unsupported typed values are retained with Apply disabled.
The original-file and new-copy exporter contracts are unchanged.

## Local evidence

Xcode 27.1 with the installed iOS 27.0 iPhone 17e and iPad Pro 13-inch (M5).
Receipts, logs, screenshots and xcresults remain in ignored `.build/` directories.

- `ios-numeric-iphone-final`: full iPhone suite at `6b1be3b`, 16 unit tests and
  11 UI tests passed, zero failures/skips. All 30 recorded inputs remained unchanged.
- `ios-numeric-scroll-acceptance`: full iPad attempt with the scroll-helper change
  later committed as `e9e13e9`. All 16 unit tests and ten UI tests passed, including
  every kit-editing/export test. The existing setlist-search UI test timed out in
  keyboard animation waits. This attempt is retained as a failure.
- `ios-search-submit-check`: focused iPad search/navigation/performance test passed
  in 24 seconds after splitting query entry and Return into separate actions.
  The subsequent `6b1be3b` commit includes those actions and a comment-only wording
  change. No app implementation changed between these runs.
- `ios-files-stall-reproduction`: before the helper follow-ups, iPad edit → Files
  export → reopen passed unchanged in 49 seconds. An earlier local attempt's
  numeric-entry animation timeout remains recorded separately.

This establishes passing coverage across the full iPhone run, the iPad run and its
focused search follow-up. It is **not** a claim of one clean full-suite run on both
devices at the final commit. The earlier animation stalls remain a simulator
reliability limitation; they have not been silently retried or counted as passes.

## Verified interactions

Both sizes pass large-value entry, Clear, direct replacement, slider adjustment,
invalid-value retention, Cancel, explicit Apply, signed pan and both layers.
Undo/Redo, retained edits after Done, portrait/landscape layouts, replacement
confirmation and export-folder cancellation remain covered. Files export/reopen
displays the edited value and retains the original Layer A reference. The Swift
tests also verify original bytes, reserved-byte preservation, exclusive creation,
collisions, partial-write cleanup and file-presenter isolation.

The hosted CI failure at `7984d79` asked XCTest for an offscreen Layer B control's
hittability. Hosted accessibility failed with an invalid activation point instead
of returning false. The helper now waits for the edit sheet to disappear, checks
the control's frame is in the unobscured viewport, scrolls in the required direction
and only then queries hittability. All value, assignment and final visibility
assertions remain. The Files reopen helper uses the document image in icon view
or the actual cell in list view, avoiding coordinate taps through the hosted service.

## Remaining acceptance

CI on PR #77 is independent and must finish on the updated branch. No merge is
implied by these local checks. The 0.5.1 build has not yet been accepted on a
physical iPad. The previously attended 0.5.0 controls, layout and Undo are recorded
in the separate iPad note. NAS/Files-provider imports and exports, accessibility,
sound availability and module playback remain separate checks. Simulator tests
use synthetic files only; private library checks must stay outside CI and commits.
