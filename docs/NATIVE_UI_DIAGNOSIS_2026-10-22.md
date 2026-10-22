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

Hosted Xcode 16.4 iPad validation remains required before closing #88. These local
passes do not resolve the first-launch/PID/teardown failures above.
