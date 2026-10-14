# October 14 beta candidate

This is the tested unsigned beta at revision
`d56baecb53a1d537f13c8646f07317f488aee3d2`. It includes the combined work in
PRs #66, #67 and #68. It is available for controlled testing; it is not a published
stable release. Later documentation commits do not change the downloads pinned here.

## Download and open

Sign in to GitHub and choose the artifact for your computer from
[this successful build](https://github.com/Coober666/strike-pro-remapper/actions/runs/38624534354).

| Computer | Download | What to open |
| --- | --- | --- |
| Windows 10/11 x64 | [Windows beta artifact](https://github.com/Coober666/strike-pro-remapper/actions/runs/38624534354/artifacts/11924331931) | Extract both ZIP layers, keep the whole `Strike Remapper` folder, then open `Strike Remapper.exe`. Python/Tk/MIDI support is included. |
| Mac or Linux | [Source beta artifact](https://github.com/Coober666/strike-pro-remapper/actions/runs/38624534354/artifacts/11923642271) | Extract both ZIP layers. Use Python 3.10+ with Tk: Mac `launch-host.command`, or `python3 launch_editor.py` from the application folder. See [source setup](BETA_START.md) and [Tk/terminal help](HOST_LAUNCHER.md#first-run-help). |
| iPad or iPhone browser | Use one of the host downloads above | Enable Wi-Fi on the host before starting, then scan its pairing QR on the same trusted network. Open the HTTP address. The host serves the editor; see [mobile setup](WIFI_EDITOR.md). |

GitHub's outer artifact ZIP contains an application ZIP and its checksum sidecar.
Extract the application ZIP too; do not run from either ZIP preview. These artifacts
are scheduled to expire on November 13, 2026. After expiry, use a newly verified build
with its own revision and checksums, not these hashes with a different download.

The application still opens in your browser. The small host window manages startup,
library selection, pairing and Stop. Windows detailed help is in `Help/README.txt`.

### Exact application ZIPs and SHA-256

Windows filename:
`strike-remapper-windows-x64-d56baecb53a1d537f13c8646f07317f488aee3d2.zip`

```text
9a5099b14797531fef7cd36a9a2e649427001468d935abbc7d85efc08f69c61b
```

Source filename:
`strike-remapper-d56baecb53a1d537f13c8646f07317f488aee3d2.zip`

```text
8fcede67162b0cde1d2869db8a6ce01df622daf3c72e3c1aa868c5edc343f53b
```

Compare the inner application ZIP with its sidecar using Windows
`Get-FileHash -Algorithm SHA256 <zip-path>`, Mac `shasum -a 256 <zip-path>`, or
Linux `sha256sum <zip-path>`. Quote paths containing spaces. These are the CI artifact
hashes; separate local builds have different hashes. A checksum verifies matching
bytes, not publisher signing.

## First test in ten minutes

1. Choose an empty library or a copy, outside the extracted application folder.
   Keep the original library and backup separate.
2. Choose **Try a demo**. In Drum MIDI toolkit, name the synthetic take and Save.
   Wait for **Saved in this browser**, reload, and reopen that saved take.
3. Export its session backup. Find the downloaded file, restore it, and confirm a
   new copy with the same event count and notes appears. Reusable pad profiles are
   exported separately; the host library is a third separate backup.
4. Open the editor and create a disposable kit. Change one pad parameter, Save,
   then reopen it and check the value. Save writes the selected host library.
5. Export its kit bundle. Find the ZIP in Downloads/Files. Read any missing-assets
   warning; an incomplete bundle is not a complete backup. **Export kits to JSON**
   creates a saved-kit report, not an importable kit backup.
6. Leave another disposable edit unsaved, use normal **Stop**, restart with the same
   library, and check the recovery entry and value. Record the result rather than
   assuming a passing automated test proves this machine's behavior.

Record build, OS/browser, expected and actual results using the
[acceptance form](HANDS_ON_ACCEPTANCE.md#result-form). For mobile testing continue
with H1; playing/mapping and listening are H2 and H3. Deployment and interruption
checks have separate procedures and test-media requirements.

## What changed in this candidate

- Windows folder beta bundles its runtime and MIDI dependency, with one-click host
  startup, pairing and readable offline help.
- Setlists include local sample checks and collection previews. Kit Balance offers
  bounded sample estimates, audition and explicitly selected one-step Undo changes.
- Saved MIDI sessions reject stale-tab overwrites and offer Save as new copy;
  disconnected takes retain their received events and partial status.
- CSV and ZIP imports validate before applying changes and explain partial/uncertain
  outcomes. Existing ZIP conflicts are preserved; failed uploads do not auto-retry.
- Bundle exports keep kit/dependency state consistent, prefer edited library sounds,
  report missing assets and retain the editor after download failures. Saved-kit JSON
  reports include valid kits and identify skipped files.

## Updating and rolling back

Save, Stop and close the old host. Copy the entire library to a dated backup; export
browser MIDI sessions and reusable profiles separately. Extract the new application
to a new folder, launch it, and select the same external working library. Keep the
old application and untouched backup until checks pass. For rollback, stop the new
host and run the previous application against a fresh copy of the pre-upgrade backup.
Do not overwrite your only library or delete it with the old application folder.

## Known limits and reporting

This build is unsigned and updates are manual. Windows may show an unknown-publisher
warning; do not disable security protections. Independent Windows installation/USB,
newest physical mobile workflows and listening acceptance remain open. Linux/Pi
hardware compatibility is unverified. Generic MIDI tools do not establish kit-file
editing support for Command or Nitro modules.

Setlist batch deployment is disabled. Kit Balance measures bounded local sample
windows, not the module's complete sound. ZIP publication is not a crash-atomic
multi-file transaction. Intermittent Strike media stalls remain unresolved even
though reads have retry protection. See the [issue and release review](RELEASE_REVIEW_2026-10-14.md).

For a failure, include the revision, host/mobile OS, browser, exact steps, expected
result and actual result. The editor's **Connection details → troubleshooting report**
provides limited support information. Review any other logs before sharing them;
leave out pairing tokens, private audio and personal library contents.
