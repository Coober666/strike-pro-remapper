# Native UI-test and simulator harness notes

Moved verbatim from AGENTS.md so the agent brief stays focused. These rules apply to
`native/StrikeCompanioniOS/UITests`, the `mac-companion.yml` workflow and
`tools/build_ios_companion.py`. They describe hosted-simulator and XCTest behaviour,
not app features; physical-device acceptance lives in the dated acceptance documents.

## Setlist companion, CI matrix and simulator lifecycle

Open In UI tests target the viewer explicitly with `XCUIApplication.open` on
Xcode 27; default-app file dispatch can time out in hosted simulators. This is a
launch operation, so active-session retention is covered by model tests and the
attended iPhone check. Xcode 16's app URL launch drops the file URL; system URL
opening times out on Xcode 16/26. Only the two document-handoff UI tests explicitly skip on their
older compilers. The Xcode 27 CI matrix
job must execute it; model import contracts and other UI tests run on both.
The modern job uses GitHub's `xcode-27` preview image with an explicit
/Applications/Xcode_27.1.app developer directory, matching local Xcode 27.1
(27A9275) verification. The image's floating default selected 27.0 (27A266a)
and produced repeated launch/Files accessibility failures despite a passing push run.
Pinning aligns the environments; do not claim it fixes those failures until CI passes.
The legacy job pins Xcode 16.4. Keep all tests, limits and failure evidence.
Each Xcode version has separate iPhone and iPad CI jobs, selecting one member of
the helper's compatible installed runtime pair with --device. Each retains the
35-minute job limit and existing per-test limits, source hashes, lifecycle cleanup
and uniquely named device artifacts. Cold preview-runtime startup plus both full
suites can exceed a combined job budget even while every completed test passes.
Default simulator selection uses the newest installed iPhone/iPad runtime pair
supported by the selected SDK; tests in `tools/test_ios_build.py` never access devices.
Keep import/rejection and source-byte UI assertions, plus selected-song retention
model assertions. Reading options
uses the standard labelled SwiftUI Menu with an icon-only presentation, avoiding
the nested accessibility buttons produced by a framed image label on iOS 18.
The search UI workflow enters its query and submits Return as separate keyboard
events before selection, so a wide-iPad keyboard does not retain animation-idle
waits during later toolbar actions. Each test has
a 180-second execution allowance, keeping stalled UI diagnostics within the CI job.
Before each device run, wait for `simctl bootstatus -b`. Shut down only devices
that were not already booted when the helper started, including after failure;
never shut down a preexisting user simulator. Lifecycle tests mock device access.
Receipt exclusions for .build/.swiftpm/xcuserdata apply only below each native input
folder, so a worktree inside a parent .build still hashes all source files.
Keep ordinary failure logs, screenshots and xcresult bundles, but omit verbose
OS sysdiagnose capture, which can outlast the CI job after an automation failure.
On failure the builder prints the log tail plus every failing-test diagnostic line
(failure_summary in tools/build_ios_companion.py), so the job log names each failed
assertion or timeout even when it occurred far from the end of the xcodebuild log.
Files-picker UI checks allow 90 seconds for the OS service's first accessibility tree, then
require dismissal, Import re-enablement and selected-song retention after Cancel.

## Kit editing and Files-provider workflows

