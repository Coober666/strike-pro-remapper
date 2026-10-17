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
Builder and import again. This version holds the document and preferences in
memory for this app session; reopen your export after a cold launch. It does not
save imported documents, bookmarks, changes or personal content in preferences.

Kit references are displayed as text. A setlist does not include kits or sounds.
The companion does not check kit availability, follow kit paths, access cards,
connect to the editor, or send MIDI.

## Simulator build and tests

Requires full Xcode with an installed iOS simulator runtime. Open
`StrikeCompanion.xcodeproj`, choose scheme **StrikeCompanion** and an iPhone or iPad
simulator, and Run. The project references `../StrikeCompanion` directly; keep the
repository folder layout intact. No signing team is needed in a simulator.

From the repository root:

```sh
python3 tools/build_ios_companion.py --output .build/ios-validation
```

The output directory must be new. This selects one installed iPhone and iPad,
builds and runs XCTest/XCUITest sequentially, and retains logs, `.xcresult` bundles
with screenshot attachments, and a receipt containing input SHA-256 hashes.
Use `--device <simulator-UUID>` (repeatable) to select specific installed devices.
The helper rejects input changes during a run and never downloads runtimes or configures signing. To list devices:

```sh
xcrun simctl list devices available
```

Tests use the shared Python/Swift format cases and bundled fictional demo. They
cover bounded file imports, successful replacement, failed-import preservation,
empty lists, original-order navigation, search, note size, performance view,
rotation, scroll reset, Open In imports/rejections, and Files cancellation. Open In
UI automation is a launch operation; active-session failed-import retention is
covered against the production model. Simulator evidence does not establish physical
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

The existing Mac target, build artifacts, and remote build workflow remain separate.
