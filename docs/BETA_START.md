# Start with the source beta

This ZIP is a portable application folder for testing. It requires Python 3.10 or
newer; the host window also requires Tk. It is unsigned, has no automatic updater,
and is not a native iPhone/iPad app. MIDI capture on physical modules and the latest
mobile workflows still need acceptance testing.

## First ten minutes

1. Extract the whole ZIP to a new folder. Keep every file together; do not launch
   from inside the ZIP or extract over an old installation.
2. Windows: open `launch-host.bat`. Mac: open `launch-host.command`. If the Mac
   launcher is not executable after extraction, run `python3 launch_editor.py`
   from the extracted application folder. Linux desktop: run that same command.
   If Python/Tk is missing, follow [host setup help](HOST_LAUNCHER.md#first-run-help).
3. Choose a separate library folder. Start with a copy of your library or an empty
   folder; keep its backup elsewhere. Choose Start, then Open editor.
4. Open Drum MIDI toolkit and Try a demo. Name it, add notes/tags and Save session.
   Wait for **Saved in this browser** before closing/reloading the page.
5. Select one channel/note under Analysis focus. The chart/report should isolate
   that note while JSON and CSV retain the whole take.
6. Under Saved sessions, select the demo for backup, open Back up / restore sessions,
   and Export selected sessions. Restore that file to verify a new copy appears.
   Repeated imports intentionally make new copies; existing sessions are never replaced.

## iPad and iPhone

Stop the host, enable Wi-Fi, choose its private IPv4 address and Start. Scan its
pairing QR code with the mobile device on the same trusted network. Use `http://`;
Brave may need its automatic HTTPS upgrade disabled for this local address. Open
Drum MIDI toolkit from the editor. The module connects to the host computer by USB.

Host MIDI capture requires the optional package in `requirements-midi.txt`, installed
in the Python environment running the editor. Use Host setup check before Record;
see [MIDI setup](MIDI_TOOLKIT.md). Demo/import/analysis do not need a module or that
package. Native apps and direct mobile USB remain deferred.

## Know where your work lives

- Kit saves, samples and recovery live in the host's selected library folder.
- MIDI sessions and saved pad profiles live in each browser and host address/port.
  Changing address, browser or device can show an empty shelf. Export session backups
  and profiles before clearing browser data or changing the host address.
- A session backup contains saved captures, including their own pad-map snapshots.
  It does not include unsaved edits, the reusable profile shelf or the kit library.
  Back those up separately. Export profiles from Pad names & MIDI Learn.
- The temporary host MIDI take lasts 10 minutes after stopping. It is not a backup.
- Save in the kit editor saves the library copy; Deploy explicitly writes the user
  card. Use copied kits/disposable media when testing. Factory content stays read-only.

## Updating and reporting a problem

Save and Stop before updating. Extract the next beta to a new application folder,
then select the same external library. Keep the prior folder and a library backup
until the new version is checked; see [upgrade/rollback steps](HOST_LAUNCHER.md).

Include the revision from `BETA-MANIFEST.json`, operating system, Python/browser,
module model and the steps that led to the problem. For MIDI input failures, export
the host setup report. Review reports before sharing input names or driver details.
Do not post pairing links/tokens. Mark whether the result used real hardware or a demo.

The remaining [release acceptance checklist](RELEASE_CHECKLIST.md) is deliberately
open until each item has evidence. A passing automated test is not hardware acceptance.

## Build a package from a checkout

From the repository folder, run:

```text
python tools/build_beta.py --output dist/strike-remapper-beta.zip
```

Choose a new filename if that file already exists. The builder only includes runtime
code/assets, selected utilities, public documentation and license/catalog metadata.
It excludes libraries, Git state, test fixtures, captured takes, node packages and
private configuration. Mac command files receive Unix newlines/executable attributes.
The embedded manifest records the Git revision, whether the working tree had changes,
and a SHA-256 hash for each packaged file. Identical checkout contents produce identical
ZIP bytes; this manifest detects content changes, not publisher authenticity.

`python tools/test_beta_package.py` builds/extracts the archive, checks file hashes,
exclusions and launch-file attributes, and starts the extracted host with a temporary
external library and card discovery disabled. It verifies pairing and served assets.
It does not install Python/Tk or test macOS launch permissions or physical MIDI.
