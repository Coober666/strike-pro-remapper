# Strike Remapper — Windows beta

For Windows 10/11 x64. Python, Tk and host MIDI support are included.
No Python, Git or terminal setup is needed to run this package.

1. Download the Windows beta ZIP from the project's tested CI run (artifact
   strike-windows-beta-…). GitHub requires sign-in to download CI artifacts.
   If GitHub supplies an outer artifact ZIP, extract it first.
2. Right-click the application ZIP and choose Extract All. Keep the entire
   Strike Remapper folder together, including _internal.
3. Open Strike Remapper.exe. Choose Open editor. Your default browser opens.
   Keep the small host window open while editing. Stop saves recovery and
   shuts down the server; closing the window also stops it.
4. No module handy? Choose Try a demo for a synthetic drum-MIDI session.
   It does not connect to MIDI, activate a card, or change a module.

The default library is Documents/Strike Remapper/library under your Windows
home folder. You can choose an existing library instead. Application upgrades
must stay separate from this folder; libraries inside the package are rejected.
Back up your library and original SD card before editing/deploying real kits.
Closing the browser alone does not stop the host.

Detailed help travels with this download. Open the Help folder beside the executable,
then double-click README.txt or a named guide to read it in Notepad. Setup, Wi-Fi,
MIDI sessions/profiles, recovery/upgrades, setlists and device-check instructions are
included as text files, with screenshots. No Markdown app or internet is required
to read them; optional repository/evidence links need internet. Source-start.txt is
for the separate Python source package, not the bundled Windows executable.

For iPad/iPhone: before opening the editor, enable Wi-Fi in the launcher and
choose this computer's private IPv4 address. Scan the pairing code on the same
trusted network; use HTTP. The Windows computer stays on and hosts the editor,
and the module's USB cable stays connected to that computer. If Windows asks
about firewall access, allow only your trusted private network. This package
is not a native iOS app. Direct iPad/iPhone USB is still deferred.

MIDI input support is bundled. In Drum MIDI toolkit, select the Wi-Fi host
computer source and use Host setup check. A missing input still means the USB
connection or device/driver needs attention. Capture only begins when you
explicitly choose an input and Start. Factory activation remains an explicit
separate action; the demo and package checks do not send activation messages.

Updates: Stop and close the old host. Extract the new ZIP into a new application
folder, open its launcher, and keep the same external library selection.
There is no automatic updater. Keep the previous package for rollback.

This beta is unsigned. Windows may show an unknown-publisher warning; verify
that your download came from this repository's tested build. Do not disable
Windows security protections. A signed installer is a later release step.
The ZIP has a SHA-256 sidecar, and PACKAGE-MANIFEST.json lists every payload hash.
The editor's support report identifies the source revision.

If it does not start: extract all files, retain _internal, and check whether
another editor is using port 8765. The launcher never kills another process.
Use Copy diagnostics or the editor support report when reporting a problem.
Do not post pairing links publicly. Source launch remains available for
Mac/Linux and developers; see the repository's docs/HOST_LAUNCHER.md.

Build verification checks an extracted copy with Python removed from PATH,
bundled Tk/MIDI, editor assets, external-library save/recovery and helper tools.
It does not substitute for a fresh Windows machine test or connected-module
acceptance. No physical device test is implied by a successful package build.

## Building from source

On Windows x64 with Python 3.11:

    python -m venv .build/windows-env
    .build/windows-env/Scripts/python -m pip install -r requirements-build-windows.txt
    .build/windows-env/Scripts/python tools/build_windows.py --output .build/strike-windows.zip --require-clean
    python tools/check_windows_package.py .build/strike-windows.zip

Use a clean Git checkout for --require-clean; omit that flag only for a local
experimental build, whose identity will explicitly report modified sources.
The check extracts into a disposable directory and never opens MIDI ports.
CI publishes the ZIP only after source, browser, host and packaged checks pass.