Replacement helpers use the visible Clear action and assert the resulting text;
they must not assume where a tap places the caret. A separate check verifies that
first-focus typing replaces the selected number without Clear. Replacement helpers
submit keyboard Done before toolbar actions: the iPad keyboard repositions the sheet
before the remote accessibility frame catches up. Done must leave Apply explicit.
Files may restore its last folder: UI tests recognize the app destination before
navigating the sidebar. Reopen the exported file using its image element in icon
view or the cell in list view, letting XCTest reveal it. Avoid normalized coordinate
taps through the hosted Files service. Repeated simulator runs retain their exported
copies: scroll Files’ virtualized File View grid within a bounded loop to locate the
exact newly exported filename; never repeat the write or delete earlier files.
Older SwiftUI exposes list and detail status labels together; select an explicit
match when asserting the shared model’s Original imported status.
Scroll test helpers
wait for the edit sheet to disappear and reverse direction when the target is above
the viewport. Check an element's frame is inside the unobscured scroll viewport before
asking isHittable: hosted accessibility can fail the test for offscreen activation
points rather than returning false. Keep the final visibility assertion. The three Files-provider
UI tests have a 300-second allowance for cold hosted providers; other tests default
to 180 seconds and the builder caps every test at 300 seconds. Do not skip assertions
or retry file mutations to accommodate a slow provider.
For cancellation, prefer the real Cancel button in the running Files service's
accessibility tree (com.apple.DocumentManagerUICore.Service), then the host's actual
Button. Xcode 27 can expose the close control only as a misleading Other proxy in
the host while the service retains its correct Button/frame. Require a valid frame
inside the screen and hittability before choosing a control. If Cancel is hidden,
navigate only through the actual Recents TabBar button, then wait for actionable
Cancel. Never use generic Recents/Cancel Other proxies or More as readiness evidence:
More opens sorting options and can leave a covered Cancel with an invalid hit point.
UI test relaunches send Home to a foreground app, terminate it if still running,
and require notRunning before launch or document handoff. Hosted Files can report
stale foreground/background state while Home is visibly onscreen, so the required
condition is the final stopped process, not an intermediate background flag.
This keeps implicit foreground termination out of launch() after repeated hosted
XCTest PID acknowledgement failures. Cold-launch restoration requires a stopped process before launch;
its song/reading assertions and document source-byte checks remain unchanged.
Read enabled/frame attributes from one throwing snapshot, treating a disappearing
Files match as not ready. Separate exists/isEnabled/frame queries can hard-fail if
the restored folder replaces its tab bar between them. Keep the hittability check.
Folder export also waits for an enabled, hittable native Open button after the
destination title appears: Browse can publish the title while Open is still disabled.
Submit Open once, retaining the export-status and exact reopened-value assertions.
Waits for elements drawn by the Files service during export/reopen navigation (On My
iPhone/iPad, the app folder, the File View grid and the exported cell) use 30 seconds,
matching the picker-ready wait. A hosted 16.4 iPhone run timed out at the former 10s
folder wait while the same commit passed elsewhere (#85). App-owned waits are unchanged.
Assert the editor is usable again.
After cancellation, wait for the named dirty-replacement alert before tapping Discard,
then require its dismissal before checking the new kit. Older SwiftUI can expose
the action during presentation before its tap target has settled; never retry Discard.

## Hosted Xcode 27.1 workarounds

The largest accessibility-text UI check waits up to 10 seconds for Done to become
enabled/hittable after compact zone navigation, then taps once and verifies the
editor dismisses back to the welcome screen. The detail title appears before the
navigation toolbar finishes transitioning on hosted Xcode 27.1 iPhones; checking
isHittable immediately can fail while Done remains visible in the test video.
Retain the final action and dismissal assertions; do not retry the tap.

Hosted Xcode 27.1 can report an old app PID while the previous test's process is
already exiting. After Home, wait up to five seconds for notRunning before deciding
to terminate once; retain the final stopped-state assertion and never retry a failed
termination or launch over a running process. After export-folder cancellation,
wait up to 60 seconds for the actual kit-actions button to exist with an enabled,
onscreen snapshot and hittability. Guard existence before forced AX lookups: hosted
Files dismissal can briefly publish no toolbar, and forced finds consume the wait
budget in internal retries. Keep edited-value retention and actual subsequent
replacement/menu assertions. No file-write retry or weakened mutation check.

The modern hosted SDK can still emit the exact "Failed to terminate <bundle>:<pid>:
Failed to terminate <bundle>:0" acknowledgement error after the single terminate.
Only on compiler >=6.3, scope a non-strict XCTExpectFailure to that ONE call and
an anchored exact matcher for this app/positive old PID/PID zero. Never match other
errors or any test assertion. The notRunning assertion is outside the scope and
must pass before launch; cold-launch restoration and source-byte assertions still
execute normally. The matcher has negative coverage for unrelated failures, wrong
apps, incomplete messages and PID-zero origins. Keep the expected SDK diagnostic
visible in xcresult; do not retry termination, skip tests or weaken final process
and restored-state checks. This is a test-harness workaround, not an app fix.

Whole-tree zone UI lookups use app.kitZone(id), an Any-type query with the exact predicate
identifier == <kit-zone-id>. Do not use matching(identifier:) for the whole tree:
that expands XCElementSnapshot.identifiers through label/value and the hosted
Xcode 27.1 iPad spindump showed the app main thread blocked in XCTest value-fetch
logging to stderr. Retain Any for older SwiftUI's element-type differences, but
query only the actual accessibilityIdentifier. Selection, layer/source-byte,
value and return/dismissal assertions remain; no query-timeout suppression.

The valid/invalid setlist Open In UI workflow uses the existing 300-second ceiling:
it performs three cold launches and hosted Xcode 27.1 spent over 100 seconds setting
up the final document launch before successfully presenting its rejection alert.
Keep the alert dismissal, restored imported-song and unchanged-source assertions.
Other non-provider tests retain their 180-second default; do not retry handoffs.


## October 22 diagnosis: delayed typing and Files extension activation

For #88, run 39697106912's Xcode 16.4 iPad recording showed `Snare`
with the caret and keyboard still present at test time 32 seconds, after the
assertion had read `Sn` at 31.32 seconds. The single synthesized event contains
all five characters. This establishes delayed delivery/observation in that run;
it does not establish lost focus or a production field defect. After one
`typeText("Snare")`, wait at most five seconds for that exact value, then retain
the strict equality assertion and separate Return/explicit Apply actions. Never
resend text, retry taps or accept a prefix. Keep before/after state and screenshot
attachments, including public snapshot focus/attributes and keyboard count/frame.
`hasFocus` is UI focus; do not describe it as a guaranteed keyboard-focus flag.
See docs/NATIVE_UI_DIAGNOSIS_2026-10-22.md for the source evidence and limits.

For #85, run 39677340058 attempt 2's iPhone failure was in XCTest's attempt to
activate `com.apple.DocumentManagerUICore.Service` when tapping its real Cancel
button. The running Files extension is not a launchable app; FBSApplicationLibrary
returned nil. In `cancelFilesPicker` only, deliver the single Cancel/Recents tap
through the foreground host's coordinate space at the freshly validated real
button's center. Require its enabled snapshot, full onscreen frame and hittability;
never guess a position or use generic Other proxies. This specific exception
avoids extension activation and does not change the Files reopening rule above.
Keep picker dismissal, enabled Import and selected-song/edited-value assertions.
No retry or broader launch-error suppression is justified by this failure.
