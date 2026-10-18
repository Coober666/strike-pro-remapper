# Strike Companion for iPhone and iPad

A native, offline, read-only performance sheet for the same version-1 JSON exported
by Strike Remapper’s Setlist Builder. Requires iOS/iPadOS 17 or later.

Import an export from **Files**, or use **Open in Strike Companion** from another
app. The entire document is validated by the existing Foundation-only
`StrikeSetlists` local Swift package. Files are bounded to 1 MiB and 128 songs;
invalid imports keep the current setlist, selected song and search. The source
file is never modified. No external Swift packages are downloaded.

On iPhone, the current song fills the screen in either orientation; **Songs** opens a searchable running
order. On regular-width iPad windows at least 760 points wide, the list stays beside the sheet.
Narrow windows use the iPhone layout. **Reading options** offers Performance view
and three note sizes, with Dynamic Type scaling. Performance view hides the iPad
list. Previous/Next always follows the original order, even with a search active,
and stops at either end. Each song starts at the top of the sheet. Hardware
keyboard shortcuts: Command-O to import, Command-Left/Right to change songs.

Performance notes and show notes come from the export. Update them in Setlist
Builder and import again. The app keeps one local copy in its private Application Support folder and restores
the setlist, selected song, notes size and Performance view after relaunch. Search
starts empty. The source file is never changed or reopened automatically, so later
source edits need another import. No source URLs or bookmarks are saved. Use
**Reading options → Close setlist** to remove the saved document; reading preferences
remain. A failed save shows a Retry save warning and keeps the current state in memory.
A corrupt or unsupported saved session opens the welcome screen with a warning.

Kit references are displayed as text. A setlist does not include kits or sounds.
The companion does not check kit availability, follow kit paths, access cards,
connect to the editor, or send MIDI.

## Read-only kit inspector (0.4)

Choose **Kit inspector** in the toolbar, then **Open kit** to select a `.skt` from
Files. Open In also recognizes `.skt` files. **Try synthetic kit** needs no personal
files. Wide iPad windows show the pad-zone list beside its details; narrow windows
and iPhone use a list and detail screen. Layer A/B references, level, signed pan,
pitch/fine, decay, velocity range, filter/loop and selected zone/MIDI settings are
read from known offsets. Unknown enum values remain labelled with their raw number.
Unassigned and unresolved string indices are explicit. No instrument/sample path
is followed, so a displayed reference does not prove that sound is available.

The Foundation-only parser lives beside the shared setlist core. It bounds input
to 4 MiB, the KIT header to 44–4096 bytes, 128 pad zones of 62–4096 bytes, and 4096
printable ASCII references of up to 240 bytes. Missing/truncated blocks and
unterminated/unsupported strings are rejected before replacing the current kit.
Unknown pad IDs and opaque trailing bytes are retained. All imported bytes are
kept unchanged in memory. This is an inspector, with no writer/export/editing,
playback, sound library, host connection or deployment. No kit is saved across
launches. Closing the inspector returns to the same setlist and selected song.

`tools/test_kit_inspector_format.py` checks committed synthetic demo/parity cases
against Python; use `--write` only when intentionally regenerating them. Swift
contracts check the same cases, all truncation boundaries, bounds, signed values,
unknown zones, unresolved references and unchanged source bytes. These are format
and simulator checks, not physical file-provider or module acceptance.

## Simulator build and tests

Requires full Xcode with an installed iOS simulator runtime. Open
`StrikeCompanion.xcodeproj`, choose scheme **StrikeCompanion** and an iPhone or iPad
simulator, and Run. The project references `../StrikeCompanion` directly; keep the
repository folder layout intact. No signing team is needed in a simulator.

From the repository root:

```sh
python3 tools/build_ios_companion.py --output .build/ios-validation
```

The output directory must be new. This selects one installed iPhone and iPad from
the newest complete runtime pair supported by the selected Xcode simulator SDK,
builds and runs XCTest/XCUITest sequentially, and retains logs, `.xcresult` bundles
with screenshot attachments, and a receipt containing input SHA-256 hashes.
Each test has a three-minute execution allowance so a stalled UI test fails with
diagnostics before the overall CI job expires.
Ordinary logs, screenshots and test results are retained; verbose OS sysdiagnose
capture is disabled because it can exhaust the job after an automation timeout.
The helper waits for each simulator to finish booting before testing. It shuts
down simulators it needed to start between runs, including on failure, and
preserves any simulator that was already booted when the helper started.
Use `--device <simulator-UUID>` (repeatable) to select specific installed devices.
The helper rejects input changes during a run and never downloads runtimes or configures signing. To list devices:

```sh
xcrun simctl list devices available
```

Tests use the shared Python/Swift format cases and bundled fictional demo. They
cover bounded file imports, successful replacement, failed-import preservation,
empty lists, original-order navigation, search, note size, performance view,
rotation, scroll reset, Open In imports/rejections, and Files cancellation. Open In
UI tests explicitly target Strike Companion using Xcode 27's app-launch API;
default-app file dispatch can time out on hosted simulators. Because the API
relaunches the app, active-session import retention is covered by model tests and
the attended iPhone check. CI runs Xcode 16.4 and 27 separately. The job allows 35 minutes for both devices,
including cold boots and the expanded UI suite. Xcode 16/26's
file-URL automation drops the document or times out, so only the two document-handoff UI tests
explicitly skip on their older compilers; Xcode 27 must execute it. The modern
job uses GitHub's `xcode-27` preview runner and its bundled toolchain/runtime.
All model import
contracts and other UI tests run on both. Simulator evidence does not establish physical
Files/iCloud/AirDrop, signing, VoiceOver, or distance-reading acceptance.

## Physical device setup, after simulator validation

Keep this attended and do one step at a time. First connect an unlocked iPhone or
iPad to the Mac with a data cable. Then follow the device’s Trust prompt, choose it
in Xcode, and resolve the signing team under Signing & Capabilities as needed.
Do not place a personal team ID in the shared project or commit Xcode user state.
Developer Mode may need enabling on the device. Xcode’s Run installs a development
build; this is not an App Store/TestFlight release or a signed distribution package.
After launch, check demo navigation, import a synthetic export through Files, reject
an invalid export, and check portrait, landscape, large text and VoiceOver before
using a personal show. Developer account and device prompts require the owner.

[Initial iPhone acceptance, October 17](../../docs/IOS_COMPANION_IPHONE_ACCEPTANCE_2026-10-17.md)
records a successful signed development install, launch and owner-confirmed demo
Previous/Next plus a synthetic AirDrop/Open In import on iPhone 17 / iOS 26.6.2.
The owner also confirmed that invalid imports preserve the selected song and
notes, and that extra-large notes remain readable in portrait and landscape with
navigation visible.
Files-picker imports and broader device acceptance remain pending.
The inspected profile expires October 24, 2026 and
will require a fresh development build/profile after expiry.

[Companion 0.4 iPhone acceptance, October 18](../../docs/IOS_COMPANION_04_IPHONE_ACCEPTANCE_2026-10-18.md)
records owner-confirmed cold-launch restoration of the demo's selected song and
extra-large notes, both synthetic kit layers, return to the same song, external
`.skt` AirDrop/Open In, and invalid-kit rejection retaining Snare Head details.
Successful in-app Files/provider imports, imported-setlist persistence, physical
iPad and broader accessibility checks remain separate.

The existing Mac target, build artifacts, and remote build workflow remain separate.
