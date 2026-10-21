# Native Strike editor

The native iPhone/iPad editor grows from the shared Swift kit-copy editor. It keeps
setlist performance view available and never makes imported originals save targets.
The Mac setlist companion stays independent. This plan is implementation scope,
not a claim of physical acceptance or feature completion.

## One product, with the full web editor as the feature target

The owner chose one native **Strike Remapper** app with performance and editing
views on October 18, 2026. Evolve the existing iPhone/iPad Companion implementation;
do not build a separate competing editor app. The full Strike Remapper web/PWA
workflow is the feature target, including kit/pad editing, instrument and sample
workflows, sound search/assignment/preview, drum-map/setup controls, kit FX,
setlists, MIDI tools and verified module delivery. Native implementation may adapt
the layout to iPad and iPhone. Current builds do not have full feature parity.

The Companion name describes the initial setlist milestone. Version 0.6 changes
visible native branding to Strike Remapper, preserving bundle identity, existing
setlist data, document associations and the shared format contracts. Keep
the Mac read-only companion independent. Preserve the working web app throughout.

The present milestone has real-kit import, confirmed per-pad settings, existing
reference assignment, Undo/Redo and new-copy export. The optional drum map is
simulator-tested. The physical NAS import/edit/export/reopen result is recorded in
[the iPad follow-up](IOS_COMPANION_051_IPAD_NAS_ACCEPTANCE_2026-10-18.md).
Native MIDI input now has a software implementation; broader library/instrument/FX features follow the gates
below. MIDI output, audio routing and module storage each require their own evidence.

## Direct iPad-to-Strike connection comes first

The intended everyday setup is an iPad connected directly to the powered Strike,
without a Mac/PC service. Native Core MIDI supplies the MIDI transport; the Strike
USB port sends and receives MIDI. This is an implementation goal, not confirmation
that this hardware pairing or direct storage transfer works on iPadOS.

Before broadening the editor, implement an explicitly selected MIDI input, bounded
channel-message monitoring/capture, note/velocity/hi-hat views and pad Learn. Opening
the app must not connect automatically or send messages. Begin with read-only MIDI;
add output commands only when documented or independently verified. Do not invent a
live kit-parameter protocol from file offsets. Stop on disconnection/backgrounding,
retain captured work and require explicit reconnect. Simulator-injected MIDI is not
physical USB acceptance.

Then prove whether iPadOS exposes the Strike's user/factory storage through Files,
and whether a new-copy export can be reloaded on the module. MIDI reception alone
does not prove either. The known factory-card activation message still needs its
own attended direct-iPad test. If the module storage is not exposed, investigate an
explicit SD-reader workflow before considering any host dependency. Do not promise
single-cable kit deployment until this gate passes.

