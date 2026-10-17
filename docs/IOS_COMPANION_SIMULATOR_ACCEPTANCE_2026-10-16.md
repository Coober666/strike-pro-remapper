# iPhone/iPad companion simulator checks — October 16, 2026

Implemented on `codex/ios-ipad-companion`, based on PR #72 head
`41abe66586774b41b15547ca0145f774c5c69ae7`. The shared Swift package and Mac app
source remain unchanged. The mobile app consumes the existing local package and
the same synthetic demo/version-1 validation cases.

Local environment: Apple Silicon Mac, Xcode 27.1 (27A9275), Swift 6.4, installed
iOS 27.0 simulators. The project declares iOS/iPadOS 17 minimum compatibility;
older runtime behavior was not exercised.

| Simulator | Checks | Result |
| --- | --- | --- |
| iPhone 17e | Four unit tests and four UI tests | Passed |
| iPad mini (A17 Pro) | Four unit tests and four UI tests | Passed |
| iPad Pro 11-inch (M5) | Sidebar/search/performance and adaptive layout/scroll UI tests | Passed |

Each unit run includes all 35 shared Python/Swift format cases, bounded imports,
source-byte preservation, invalid/missing/directory/oversized/non-file URL
rejection, successful replacement, selection bounds, original-order navigation,
empty sets, and reading-pane reset identity when reopening the same filename.
UI checks cover the fictional demo, search in song notes, original-order Next,
end bounds, Files picker cancellation, Open In valid/invalid files, extra-large
notes, performance view, rotation, sidebar visibility, and scroll reset.

`XCUIApplication.open` is a launch operation and can create a fresh process.
Those tests establish Open In acceptance/rejection; the model tests establish
failed-import retention within the current app session. No persistence across
cold launches is claimed. Error presentation uses local SwiftUI alert state.

The existing Python format and Mac build helper tests also passed (six tests).
`git diff --check` passed. A new iOS simulator CI job is included; no remote CI
result or published release is claimed by this local validation.

## Local evidence

The ignored `.build/ios-validation-final/` directory contains `test-receipt.json`,
both simulator logs and `.xcresult` bundles, the simulator app in
`DerivedData/Build/Products/Debug-iphonesimulator/Strike Companion.app`, and
`iphone-preview.png` / `ipad-preview.png`. The receipt records the base revision,
exact companion/helper file hashes and successful exit codes, and verifies that
inputs stayed unchanged during testing. Final file hashes matched the receipt.
Additional wide-iPad evidence is in `.build/ios-wide-ipad.log` and
`.build/ios-wide-ipad.xcresult`. Portrait and landscape screenshots were visually
reviewed, including the wide sidebar and extra-large performance notes. Test
screenshots contain only fictional bundled data.

Reproduce the full suite with a new output directory:

```sh
python3 tools/build_ios_companion.py --output .build/ios-validation-new
```

## Remaining attended checks

Subsequent [October 17 iPhone checks](IOS_COMPANION_IPHONE_ACCEPTANCE_2026-10-17.md)
record development installation, AirDrop/Open In import, safe rejection,
navigation, extra-large notes and rotation on hardware. The list below records
what remained unverified at the end of this simulator run.

Physical-device installation/signing, actual Files providers/iCloud/AirDrop,
VoiceOver, distance reading, and real-device backgrounding remain unverified.
Device setup follows simulator validation and requires owner actions one at a
time. The app remains an offline, read-only reference viewer; it never verifies
kit availability, loads sounds, controls the module, or sends MIDI. Imported
content and display preferences are held for the current app session only.

## October 17 CI follow-up

The first PR #75 CI run used Xcode 16.4 / iOS 18.5 and failed two iPhone UI tests.
Its diagnostics show `XCUIApplication.open(file)` relaunching the app without
delivering the file URL, and the framed image Menu label exposing nested buttons
whose outer accessibility element could not be tapped. Unit tests and the other
UI tests passed; the helper stopped before the iPad run.

The import UI test now uses `XCUIDevice.shared.system.open` to route the document
through the OS and additionally checks selected-song retention after rejection.
Reading options uses SwiftUI's standard labelled Menu with an icon-only display.
Both affected tests passed locally on the installed iPhone 17e / iOS 27.0
simulator with Xcode 27.1. Logs and results are retained in
`.build/ci-pr75-fix-validation/targeted-iphone-2.log` and its `.xcresult` bundle.
The initial targeted invocation selected zero tests; only the corrected run's
two executed tests count as validation. Remote results for the fix are recorded
by the PR checks, separately from these local results.
