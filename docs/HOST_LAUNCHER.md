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

The launcher uses port 8765 and never stops an existing process to free it. If occupied,
stop the other editor yourself or use the command-line `--port` option for Wi-Fi.
Wi-Fi starts disabled on each launcher run. Pairing links are new after each start;
old browser sessions must pair again. The library choice and address are remembered.

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

## Verification limits

Automated loopback tests cover start/stop, failed recovery on stop, occupied ports,
pairing, token renewal and diagnostics. The launcher window and QR scanning still need
hands-on Windows and Mac/iPad acceptance. The older Intel Mac remains the only physically
verified Strike host; the launcher does not extend module compatibility claims.
Linux can use the existing command-line host; optional Tk availability depends on its
Python installation. Native iPhone/iPad apps and direct mobile USB remain paused.

See [release acceptance](RELEASE_CHECKLIST.md) before distributing a release.