Primary references: [Apple Core MIDI](https://developer.apple.com/documentation/coremidi),
[Alesis Strike USB MIDI FAQ](https://support.alesis.com/support/solutions/articles/69000801282-alesis-strike-pro-kit-frequently-asked-questions),
and the repository's [captured factory-card evidence](FACTORY_SD_ACTIVATION.md).

## Native MIDI input milestone (0.7)

The MIDI tools screen is independent of the open kit and setlist. Refresh enumerates
input sources only; the user must select one and press Record. One Core MIDI 1.0
input port receives complete channel messages from that source. No MIDI outputs,
virtual endpoints, audio sessions or sending APIs are used. The UI shows per-channel
note-hit counts/velocity ranges/means, CC4 values and the latest 12 messages. Note On
velocity zero is Note Off. No manufacturer pad map or hi-hat direction is assumed.

Takes are bounded to 50,000 events and 20 minutes. A 4,096-message mailbox bounds
callback-to-UI handoff; overflow/unsupported channel data stops with a partial take.
The port requests MIDI 1.0; nonzero UMP groups and unconverted MIDI 2 channel data
cannot be represented in the version-1 export and cause partial-stop. SysEx/system
messages are ignored. A fresh mailbox per recording rejects old callbacks. The
receive code traverses original variable-length packet pointers, including packets
larger than the SDK's fixed tuple declaration. Timing uses monotonic callback arrival,
not calibrated physical strike timing. No pause/resume is part of this milestone.

Stop drains retained input and closes the port. Background/inactive state and source
removal stop with partial status; later notifications cannot downgrade a normally
stopped take. Reported Core MIDI I/O errors also stop an active take when they
match the selected source's parent device or cannot be attributed safely; errors
from a known unrelated device are ignored. No automatic reconnect or recording restart. A new recording needs
explicit discard of any retained take; a failed open keeps it. Done retains the take
in memory and stops input. Exports are bounded to 8 MiB and use version-1
`drum-midi-session` JSON, validated by the existing web toolkit in
`tools/test_native_midi_export.py`. The export dialog writes only the requested
capture; it never changes the imported kit/setlist. There is no capture import or
app-owned MIDI persistence yet. Export before terminating the app.

Learn arms only during recording, excludes already queued hits, and freezes the
first new positive Note On until Apply name or Cancel. Names attach to channel/note
pairs within this take (128 pairs, 80 UTF-16 units per name) and export as a padMap.
They never change stored kit MIDI settings. Learning is cancelled on Stop/disconnect.
Synthetic driver tests and simulator UI workflows do not establish direct iPad USB,
physical disconnect, audio coexistence or module-storage acceptance. Physical tests
wait until the owner is home with an unlocked device and powered module.

## Music and monitoring audio

The iPad's single USB-C port connects to a hub. The hub supplies USB data for the
Strike, an audio output (built in or a USB DAC), and optionally charging input.
These are peripherals, not a separate computer service. The intended wired setup
uses the hub's USB data connection for Strike MIDI and
an iPad audio output/DAC into the module's AUX IN for music. The module produces
its own drum sound. A MIDI event does not itself produce audio, but any software
drums/preview generated on the iPad can mix with music on its shared output.

Native MIDI monitoring, recording and pad Learn must be silent by default and must
not echo received notes to an output. Never auto-enable software-drum playback.
Future previews/software instruments require an explicit playback choice and Stop;
the editor must coexist with another app playing music. Verify audio-session mixing
and routing on the physical iPad before claiming that behavior. Other apps' MIDI
instruments remain outside this app's control.

## Visual workspace

Add a selectable drum map beside the inspector on wide iPads. Each displayed
pad comes from the open kit; selecting its head/bow and rim/edge/bell changes the
same inspector selection. Keep a Zones list for unknown identifiers, missing zones,
small windows and accessibility. iPhone opens the inspector from the map. Native
buttons must retain at least 44-point touch targets. Map selection never edits kit
bytes, plays audio or sends MIDI.

Use the existing graphite surfaces (#1c2126, #262b33), brass selection (#d9b85e),
light text (#ced4db), muted red drum shells and brass cymbals. Native system type
respects Dynamic Type. Put the standard drum arrangement at the center; keep
surrounding controls quiet and left aligned. Selection uses a brass hoop and an
explicit label. Avoid decorative motion, animated hit feedback and miniature controls.
The first map represents standard positions, not the owner's physical setup.

On wide iPad: a persistent map or Zones list on the left, selected pad and A/B
controls on the right. On phone/narrow iPad: map or list, then a detail screen with
zone-switch buttons. Selection survives switching Map/Zones and Done while the kit
session remains in memory. Unknown zones always remain reachable in Zones.

## Sound workflow

Next add a user-selected, bounded sound-library import and a native `.sin` reader.
Reference validation, sample resolution and sound availability need independent
positive evidence. Preserve relative library structure and original bytes. Search,
preview and assignment are separate explicit actions. Add new kit references only
with shared Swift/Python byte-level contracts and one undoable assignment operation.
No automatic scans, card activation, library migration or overwrite on import.

## Complete editing workflow

Then add confirmed kit FX, app-owned draft recovery, reusable pad setups and
library organization. Extend tests before any new binary writes, retain reserved
bytes, and export fresh copies with the existing verified writer. Native audio,
portable library export and module delivery are separate milestones. Direct mobile
USB and a universal module editor remain research, not implied capabilities.

## Verification

Use synthetic fixtures and installed iPhone/iPad simulators first. Cover map/zone
selection, all supported zone types, unknown-zone fallback, compact navigation,
rotation and editing/export regressions. Keep evidence tied to actual source hashes.
Physical iPad follow-up waits until its owner confirms the OS update has finished.
Guide attended steps one at a time; simulator or process-launch results never count
as owner-confirmed UI or module playback.
