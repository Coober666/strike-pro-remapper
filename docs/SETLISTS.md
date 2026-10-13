# Prepare a show with Setlist Builder

Open **Setlist Builder** from Start or the Kits menu. It works without the module and
through the paired Wi-Fi editor on iPad/iPhone. Use the browser that has editing control
to save lists, create kit copies or run local checks.

1. Name your setlist, choose a saved library kit, and select **Add to setlist**.
2. Add the song title and any notes. The same kit can appear in several songs.
3. Use Up/Down on touch screens or drag the order handle to arrange the show.
4. Optionally supply output names and enable three-digit numbering. These are planned
   filenames only; reordering and numbering never rename or change source kits.
5. Use **Check saved kits** to preview filenames and flag problems. Then **Save setlist**
   to keep the list in the host library and **Print show sheet** for a printable summary.
   The print tab includes a Print / save PDF button, order, notes, planned filenames and
   the local validation snapshot.

## Song-specific kit edits

Use **Copy kit for song**, enter a new name, and create the copy. The app copies the
saved kit's exact bytes into `library/kits/` and updates that song's setlist draft.
Save the setlist, then use **Edit kit** to open the copy in the normal editor. Kit
switching retains the existing editor recovery behavior. Unsaved kit edits are not
included in copies or local checks; save those first if they belong in your show.

Kit-copy names use up to 22 ASCII letters, numbers, spaces, hyphens or underscores,
plus `.skt`. Existing names, including case-only variants, cannot be overwritten.

## What local checks establish

- The saved kit is present inside this library and can be parsed/rebuilt exactly.
- Assigned instrument indices and paths are structurally valid.
- Instrument references have local `.sin` or positive factory-catalog evidence, or are
  explicitly unverified. A catalog miss never establishes that a sound is absent.
- Planned filenames are at most 26 characters including `.skt`, use conservative ASCII
  and avoid reserved device names. Unsupported characters are removed in the preview;
  duplicate names after shortening/sanitizing are flagged. Numbering uses 001–128.

Checks never read a card, enumerate devices, read WAV samples or replace the active kit.
They do not verify sample completeness, total sample size, card space, existing card
files or actual module playback. A local pass is not deployment approval. Printing shows
the last check snapshot; run checks again after editing or copying kit files elsewhere.

**Batch setlist deployment is not included.** Deploy individual kits through the normal
editor, with its actual card preflight and confirmation. Planned setlist names are not
automatically applied by individual-kit Deploy. Issue #28 remains open for integrating
the deploy pipeline and testing interruption, backup and restore with disposable media.

## Save, transfer and recovery

Saved lists are human-readable version-1 JSON in `library/setlists/<id>.json`. They
reference kits relative to `library/kits/`; no machine-specific path is exported.
The host shares saved lists with its paired clients, independently of MIDI sessions
which live in each browser. Keep the whole library backed up when upgrading.

**Export JSON** downloads the current draft, including unsaved edits. It does not bundle
kits, instruments or samples. Copy those separately with the same relative layout.
**Import JSON** validates the complete document and opens a new draft; it never replaces
an existing saved list. Missing kit references stay visible so you can restore the files.
**Duplicate setlist** also creates a draft and does not duplicate its referenced kits.
**Delete setlist** removes only the list; kit files stay in the library.

Setlists require explicit Save. Their unsaved drafts are separate from kit recovery and
do not survive a closed/reloaded page. Close/switch and browser navigation warn about
unsaved changes. Export before changing pages if a host save fails.

If another page changed a list, a stale save/delete is rejected. Export your draft,
refresh the saved lists, then reopen the latest version or import your export as a new
list. A lost network response does not prove that a save/copy failed: refresh and inspect
the host before repeating it. The app never retries these writes automatically.

Limits: 50 saved lists per library, 128 songs per list, 1 MB JSON import/request. The
kit picker shows at most 2,000 saved kits. Local checks limit individual metadata files
to 2 MB and reject recovery files, traversal paths and linked library files.

## Verification

Automated tests use synthetic local files and simulated browsers. They cover original
kit preservation, exact copies, atomic-write failure, revisions, path restrictions,
missing/corrupt kits, duplicate outputs, import/export/print, drag/touch ordering and
paired editor ownership. Physical iPad/iPhone interaction and batch deployment remain
release acceptance work; no new module-write claim is made by these tests.
