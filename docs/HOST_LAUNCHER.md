# Run the editor host

The optional host window controls one editor process and its library. It does not
install a background service, start on login, update firmware, or deploy automatically.
Python 3.10+ with Tk is required for the window. The existing command-line editor
continues to work without Tk. This is a source launcher, not a signed installer.

## First launch

1. Windows: double-click `launch-host.bat`. Mac: double-click `launch-host.command`.
   Or run `python launch_editor.py` (`python3` on Mac).
2. Choose the folder containing your existing `kits`, `instruments`, and `samples`
   folders. For a new library, choose an empty folder. No existing files are moved.
3. Leave Wi-Fi off for computer-only use. Choose **Start**, then **Open editor**.
4. For iPad/iPhone, stop first, enable Wi-Fi, and select the computer's private IPv4
   address. The address list is a convenience; some Macs require entering their Wi-Fi
   address manually. Start, then scan the QR code using the mobile camera.
5. Use the private pairing link on the same Wi-Fi. It grants full editor access.
   HTTP is required; if Brave upgrades it, permit HTTP for that local address.
6. Keep the computer awake. **Stop** writes a local recovery copy and closes this
   service. A failed initial recovery save leaves the editor running so you can save.
   If the final save fails after the service stops, keep the window open. Its latest
   edits remain in memory. Free disk space or restore folder access, then choose
   **Retry recovery save**. Changing libraries and closing are held until it succeeds.

Start/Stop and diagnostics remain visible in short windows. Scroll the setup/pairing
area to reach its contents; keyboard focus brings setup fields back into view.

The launcher uses port 8765 and never stops an existing process to free it. If occupied,
stop the other editor yourself or use the command-line `--port` option for Wi-Fi.
Wi-Fi starts disabled on each launcher run. Pairing links are new after each start;
old browser sessions must pair again. The library choice and address are remembered.

## First-run help

- **Python not found:** install Python 3.10+ with its Tcl/Tk component. On Windows,
  include the Python launcher (`py`); if only `python` is available, run
  `python launch_editor.py` from the application folder. On Mac/Linux use `python3`.
- **Tk missing:** use the same Python command followed by `-m tkinter` to check its
  Tk installation. The editor can run without the host window: `python strike_remap.py`
  (`python3` on Mac/Linux). Wi-Fi without Tk is documented in [Wi-Fi setup](WIFI_EDITOR.md).
- **No graphical desktop:** launch the window from the computer's desktop session.
  For an SSH-only host, use the terminal Wi-Fi entry point instead.
- **Port already in use:** an editor or another service owns port 8765. Stop that
  service deliberately or use the Wi-Fi command's `--port` option. The launcher
  does not kill another process or silently attach to a different library.
- **Wrong library folder:** select the parent containing `kits`, `instruments`, and
  `samples`, not an individual kit, the `kits` subfolder, or the application folder.
  For an older installation this is often its `library` subfolder. Keep a backup
  before moving it. A new empty library is also valid.
- **Wi-Fi address changed:** use this computer's current private IPv4 address, or
  turn Wi-Fi off to work locally. A remembered address may belong to an old network.

## Diagnostics

**Copy diagnostics** includes host status, address, and library path; it excludes
the pairing token. Review it before sharing because folder names may be personal.
If a mobile connection fails, check same Wi-Fi, host awake, local-network/firewall
permission, and `http://`. Changing networks may require a different host address.

## Recovery and upgrades

Recovery copies are local `.autosave.skt` files offered from the editor's Start screen.
Periodic copies run on the host every 60 seconds, independently of open browser pages.
Normal Stop also saves recovery. Power loss or force-killing can lose the most recent
edits. Before switching kits, current unsaved edits are preserved; a failed preservation
blocks the switch. Failed recovery does not remove its recovery entry. Recovering the
same kit's older copy also snapshots the current edits first.

Before upgrading: Save to library, Stop, and back up the entire library folder, including
snapshots and sidecars. Replace the application files, then select the same external
library folder. Do not replace or delete the library with the application. No automatic
migration or updater is installed. To roll back, stop and launch the previous application
against a backup copy of the library. Never test a rollback against your only copy.

To rehearse this yourself with a copied library:

1. Stop the host. Copy the whole library to a dated backup folder; compare file counts
   and sizes, and keep the backup untouched.
2. Extract the new application into a separate folder. Start it and select your working
   library. Confirm kits, tags, snapshots and any recovery entry are present.
3. Recover a disposable kit, check the edited value, and save it to the working library.
4. Stop. Copy the pre-upgrade backup into another working folder. Start the previous
   application against that copy and confirm the original kit and recovery files load.
5. Keep the real library and backup separate from application folders you remove.

The automated rehearsal hashes every backup file, including snapshots and sidecars,
and verifies recovered kit bytes in fresh processes. On October 13, 2026 it passed
from merged commit `afdca93` to this polish branch, then back to `afdca93` using a
restored backup copy. It used a synthetic kit and sample sentinel, not a real card.
`tools/test_library_portability.py` repeats the relocation/backup checks in CI;
set `STRIKE_PREVIOUS_APP` to an extracted older release to repeat a version boundary.

## Verification limits

Automated loopback tests cover start/stop, initial and final recovery failures on stop,
occupied ports, pairing, token renewal and diagnostics. Real Tk control tests on Windows
exercise Start/Stop, saved library selection, QR rendering, short-window scrolling and
recovery retries, including a blocked close. They use disposable libraries with card
discovery disabled. CI has a Windows job where missing Tk/display fails instead of skipping.
These are programmatic checks, not a new-user install or a camera scan. The launcher
still needs hands-on Windows and Mac/iPad acceptance. The older Intel Mac remains the only physically
verified Strike host; the launcher does not extend module compatibility claims.
Linux can use the existing command-line host; optional Tk availability depends on its
Python installation. Native iPhone/iPad apps and direct mobile USB remain paused.

See [release acceptance](RELEASE_CHECKLIST.md) before distributing a release.
