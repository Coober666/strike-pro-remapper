# Native simulator failure diagnosis — October 22, 2026

Scope: downloaded synthetic GitHub CI logs, xcresults and test recordings; focused
local simulator checks. No physical device, personal documents or real MIDI input.
This is test-harness evidence, not device, latency or module acceptance.

## MIDI Learn (#88)

Source: [run 39697106912, Xcode 16.4 iPad job](https://github.com/Coober666/strike-pro-remapper/actions/runs/39697106912/job/119557050802),
commit `6fa56fc0ca245b4f04f09dd634c54e105ed87c24`, artifact `12391714496`.
`NativeMIDIUITests/testExplicitInputCaptureLearnStopAndRetainedTake()` failed its
exact `Snare` assertion with `Sn` after one `typeText("Snare")`.

The full xcresult attachments add information absent from the original issue:

- Log: text synthesis started at 31.01s; typeText returned at 31.29s; the value
  query started at 31.32s. No second text event was sent.
- The synthesized event stores `Snare`, typing speed 60 and duration 1.1s.
- Screen recording at approximately 31s shows `S` and a caret; at approximately
  32s it shows the full `Snare` and caret. The keyboard remains visible and the
  synthetic recording's message count continues increasing.

The observed prefix was temporary in this run. Delayed keyboard delivery or
accessibility observation is supported; permanent character loss or an app focus
bug is not established. The older run-110 focus failure remains distinct evidence.
No production field or recording behavior changed for this diagnosis.

The test now waits up to five seconds for the exact expected value after its one
text event, then retains the strict equality check, separate Return, explicit
Apply and learned-name/retained-take assertions. Incomplete delivery still fails.
Before/after attachments retain field value, public UI-focus/snapshot attributes,
keyboard count/frame, app accessibility tree and screenshot. No private keyboard
focus property is assumed, and `hasFocus` is not proof of keyboard focus.

Local retained evidence under `.build/issue88-all-attachments/`:

| Evidence | SHA-256 |
| --- | --- |
| `7B555AD7-0675-474D-AD65-AA10FE3EC470.mp4` | `2f49490eefb22e298ba75dede0a17511f3dba93567160285bf639c4755156f9c` |
| `frame-31.png` | `59c634ce6613909c13d8c01ad4e383cc8f62c91d0a4a2c7771d0c02505f70578` |
| `frame-32.png` | `9b529df7c33bc95c4d71675ff5ddf87e5dad1fcf86a95a7961800c43e441dd49` |

These extracted frames and CI bundles are local evidence, not shipped assets.

## Files cancellation and remaining hosted failures (#85)

All six artifact IDs listed in #85 were downloaded and their full logs inspected.
The failures have different causes; they do not support an orientation fix or a
blanket increase to every timeout.

| Artifact | Recorded failure |
| --- | --- |
| `12383204089` | First `app.launch()` in adaptive-layout test timed out via Xcode; teardown reached 347s. |
| `12383908287` | First launch in cold-restoration test reported no process ID after the 180s ceiling. |
| `12311876886` | First launch in cold-restoration test reported no process ID after about 172s. |
| `12309515705` | Cold-restoration assertions completed around 50s, but teardown inflated elapsed time to 231s past the 180s allowance. |
| `12307183172` | Three-launch Open In test reached final rejection handling around 180s; current source already grants this test 300s. |
| `12385838026` | Tapping real Files Cancel tried to activate the Files extension; FBSApplicationLibrary returned nil. |

For the last failure, [run 39677340058 attempt 2, Xcode 27.1 iPhone](https://github.com/Coober666/strike-pro-remapper/actions/runs/39677340058/job/119514599625)
shows the real Cancel button passing readiness, followed by `Open`/`Activate
com.apple.DocumentManagerUICore.Service` and `Failed to launch` at helper line 305.
The extension was already running but is not a launchable application.

`cancelFilesPicker` now delivers one tap through the foreground host at the
fresh snapshot center of the actual Cancel or Recents button. Enabled state,
full onscreen frame and hittability are required immediately before that tap.
No generic proxy or fixed position is accepted. Picker dismissal, Import enabled,
selected-song and edited-value assertions remain. No launch/termination diagnostic
is suppressed. General Files reopening continues to use actual elements.

The first-launch/PID and prolonged-teardown failures remain unresolved. Passing a
focused local run or re-running hosted CI cannot establish that these are fixed.
Xcode 16.4 and its iPad runtime are not installed on this Mac, so the original
MIDI Learn environment requires the hosted compatibility job.

## Local validation

Xcode 27.1 (27A9275), installed iOS 27.0 simulators:

| Device | Focused results |
| --- | --- |
| iPad Pro 13-inch (M5) | Both tests passed, 78.33 seconds. |
| iPhone 18 Pro | Both tests passed, 50.28 seconds. |

Each run executed `CompanionUITests/testFilePickerCancellationPreservesSong`
and `NativeMIDIUITests/testExplicitInputCaptureLearnStopAndRetainedTake` once,
with serial execution, 180-second default / 300-second maximum test allowances,
no verbose OS diagnostics and code signing disabled. This is four test executions,
not a full-suite or frequency claim. Both simulators began shut down, were booted
with `simctl bootstatus -b`, then shut down by the lifecycle helper.

Logs, xcresults, commands, Xcode identity and native-input SHA-256 hashes are retained
locally in `.build/native-focus-1/`; `receipt.json` records `inputs_unchanged: true`
for both runs. Inputs were base `0105c7fc2e18481d6eb0caba997c5f301850aa2e`
plus the two UI-test edits committed with this note. Before/after state and screen
attachments were exported and inspected: the successful name was `Snare`;
`hasFocus` was false even while the keyboard was present, reinforcing its stated
limitation. `python3 tools/test_ios_build.py` passed all eight contracts;
`git diff --check` passed.

At that initial local checkpoint, hosted Xcode 16.4 iPad validation was still
pending. Later run 39702644297 passed both Xcode 16.4 lanes for `f576f00`, including
the strict Learn-name workflow; its Xcode 27.1 iPad lane failed Files readiness as
documented below. The new snapshot-first candidate still requires hosted matrix
validation. These local passes do not resolve the first-launch/PID/teardown failures.


## Hosted readiness follow-up: run 39702644297

[#87's Xcode 27.1 iPad job](https://github.com/Coober666/strike-pro-remapper/actions/runs/39702644297/job/119575255695)
failed `testFilePickerCancellationPreservesSong` at the initial 90-second readiness
assertion, before `tapControl`. Artifact `12395717027` has archive SHA-256
`df797180b53fe3b209db4f82acd3cdd8135608279327a0313c17029be2f87718`.
Its receipt identifies source `f77ac678a9b043ef0b1f715485f745d18a4b695c`
(PR merge ref) and Xcode 27.1 (27A9275). The workflow branch head was `f576f00`.

Import was synthesized once at 21.91 seconds. Video at 24/50 seconds shows no
picker; 60/70/80 seconds shows a partial blank popover with an unfinished close
control; 90/113/146 seconds shows the complete Recents picker and X close. The
initial readiness checks began at 24.36 seconds. Two polling cycles consumed the
budget in blocking/retried Cancel/Recents `exists` queries; no candidate `Find`,
enabled/frame snapshot or hittability check completed before the failure.

The failure's host snapshots were requested at 123.29 and 146.51 seconds. That final
host tree (pid 9821) exposed a real Button labelled Cancel, with no logged identifier,
frame `(50,372,36,36)` under NavigationBar `DOCSidebarView`. It also exposed a misleading
Other labelled Cancel with a 1-point-wide frame. Recents was the selected sidebar
Cell `DOC.sidebar.item.Recents`; there was no Recents TabBar Button in that tree.
The recording alone does not prove when the real button became queryable through
AX. Per-poll service state and root provenance were not captured, so whether the
service state guard skipped its query is unknown. This failure does not test the
host-coordinate tap or post-cancellation assertions.

The follow-up changes cancellation discovery only: one throwing snapshot per queried
root, host first, followed by local traversal for real navigation-bar Cancel Buttons
or actual TabBar Recents Buttons. A running-service fallback is explicit and logged.
Exact label predicates retain identifier-less controls. A candidate must resolve to
a fresh actual live Button with enabled/full onscreen frame and hittability before
its single host-coordinate tap. Generic Other and sidebar Cell proxies remain
rejected. The selected control is retained across the readiness result, avoiding an
extra discovery pass. Poll diagnostics report root/state/candidate count/choice;
failures keep a screenshot without fetching an unbounded debug tree. Both existing
90-second waits, per-test ceilings, dismissal and retained-song/edit assertions stay.
Global export Open handling and production app behavior are unchanged.

This is a candidate correction, not a proven cause or fix. A #69 hosted iPad job
passed with the same native tree, so that pass and the #87 failure must both remain
visible. Repeated-query overhead is plausible; the artifact cannot isolate it from
late OS-provider/AX readiness. The candidate received root and independent review,
including a guard that host bounds themselves must be nonempty, non-null and finite.

Exactly one focused `testFilePickerCancellationPreservesSong` execution passed on
each installed iPad/iPhone simulator with Xcode 27.1 (27A9275), iOS 27.0. The iPad
completed in 17.30 seconds; the iPhone completed in 17.30 seconds. Both retained the
90-second readiness waits, 180/300-second allowances, no verbose OS diagnostics,
serial execution and no signing. Compact logs explicitly identify each queried
root/state/candidate count and selected control. On iPad the host had no real
candidate; the second poll selected the running service's real Cancel Button.
On iPhone, the service's actual TabBar Recents Button was selected on poll 2;
poll 3 then selected the host's real navigation-bar Cancel Button. Both paths
required dismissal, enabled Import and selected-song retention after the one-shot
actions.

Logs, xcresults, commands and native-input SHA-256 hashes are retained locally at
`/private/tmp/strike-files-snapshot-candidate-20261022/`. Its receipt records base
`f576f007c8d381926f45f567cce0ebf9877121ed` plus the reviewed test-source edit,
`inputs_unchanged: true` for both runs, and no outer timeout. No source or docs were
edited while either runtime check executed. Both owned simulators were shut down.
`python3 tools/test_ios_build.py` passed all eight contracts; `git diff --check`
passed. This is focused new-source validation, not a full-matrix or slow-provider
reproduction claim; run 39702644297 remains failed and hosted validation is pending.

Downloaded bundle, recording and extracted frames are retained locally under
`/private/tmp/strike-hosted87-failure-39702644297/`; no devices were accessed to
inspect them and the failed run was not retried.

## Issue #85 lifecycle isolation follow-up

The remaining launch/PID and teardown evidence has a concrete lifecycle boundary:
all UI classes reset portrait before stopping the previous app, and leave their app
running for implicit XCTest teardown. Artifact `12309515705` ends its assertions at
50.39 seconds with the reading-options menu still open, then reaches 231.35 seconds
in teardown. Artifacts `12383204089`, `12383908287` and `12311876886` stall during
launch, before any app-owned UI assertion. These are not reasons to extend waits.

`NativeUITestCase` now registers one owned application per test, stops the previous
process before portrait setup, and explicitly stops its app before implicit teardown.
It asserts notRunning before restoring portrait. Cold relaunches reuse the same
private session, retaining the restoration/import checks. Failures still run cleanup;
pure matcher tests that never launch an app do not stop a process. The existing
exact stale-PID matcher is unchanged; no additional diagnostic is suppressed.

The build helper also separates the hosted model and UI bundles into serial
test-without-building sessions after build-for-testing. This removes their shared
test-session boundary, which was an unresolved variable in the earlier local
model-plus-export failure. Both entire targets remain selected. The scheme guard
refuses skipped/missing/new targets rather than silently losing coverage. Distinct
models/ui xcresults and phase commands/statuses survive in a version-2 receipt;
startup failures now retain a receipt too. Failed phases or changed inputs prevent
later sessions. The existing 180/300-second test and 35-minute CI ceilings remain.

One controlled current-source baseline at `0033c7e` (tracked files equal main
`23f1eb2`) ran all 34 model tests followed by cancellation, export/reopen and Learn
on the installed iPad. It passed without source changes. Its log/xcresult/receipt
are retained at `/private/tmp/strike-issue85-baseline-20261022/`. That pass does not
replace the earlier failed full run or establish that a lifecycle cause is proven.

Fourteen deterministic helper contracts cover phase failure propagation,
startup receipt/cleanup, source-drift interruption and refusal to omit test targets.
Build errors are included in the failure summary even when the final log lines
only name failed compiler commands.

The first follow-up at `6729ea8` exposed an isolation mistake: synchronous
tearDownWithError is nonisolated, producing warnings locally and compile errors
on hosted Xcode 16.4. Artifact `12400531925` retains that build failure and source
receipt; no model/UI phase ran there. A subsequent async override at `13f0e57`
compiled locally, but Xcode16.4 correctly rejected sending non-Sendable XCTestCase
through super.tearDown (artifact `12400947983`). Cleanup now uses XCTest's public
addTeardownBlock with an explicitly async main-actor closure capturing only the app
and test name. Superclass hooks remain unchanged; no executor assumptions,
unchecked Sendable or diagnostic suppression are used. Registration follows the
initial successful stop, so a setup termination failure cannot be retried in cleanup.

The local `6729ea8` iPad run passed the 34 models and the setlist UI class, then
the signed-value editing test exceeded its unchanged 180-second limit after typing
`-17`. Its thread samples show the app main thread idle and XCTest waiting for
animation quiescence; its screenshot shows keyboard language suggestions for the
numeric field. A temporary display-awake assertion did not release that wait.
An initial sandbox display query had no valid display handle and cannot establish
pre-intervention sleep state; do not attribute this failure to display sleep.
The run was interrupted after the recorded timeout because its synchronous
teardown source was already superseded; the receipt marks it incomplete with
unchanged inputs. Logs, xcresults, samples and screenshot remain at
`/private/tmp/strike-issue85-new-20261022/`. The iPhone phase did not start.

NumericValueField now opts out of autocorrection, spelling checks, capitalization
and smart dashes because its contents are literal signed integers. This retains
ordinary keyboard entry/Done/Apply and exact signed-value assertions; it does not
disable animations or XCTest idle waits. The keyboard configuration is a concrete
input correction, not proof that all historic animation stalls have one cause.
The `13f0e57` local run also hit the unchanged 180-second limit in running-order
search after Return; its valid display query confirms the display was awake during
the stall. Its screenshot, log, xcresults and incomplete unchanged-input receipt
remain at `/private/tmp/strike-issue85-13f0e57-20261022/`. This demonstrates that
lifecycle isolation and numeric keyboard traits alone do not resolve all of #85.
See issue #85 and its linked PR for subsequent exact-source validation results.
Do not describe a green rerun of unchanged source as a fix or claim all SDK failures
are eliminated from a single new-source pass.
