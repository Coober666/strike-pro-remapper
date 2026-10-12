# Activate the factory card from an iPad over Wi-Fi

Leave the Strike's USB cable plugged into a Mac, Windows PC, or Linux/Pi host.
The iPad opens a paired controller in Safari; the host sends the verified activation
message and checks for its mounted read-only factory library. Web MIDI is not needed
on the iPad, and no browser needs to remain open on the USB host.

This service is an **activation companion**. For kit editing and deployment from an
iPad, use the separate [paired full Wi-Fi editor](WIFI_EDITOR.md). Normal editor startup
still binds to localhost. Direct USB from an iPad needs a native app; that work is paused.

## Start and pair

1. Connect the powered-on Strike to the computer. Keep both the iPad and computer on
   your trusted local network.
2. In this repository's folder on the USB host, start the controller with that host's
   LAN IPv4 address using **Python 3.10+**. On older macOS installations, select your
   newer installed Python instead of `/usr/bin/python3` (often 3.9). For example,
   if the host address is `192.168.1.50`:

   ```sh
   python3 -m strike_remapper.factory_bridge --bind 192.168.1.50
   ```

   On Windows use `python` instead of `python3`. The default port is 8766; use `--port`
   to change it. If the OS firewall asks, allow access on the private network only.
   Omitting `--bind` restricts access to `127.0.0.1` for local testing.
3. Open the **complete pairing link printed by the controller** on the iPad. Treat
   it as a password: it grants activation access while this controller process runs.
4. Tap **Find the Strike**, choose the host's Strike MIDI output, and tap
   **Activate factory card**. The controller sends once and checks for the factory
   library for approximately 15 seconds after sending. Slow OS disk calls can extend
   that interval. A successful MIDI send is not reported as confirmed storage access.
5. After activation, use the full editor on the host for library copying or inventory
   capture. Neither operation is triggered by the iPad controller.

Stop the controller with Ctrl-C when finished. Restarting generates a new pairing
secret and invalidates old links. **Forget pairing** clears that browser tab's copy;
it does not revoke links in other tabs. This is plain HTTP for a trusted LAN, not an
internet service: do not port-forward it or use it on untrusted/shared Wi-Fi.

## USB host requirements

| USB host | MIDI transport | Storage discovery |
|---|---|---|
| Mac | Built-in CoreMIDI, no Python packages | Existing `/Volumes` scan plus OS read-only flags |
| Windows | Built-in WinMM, no Python packages | Existing drive scan plus `FILE_READ_ONLY_VOLUME` |
| Linux / Pi | `amidi` from `alsa-utils`, permission to access the MIDI device | Mounted read-only filesystems from `/proc/self/mountinfo` |

Close other applications if they hold exclusive MIDI access. On Linux, install the
distribution's `alsa-utils` package if needed. A headless Pi may enumerate the factory
disk without mounting it: mount the identified factory partition **read-only**, then
optionally pass `--factory-root /your/mount/path`. The controller does not mount,
unmount, format, or change disk permissions for you. That option also helps distinguish
a known factory mount from other read-only library copies.

Only connected outputs whose names contain the word Strike are listed. Selection is
rechecked in the short-lived MIDI helper immediately before sending. No API accepts
arbitrary MIDI bytes. The only packet is `F0 00 00 0E 48 0E 33 03 01 F7`.

## Results and limits

- Already-available factory library: no MIDI sent.
- Message sent: the host is still checking; this is not confirmation.
- Read-only factory library detected: exactly one candidate has the expected
  `Instruments` and categorized `Kits` layout and a read-only filesystem. This is a
  mount/content check, **not USB serial identity verification**. A read-only mirror
  can also match; use `--factory-root` when necessary.
- Not confirmed or driver error: inspect USB, host MIDI access, and disk mounting.
  The command may already have been sent. There is no automatic retransmission.

Reloading the same tab resumes observation of its saved request, never another send.
The host deduplicates the latest 64 request IDs per process and accepts one activation
job at a time. Pairing tokens are kept in tab session storage, stripped from the URL
after pairing, and never put in access logs. Requests require the token and the exact
host/origin; no CORS access or full-editor file API is exposed.

The bridge checks filesystem flags and directory names without creating write probes.
It does not send a shutdown command, alter firmware, or write files on either SD card.
It cannot undo a packet already transmitted.

## Validation status

The packet itself was verified by native replay on an Intel Mac, including after a
fresh module power cycle; see [the capture evidence](FACTORY_SD_ACTIVATION.md).
The new helper's **output discovery** was checked on that Mac and on Windows (no
Strike attached to Windows). The new controller's sends and card transitions use
simulated hardware in tests. The macOS native transport also delivered exactly one
evidence-matching packet to a temporary virtual CoreMIDI destination; that test sent
nothing to the real module. Its browser flow is tested in Chromium and WebKit with
an iPad viewport and Web MIDI disabled. Those automated tests do not establish physical
iPad or Linux hardware validation.

**Subsequent physical-device run, October 12, 2026:** the user activated factory access
from the iPad and reported “Read-only factory library detected”; Mac inspection confirmed
the Strike's factory card mounted read-only. The separate full editor then completed a
user-operated iPad edit, Mac save, and user-card deployment, with byte-for-byte file
verification and user-confirmed playback. See the [hardware verification and user-card
recovery record](WIFI_EDITOR.md#hardware-verification-october-12-2026). Windows/Linux
native activation hardware and direct iPad USB remain unverified.

Implementation: `strike_remapper/factory_bridge.py`, `factory_midi.py`, and
`web/factory-controller/`. Tests: `tools/test_factory_bridge.py` and
`tests/browser/factory-controller.spec.js`; the virtual native transport check is
`tools/test_factory_midi_macos.py` (skips outside macOS).
