# Factory SD activation through MIDI SysEx

Verified October 11–12, 2026. **One exact MIDI SysEx message exposed the factory SD
with the official editor closed, including after a user-confirmed module power cycle.**
The app now offers an explicit **Activate factory card** action using this message;
it does not activate automatically.

```text
F0 00 00 0E 48 0E 33 03 01 F7
```

Send the 10 bytes, including `F0` and `F7`, to the **Alesis Strike MIDI destination**.
Only this complete packet has been tested; the payload fields are not individually
decoded. No variations or guessed deactivation command were sent.

## Tested setup and method

- Late-2016 Intel MacBook Pro, macOS Monterey 12.7.6 (21H1320).
- Alesis Strike USB vendor/product `13b2:0092`; USB device version `0.33` is a
  descriptor value, **not a verified firmware version**.
- Official Strike Editor 1.1.6, build 1.1.6.14666; MIDI Monitor 1.5.4.
- User disk: 15,931,539,456 bytes. Factory disk: 7,948,206,080 bytes.
- Factory disk and partition reported media read-only; the FAT volume mounted read-only.

A passive CoreMIDI logger loaded `SnoizeMIDISpy.framework` from the installed MIDI
Monitor application. This uses the same driver mechanism as **Spy on output to
destinations** without changing the monitor's GUI document. It subscribed to outgoing
traffic to the Strike and incoming traffic from it; all setup calls succeeded.
The logger itself contains no MIDI-send operation.

Disk inventories were polled roughly every 0.5 seconds plus command overhead.
The timings below measure first observed disk enumeration, not exact firmware latency.
Capture timestamps are UTC, and packet timestamps use the Mac's wall clock.

## Results

| Experiment | Initial state | Observed packet time (UTC, October 12) | First factory-disk observation | Result |
|---|---|---|---|---|
| Official editor launch | Only user card available | 06:51:02.926805 | 06:51:05.163195 | Factory card appeared after ~2.236 s; editor repeated the same packet at 06:51:05.185860 |
| Isolated replay | Editor exited; factory card absent | 06:57:24.677320 | 06:57:27.241364 | One packet sufficient; factory card appeared after ~2.564 s |
| Fresh-boot replay | User confirmed module power cycle; editor closed; only user card available | 07:02:18.616074 | 07:02:20.599225 | One packet sufficient; factory card appeared after ~1.983 s |

The replay sender called `MIDISend` once, returned success, and exited. The separate
spy independently captured the transmitted packet. The editor remained absent at the
end of both replay captures, while both cards remained mounted. No additional MIDI
traffic was captured during roughly 35 seconds after each replay; a keepalive was not
needed in that observation window. Longer-term behavior has not been established.

For the fresh-boot run, the user was asked to safely eject both volumes, turn the module
off for about 10 seconds, and turn it back on with USB connected and the editor closed.
The user confirmed completion. The physical power cycle was user-reported; the agent
verified the resulting disk and process states over SSH. The official editor was never
launched during that test.

## Shutdown remains unresolved

Normal editor quit was requested under capture. AppleScript returned `User canceled`
(`-128`), but subsequent process and disk checks showed the editor gone, the factory
disk absent, and the user disk retained. No outgoing MIDI was captured in that interval.
The first shutdown wrapper subsequently timed out while waiting for its logger and
terminated that logger, so this is a **partial shutdown trace**, not proof of an off
command or a complete deactivation protocol. Do not infer that changing the final
`01` to `00` is valid.

## Portability and integration

The bytes are a MIDI message to the module. We expect other MIDI-capable USB hosts
to be able to send them, but **only the Mac setup above has been hardware-tested**.
Sending MIDI and accessing the resulting mass-storage volume are separate concerns.

| Host | Available implementation path | Strike activation status |
|---|---|---|
| macOS | Native CoreMIDI; supported browsers can also offer Web MIDI with SysEx permission | Native CoreMIDI confirmed on the tested Intel Mac |
| Windows | Native MIDI SysEx output or a supported Web MIDI browser | Expected; not tested |
| Linux / Raspberry Pi | ALSA MIDI, including a headless sender | Expected; not tested; disk mounting depends on the host setup |
| iPad | Native CoreMIDI app, or browser UI controlling a USB-connected Pi/Mac backend | Not tested; Safari currently lacks Web MIDI, and direct access to the Strike's exposed storage also needs validation |

