# Full editor over Wi-Fi

Keep the Strike's USB cable connected to your Mac, Windows PC, or Linux computer.
The iPad is the browser; the computer owns the library, SD access, and factory activation.
This mode adds remote access to the existing editor, including its normal explicit save
and deployment actions. It is separate from the activation-only controller on port 8766.

## Start and pair

The optional [host window](HOST_LAUNCHER.md) provides Start/Stop, a remembered library
folder, **Open editor**, and a locally generated pairing QR code. Wi-Fi is opt-in.
Its launcher and QR scanning still need physical acceptance; the command below remains
available without a graphical desktop or Tk.

With Python 3.10 or newer, run from the repository folder:

```sh
python3 -m strike_remapper.wifi_editor --bind 192.168.1.239 --library-root /path/to/strike-library
```

Replace the address with your computer's private LAN IPv4 address and the library folder
with its persistent library location. Windows may use `python` instead of `python3`.
Port 8765 is the default; use `--port` if occupied. On macOS use the newer Python installation,
not an old `/usr/bin/python3`. The normal `python strike_remap.py` remains localhost-only.

Open the printed **private pairing link** on the iPad on the same network. Keep `http://`:
this server does not speak HTTPS. If Brave upgrades it, allow HTTP for this LAN address.
Pairing automatically opens the editor and removes the secret from the address bar.
You can also paste the link into the pairing page. Keep the link private: anyone with it
on the LAN has full editor access, including host files and deliberate Deploy actions.

Choose a mounted kit in Kits, or use Start to sync the cards into the computer's library.
**Save to library** saves a host copy. **Deploy** is separate and uses the existing preview
and confirmation workflow for the writable user card. The factory card remains read-only.
To expose it after a fresh module boot, choose **Activate factory card**, then find the
Strike and activate it in the new controller tab. Return to the editor and refresh if needed.
This does not make kit edits live on the module; deploy and reload the kit there as usual.

## Session and platform limits

- One page holds editing control. Additional pages open **view-only** because the host
  has one active kit and undo history. Choose **Take editing control** and confirm to
  move editing: the receiving page reloads the current kit, including unsaved changes,
  before enabling writes. Old page requests are rejected by the host, including imports,
  tool execution, saves, and deployment. Switching never saves or deploys automatically.
- A reload resumes control using a per-tab token, which is rotated to invalidate the old
  page. Opening a separate tab without that token starts view-only; duplicating a tab
  that copies session storage moves control to the duplicate and revokes the old page.
  Closing a page does not silently release unsaved work: take control on another page.
  Disconnecting or the pairing session expiring releases its control. A browser with
  session storage disabled can use the initial editing page but cannot resume on reload.
- View-only pages show the state loaded when they opened, not a live collaborative view.
  The fixed factory-activation controller remains available to paired browsers; editing
  ownership protects full-editor POST routes. The default localhost service is unchanged.
- **Disconnect** revokes that browser's session. Sessions expire after 12 hours; reopening
  the pairing link pairs again. Stopping the host process revokes every session and link.
- Keep the computer awake and connected. This command does not install an auto-start service.
- Use only a trusted LAN. HTTP is unencrypted; exact Host/Origin checks and pairing are
  access controls, not encryption. Do not port-forward this server or expose it publicly.
- iPad file editing, library browsing, and HTTP audio use the host APIs. Existing Web MIDI
  features such as live pad input and trigger SysEx backup still require a supported
  local browser. Wi-Fi forwards only the verified factory activation command through MIDI.
- Native activation is verified on the Intel MacBook/Monterey with the Strike. Windows
  and Linux adapters remain hardware-unverified. The physical iPad-to-Mac workflow below
  is verified separately from automated tests. Chromium and simulated iPad WebKit tests
  cover pairing, actual synthetic-kit edit/save/reload, logout, and host activation routing.
- The connection strip distinguishes an unreachable computer from an undetected card.
  Open **Connection details** and **Refresh connection** after reconnecting USB or mounting
  cards. Card discovery is not continuously polled. **Save to library** updates the host
  copy; **Deploy to Module** copies to the user card and verifies it. Reload the kit on
  the Strike after a successful deployment. These UI and handover changes are covered by
  simulated browser/API tests; they have not yet had another physical hardware pass.
- Direct USB from iPad to Strike remains unimplemented. The native Companion and
  read-only kit inspector do not include it.

