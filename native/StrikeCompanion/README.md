# Strike Companion for Mac

A native, read-only performance sheet for Strike Setlist Builder exports.
Open a setlist JSON, choose a song and keep its kit reference and notes in view.
The included demo uses fictional songs and kit references.

In Strike Remapper, open **Setlist Builder**, choose **Export**, and open the
resulting JSON in the companion. Use Previous/Next or Command-Left/Command-Right
to move through the original song order. Search filters the list without
reordering it. Command-O opens another setlist. A rejected file preserves the
current setlist and song selection; the viewer never saves changes to the file.

Version 0.2 adds **Performance view** (Command-Shift-F) to hide the song list,
and Standard/Large/Extra large note sizes. Show notes scale with song notes.
Search covers titles, kit references, output labels and song notes; clearing
search restores the full list. Previous/Next always follows the original order.
Malformed entries identify their song number in the error. Display preferences
last for the current app session; no document contents or access bookmarks are saved.

Setlist exports contain references and notes, not the kits themselves. The
companion does not check kit availability, load sounds, control the module,
discover cards, send MIDI, or connect to the editor. Open an updated export to
see changes made in the editor. This first version is a Mac app; an iOS/iPadOS
target and physical-device acceptance remain future work.

## Build on the Mac

Requires Apple Silicon, macOS 14+, Python 3.10+, and Apple Command Line Tools or
Xcode with a Swift 6 compiler. No external Swift packages are fetched.

```sh
python3 tools/build_macos_companion.py --output dist/mac-companion --revision "$(git rev-parse HEAD)"
```

The output directory must not exist. The build compiles/runs the document and
navigation contract executable, builds `Strike Companion.app`, ad-hoc signs and
verifies it, and writes a ZIP plus `build-receipt.json` with source revision,
compiler identity and SHA-256. This is a local development build, not a notarized
release. Ad-hoc signing does not establish a trusted developer identity.

Add `--render-preview` in a logged-in macOS graphical session to render only the
app's bundled synthetic demo to `preview.png`. It does not capture the desktop.
Rendering is not a substitute for attended file-picker, keyboard and VoiceOver
acceptance. Contract tests use the production core without XCTest/Swift Testing,
whose Command Line Tools framework integration is broken on the initial Mac.

## Build from Windows

Commit the intended source first. Configure and verify your normal SSH alias
for the Mac, then run from the repository in PowerShell:

```powershell
./tools/build-on-mac.ps1 -MacHost mac-mini -Revision HEAD
```

Or run `python tools/build_on_mac.py --host mac-mini --revision HEAD`.
Only the companion directory and its build script are archived from that commit.
No working library, home folder, credentials or uncommitted edits are copied.
Git links/symlinks in build inputs are rejected. A dirty checkout is rejected.

Each run uses a fresh `~/Developer/Builds/strike-companion/<revision>-<run>/`
directory on the Mac. It leaves existing checkouts untouched, checks the source
archive hash, then runs the tests/build. The ZIP, log and receipt return to a new
`dist/remote-mac/<run>/` directory on Windows, where revision and artifact hash
are checked again. Failed builds retain logs/source and do not retry. Inspect
the named directory after an interrupted SSH session before deciding to rerun.
There is no scheduled runner, new listener, automatic cleanup or publication.

The Mac must already have Python and the compiler installed. The helper uses
the account's `~/.local/bin`, then Homebrew, then system tools. It never installs
dependencies, changes developer-directory selection or requests administrator access.

## Source and checks

`Sources/Setlist.swift` owns bounded reading, validation and navigation. Kit
references remain plain strings and are never followed. Validation fixtures in
`Tests/Cases.json` run both against the existing Python setlist validator and the
native Swift implementation, including Unicode, type, path and count boundaries.
`Tests/Contracts.swift` additionally checks navigation and failed-import retention.

`Package.swift` exposes the Foundation-only `StrikeSetlists` library for reuse
in a future iPhone/iPad target. Every Mac build also compiles and runs a separate
package consumer (`core-probe`) against the synthetic demo. This verifies the
public library on macOS; it is not an iOS SDK build or device acceptance.
The preview option additionally writes `performance-preview.png` with extra-large notes.

Run `python tools/test_companion_format.py` and `python tools/test_mac_build.py`
on either desktop. The macOS build runs the native contracts. These checks use
only synthetic data; they must never require a connected Strike or personal library.

## Design

An ordered song rail sits beside a spacious performance sheet. Song numbers
communicate actual running order. The current song and its notes dominate;
reference fields and show notes are quieter. Native system text supports familiar
Mac behavior, with rounded display text and monospaced digits only for song order.
Palette: graphite `#1C2126`, slate `#262B33`, brass `#D9B86E`, primary text
`#F2F1EB`, secondary text `#B4BCC5`. Avoid a dashboard/card grid: this is a running
order and a readable sheet, not a monitoring dashboard.

Tracking: https://github.com/Coober666/strike-pro-remapper/issues/71
