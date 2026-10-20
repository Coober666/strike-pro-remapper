# Strike Remapper for iPhone and iPad

One native app for offline setlist performance and kit-copy editing, evolving from Strike Companion. It reads the same version-1
JSON exported by Strike Remapper’s Setlist Builder. Requires iOS/iPadOS 17 or later.

Import an export from **Files**, or use **Open in Strike Remapper** from another
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

The welcome screen offers **Edit a kit** and **Import setlist**. Existing Companion
installs update in place: the bundle identifier, document types and private
`StrikeCompanion/session-v1.json` snapshot location remain unchanged. Files displays
the app’s shared Documents folder as **Strike Remapper**. Internal Xcode target,
scheme and executable names remain unchanged for build compatibility.

## Kit-copy editor (0.5)

Choose **Kit editor** in the toolbar, then **Open kit** to select a `.skt` from
Files. Open In also recognizes `.skt`. **Try synthetic kit** needs no personal
files. Wide iPad windows show the zone list beside its details; narrow windows and
iPhone use a list and detail screen. Tap a setting, enter a value, and choose
**Apply**. **Cancel** leaves the open copy unchanged. The original file is never
written, and file coordination never asks another open app to save it. Unknown stored values remain explicit until you deliberately change them.
Numeric settings show a large **Type a value** field: first focus selects its whole
number so typing replaces it immediately. You can also use **Clear value** to
replace it. **Quick adjustment** provides a whole-number
slider; **Fine adjustment (±1)** keeps precise one-step buttons available. These
controls change the pending value only; Apply is still required. Unsupported typed
values stay visible with Apply disabled rather than silently changing to a limit.

Both layers offer level, signed pan, decay, pitch/fine, filter cutoff/enable and
loop. Expand **Velocity response** for the four velocity modulation settings and
velocity bounds; Layer B maximum is displayed without editing. Zone settings offer
MIDI channel/note, Reverb/FX1/FX2 sends, EQ/compressor enable, priority, mute group,
Note Off, gate time and Mono/Poly playback. MIDI settings only change stored bytes;
no MIDI messages are sent. Kit-level FX and reserved offsets remain untouched.

**Change assignment** chooses a reference already in this kit, or Unassigned.
References never open instruments/samples or scan cards. A displayed reference
does not prove that sound exists. There is no sound library or audio playback.

The **Edit actions (…)** menu offers **Undo**, **Redo** (20 actions) and
**Export new copy…**. Export asks for a Files **folder**, then creates a unique
`Kit-edit-xxxxxxxx.skt` file there. The 21-character ASCII name fits the documented
module filename bound. Existing items are never replaced, including symbolic links.
For a local destination, choose **Browse → On My iPhone/iPad → Strike Remapper**
in Files, then **Open**. A **Kit Copies** subfolder is also prepared for organization.
The app exposes only its Documents folder;
setlist snapshots stay in private Application Support.
The app flushes and reads back the copy, validates its format and compares its bytes
before reporting success. Open that exported file again to inspect or continue editing
it. Export keeps your current edits and undo history. Cloud synchronization and
module playback are not established by this local byte check.

**Done** returns to the same setlist/song and retains kit edits while the app stays
open. Replacing an edited kit requires **Discard edits and open kit** after the new
file has validated. Keep editing, failed imports and cancelled pickers retain the
current kit/history. The confirmation also appears when an external kit finishes
loading before the editor reopens. Kit edits do **not** persist after process termination: export
before closing the app. A failed export keeps edits open and asks you to check the
destination before retrying. Handled partial writes are removed when their identity
still matches this attempt; process interruption can leave an incomplete copy.

The Foundation-only shared parser/writer bounds files to 4 MiB, KIT headers to
44–4096 bytes, 128 pad zones of 62–4096 bytes, and 4096 printable ASCII references
of up to 240 bytes. Chunk lengths, exact string bytes, header, reserved bytes and
opaque tail survive no-op round trips and edits. Unknown zones, duplicate identifiers
and ambiguous empty string-table slots can be inspected/copied, with editing disabled.
No source URL or bookmark is retained for saving. Setlist persistence is independent.

`tools/test_kit_inspector_format.py` and `tools/test_kit_editing.py` own committed
synthetic fixtures; `--write` intentionally regenerates them. The editing oracle
uses the Python editor's confirmed parameter map and binary writer. Swift tests
compare exact bytes for every supported field, bounds, assignments, undo/redo,
unknown data, rejected edits, collisions/partial failures and exported-copy reopen.
UI tests cover explicit edits, both layers, signed pan, undo/redo, retention after
Done, replacement protection, export-folder cancellation and a complete Files export/reopen. Simulator evidence
is separate from physical Files-provider, iPad, accessibility and module acceptance.

## Native editor workspace (0.6)

Switch **Zones → Drum map** to select pads in a standard drum arrangement. It shows
only pads present in the open kit. Swipe across the map in narrow windows; wide
iPads keep the selected pad’s inspector alongside it. On iPhone, selecting a pad
opens its detail screen. Buttons above the layer controls switch between that
pad’s head/rim or bow/edge/bell zones. The **Zones** list remains available for all
zones, including unknown identifiers. At accessibility text sizes, the workspace uses the complete Zones list automatically;
selection is retained. Widening an iPad window returns a compact detail screen to
the side-by-side inspector. The arrangement is a selection aid, not a
record of your physical rack, and selection never changes kit bytes or sends MIDI.

The full native editor is being developed toward direct iPad-to-Strike operation.
Native MIDI input and direct module storage are separate acceptance gates; neither
is provided by the drum map. See [the implementation plan](../../docs/NATIVE_STRIKE_EDITOR_PLAN.md).

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
Tests default to a three-minute execution allowance; the three Files-provider tests
allow five minutes for a cold provider. Every test is capped at five minutes so
a stalled UI test fails before the overall CI job expires.
Ordinary logs, screenshots and test results are retained; verbose OS sysdiagnose
capture is disabled because it can exhaust the job after an automation timeout.
Files readiness checks read enabled/frame attributes from one throwing snapshot;
a control replaced during folder restoration remains subject to the bounded wait.
The helper waits for each simulator to finish booting before testing. It shuts
down simulators it needed to start between runs, including on failure, and
preserves any simulator that was already booted when the helper started.
Use `--device <simulator-UUID>` (repeatable) to select specific installed devices.
The helper rejects input changes during a run and never downloads runtimes or configures signing.
Generated-directory exclusions apply inside the native input folders; worktrees under
a parent `.build` directory still receive complete source hashes. To list devices:

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
the attended iPhone check. CI runs each Xcode 16.4/27.1 and iPhone/iPad combination
as a separate job, with a 35-minute budget per device including cold startup.
Every job selects its device from the helper's compatible installed runtime pair;
per-test limits, full model/UI coverage and artifact receipts remain unchanged. Xcode 16/26's
file-URL automation drops the document or times out, so only the two document-handoff UI tests
explicitly skip on their older compilers; Xcode 27 must execute it. The modern
job uses GitHub's `xcode-27` preview runner with the installed Xcode 27.1
selected explicitly, matching local verification instead of the floating default.
GitHub's [installed software inventory](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
lists this toolchain. Existing test limits, assertions and failure artifacts remain;
the pin aligns environments and does not itself establish a fix for the observed
Xcode 27.0 launch/Files accessibility failures.
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