The earlier “Read-only factory library detected” result confirms the host found a mounted,
read-only volume with the factory content shape after activation. It is not a general
live-editing protocol or a raw USB capture, and content shape alone is not proof of USB identity.

## Hardware verification: October 12, 2026

Verified with a physical iPad controlling the full editor over Wi-Fi, a late-2016 Intel
MacBook Pro running macOS Monterey 12.7.6 and Python 3.14.3, and an Alesis Strike attached
to that Mac by USB. Brave was used on the iPad during this session; browser version,
iPad model, and iPadOS version were not recorded. The running application was commit
`bd575c3de2ce531942cb8fc556ed747df32a6ce8`; the subsequent PR changes only document these results.

| Step | Evidence | Result |
|---|---|---|
| Factory activation from iPad | User reported “Read-only factory library detected”; host inventory independently showed the Strike's 7.9 GB factory card mounted read-only | Factory access available through the Mac |
| Full editor over LAN | Unpaired API returned 401; paired editor loaded; host listed 117 factory kits; iPad WebKit check had no page errors or horizontal overflow | Pairing and host library access verified |
| Both cards available after USB reconnect | Mac disk/USB inventory showed the 7.9 GB read-only factory card and 15.9 GB writable user card; editor reported both mounted, with 117 factory kits and 13 user kits | User-card deployment destination available |
| Edit and Save on physical iPad | User changed SEVENzREC's snare Layer A and pressed Save; server reported `dirty: false`; an independent read parsed the saved `.skt` | Mac library contained `Snares/BJ DWBallad Center.sin`; user-card copy still contained `Snares/BJ DWMaple Center.sin` |
| Deploy from physical iPad | User pressed Deploy to Module; independent reads compared the library and user-card `.skt` files | Files were byte-for-byte identical; user card now referenced `Snares/BJ DWBallad Center.sin` |
| Listen on the module | After being instructed to switch kits and reload SEVENzREC, the user reported “it worked!” | User-confirmed audible result; no independent audio recording was made |

Snare Layer B remained `Snares/NAC14inMaple Center.sin` in both copies throughout the
save/deploy checks. These checks read the kit files without modifying them; the user
initiated Save and Deploy from the iPad. This verifies **iPad edit → Mac library save →
user-card deployment → module playback** for this setup. Save alone did not update the
user card. This is file-based deployment, not live parameter streaming over MIDI.

All 29 automated browser tests and the repository's Python/format/parity checks also
passed for the implementation. Those tests use isolated synthetic files. Hardware
observations above are a separate user-assisted run, not inferred from simulated tests.
This run does not validate Windows/Linux hardware, direct iPad USB, every editor feature,
other firmware versions, or prolonged USB-storage reliability. Factory files were not
written and SIP/firmware settings were not changed.

## Mac sees the factory card but not the user card

In this run the module could read its inserted user card, but macOS exposed only the
factory disk. The Strike's second USB storage unit existed with no media attached in
the Mac's registry. A normal editor refresh or mount request could not recover an
already-ejected disk.

The Mac logs at **14:48:02 PDT on October 12, 2026** identified `loginwindow` as the
process that rejected the user-card mount and requested its eject:

```text
CopySLMountApprovalCallback | DiskArb - Allow = NO
CopySLMountApprovalCallback | DiskArb - wholeDisk != nil, calling DADiskEject
CopySLMountApprovalCallback | DiskArb - Allow = NO, set return value to kDAReturnNotPermitted
disk mount approval, disk = /dev/disk2s1, dissented, status = 0xF8DA0008
ejected disk, id = /dev/disk2, success.
```

This occurred before the full Wi-Fi editor started. **Why loginwindow denied the mount
was not established.** A locked-session restriction was considered, but is not proven;
do not generalize this as a Monterey rule or change security settings on that basis.

Recovery used in this session:

1. Save any editor changes and wait for card operations to finish.
2. Unlock the Mac to its desktop and safely eject the visible Strike factory volume.
3. Disconnect and reconnect the Strike's USB cable, leaving the module powered on and
   its user SD card inserted.
4. Confirm both cards in the host's disk inventory, then refresh the iPad editor.

The user reported completing that sequence. At **16:18:14–15 PDT**, the logs recorded
both mounts approved and successful; the editor then reported both cards present.
No module power cycle or additional activation send was needed for this recovery.
Disk numbers changed during reconnect: identify each card by its device, contents,
and read-only status rather than copying the historical `disk2` identifier above.
If the same problem recurs, inspect the host mount/eject logs before blaming the card
or changing the activation protocol.
