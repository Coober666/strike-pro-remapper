# Local code and shared Strike files

Keep a separate local Git checkout on each development computer. Use GitHub for
committed changes and branches; builds, dependency caches and simulator data stay
on local storage. Do not put a live checkout or its `.git` directory in a shared
SMB folder or a two-way file-sync job. Push work before changing computers and
pull the intended branch before continuing. GitHub does not contain uncommitted
edits, ignored files, personal signing choices or the sound library.

## NAS layout

An existing NAS share can hold this additive layout:

```text
Media/Music/Strike/
  library/
    kits/             .skt kits, retaining relative subfolders
    instruments/      .sin files, retaining relative subfolders
    samples/          WAV files, retaining relative subfolders
    setlists/         version-1 Setlist Builder documents
  exports/
    kits/
    setlists/
    bundles/
  incoming/Windows-desktop/   staging, not an active library
Backups/Strike Remapper/
  source/             versioned Git/worktree snapshots
  library/            versioned library backups
```

Identify the original library before copying content. Preserve originals, relative
paths, filenames and every existing destination. Stage each import under a new
directory and compare bytes before publishing it; differing same-name files need
an explicit choice or a new name, never an overwrite. Do not use a mirror/delete
sync command. Avoid combining several libraries automatically: string references
and case differences can identify different sounds. No module/card discovery is
needed for storage setup.

iPad Files can connect to the NAS using **Browse → More → Connect to Server** and
the existing NAS account. Connect while on a network that can reach the NAS. Copy
needed files onto the device for offline use. Companion imports a local document;
an open document does not automatically track NAS changes. Shared-provider editing,
conflict resolution and offline synchronization are separate app work. Export fresh
copies and avoid simultaneous edits to the same shared file. The desktop host should
keep its active working/recovery library local until NAS provider behavior is tested.

## Source backup

Time Machine or another versioned computer backup should include local source and
unfinished work. Check this independently of GitHub. A NAS copy does not replace an
independent backup of the NAS itself.

For an additional explicit source snapshot:

```sh
python3 tools/backup_source.py --repo /path/to/local/checkout \
  --destination "/path/to/mounted-share/Backups/Strike Remapper/source" \
  --require-mount "/path/to/mounted-share"
python3 tools/backup_source.py --verify "/path/to/new/snapshot"
```

The standard-library helper records all registered worktrees, a verified Git bundle
of all refs, current source archives, staged/unstaged binary patches and status. It
includes non-ignored untracked work and preserves symlinks without following them.
Ignored libraries, credentials, build products and simulator data are excluded;
back these up separately if needed. Keep snapshots private because tracked local
settings may include personal signing changes. It does not push, pull, commit,
checkout or delete source files. It refuses linked backup destinations and a missing
required mount, creates a new uniquely named snapshot, verifies archived bytes and
NAS read-back SHA-256 hashes, and writes the completion manifest last. Mount
validation uses the platform `os.path.ismount` check plus an accessible-directory
check, including mapped drive roots and UNC share roots on Windows/Python 3.10+.
A disconnected Windows root is rejected even though its pathname identifies a mount. Handled failed
publication retains a marked incomplete snapshot. An interrupted or disconnected
write may leave partial data; only a fully verified snapshot is eligible for restore.
There is no automatic pruning or retry. Before/after source checks detect changes;
this is not a filesystem freeze or an atomic multi-file capture during active editing.

Restore into a **new local folder**, never over a current checkout. Clone
`repository.bundle`, check out the recorded worktree HEAD, apply that worktree's
`index_patch` with `git apply --index`, then `working_patch` with `git apply`.
Recover non-ignored untracked files from its `source.tar.gz` after inspecting paths
and links. The source archive also provides a complete source view without Git
metadata. Compare the restored files before using them. The disposable regression
test performs an actual bundle clone and patch restore, checks a second worktree,
untracked work and ignored-file exclusion, and detects altered backup artifacts.

Machine paths, NAS addresses, accounts and setup receipts belong in private local
configuration or the NAS instructions, not repository commits. The helper runs when
explicitly invoked; existing computer-backup scheduling remains independent.