A browser's Web MIDI endpoints belong to the **browser's machine**. If the Strike is
plugged into a Pi but the browser runs on an iPad, MIDI activation must happen on the
Pi through a backend, and the Pi must also handle card access. This bridge is a proposed
architecture for full editor access. A separate paired, activation-only host controller
is now implemented; see [iPad Wi-Fi setup](IPAD_FACTORY_CONTROLLER.md). Direct Web MIDI requires a supported secure
context and explicit SysEx permission.

### Current browser implementation

Connect USB to the computer running both the Python app and the browser. Open the app
at `http://localhost:8765` (loopback addresses are also accepted) in a browser offering
Web MIDI with SysEx permission, such as Chrome or Edge. Choose **Activate factory card**
from Start, Tools, or Deploy, then **Connect MIDI**, allow SysEx, choose the connected
Strike output, and activate. Only outputs with Strike in their name are offered; if
there are several, selection is required.

The app first checks `/api/status`, sends the exact packet once if the factory card is
absent, and polls existing card discovery with a 15-second deadline. It reports success
only after that discovery reports the factory card mounted. Failure, disconnect, and
timeout do not trigger another transmission. Closing the dialog cancels observation;
it cannot undo a message already sent. Copy and inventory capture are separate actions.
Factory write protection is unchanged; activation makes no card-file write requests.

Remote hostnames and the read-only viewer are blocked. This ensures the supported setup
uses the same computer for Web MIDI and disk discovery; do not use a forwarded localhost
port for this local Web MIDI feature. The separate Wi-Fi controller provides native host
MIDI for iPad activation; it does not expose the full editor. A direct-USB iPad app is paused.
The browser workflow is covered by simulated MIDI/card tests, **not a new hardware run**.
The native macOS protocol experiments above remain the hardware evidence.

A successful send alone does not prove card availability. Continue
to enforce factory write protection and existing card-read retry behavior; do not
identify cards by mount name, disk number, or capacity alone. Those capacities describe
this test setup, and device numbers changed after the power cycle.

This discovery does not establish live parameter sync, stability under sustained card
reads, operation on other firmware, or a safe deactivation message. No card files,
firmware, or SIP settings were changed in these tests. Raw USB capture was unnecessary
for discovering and exercising the activation packet.

## Evidence

The [evidence directory](evidence/factory-sd-2026-10-12/) contains:

- Unmodified MIDI packet logs for editor launch, warm replay, fresh-boot replay, and
  the partial shutdown trace.
- `observations.json`: a projection of the original disk/timeline evidence retaining
  sizes, device identifiers, read-only properties, packet times, and editor state.
- The tested passive logger and one-shot sender source as research artifacts; neither
  is integrated into the application or automatically executed.
- `activation.syx`: the exact 10-byte packet, and `SHA256SUMS.txt` for these artifacts.

Hostnames, LAN addresses, local user paths, USB serials, and volume UUIDs are omitted
from the published disk evidence. The complete original capture bundle remains with
the investigation. These captures predate the browser implementation; no extra hardware
tests were run merely to publish this documentation or validate its browser UI.

## Sources

- [Snoize output-spy documentation](https://www.snoize.com/MIDIMonitor/docs)
- [Snoize spy framework API](https://github.com/krevis/MIDIApps/blob/main/Frameworks/SnoizeMIDISpy/Framework/MIDISpyClient.h)
- [Windows SysEx sending](https://learn.microsoft.com/en-us/windows/win32/multimedia/sending-system-exclusive-messages)
- [ALSA sequencer API](https://alsa-project.org/alsa-doc/alsa-lib/group___seq_middle.html)
- [Apple Core MIDI](https://developer.apple.com/documentation/coremidi)
- [Web MIDI access and SysEx permission](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/requestMIDIAccess)
- [Browser compatibility data](https://github.com/mdn/browser-compat-data/blob/main/api/Navigator.json)
