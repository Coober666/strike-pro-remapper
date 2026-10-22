# Preparing beta downloads

The **Prepare beta draft** Actions workflow promotes the two packages from one
successful main-branch push CI run. It does not rebuild them. It creates a new
**draft prerelease**, never publishes it, and never updates an existing release.
Ordinary pushes and PRs cannot trigger it. The workflow must first be merged to main.

## Maintainer procedure

1. Finish review and merge the intended changes. Wait for all eight jobs on that
   main push: Python tests on Linux and macOS, source-backup tests on Windows
   Python 3.10 and 3.11, browser tests, Windows host, source beta and Windows beta.
2. In Actions, select **Prepare beta draft**, choose main, enter the numeric CI run
   ID and a new tag such as `beta-20261014.1`. Selecting Run workflow authorizes
   preparation of a draft only. Do not use a PR run or an expired artifact.
3. Review the resulting draft in Releases. It includes two clearly named ZIPs,
   `START-HERE.txt`, `SHA256SUMS.txt` and `BUILD.json`. Both ZIPs retain their exact
   CI bytes and embedded revision. The source ZIP requires Python; the Windows x64
   ZIP bundles its runtime. The draft is not a public download page yet.
4. Replace the maintainer section in the draft notes with the actual changes and
   acceptance results for that revision. Check the attached downloads and their
   hashes. Record remaining device limitations accurately.
5. **Publish only after separate approval.** Keep it a prerelease. Then link that
   exact release page from the README; do not present an unpublished draft as a
   usable public download or use `/releases/latest` for a beta.

The workflow rejects unsuccessful/skipped required jobs, other repositories,
non-main/non-push runs, expired/missing artifacts, modified or mismatched package
identities, checksum/payload failures and reused tags. Creation fails if a release
already exists. If upload is interrupted, inspect the incomplete draft and staging
artifact before taking further action; there is no automatic retry or deletion.
Before publishing, verify that any existing tag resolves to `BUILD.json`'s revision.

Promotion explicitly requires both Python platform lanes and both Windows
source-backup lanes, using their full matrix job names. Backup/restore behavior
is part of the source release contract even though successful run status also
requires those jobs. A missing, duplicated, failed or skipped lane blocks promotion.

The separate prepare job has read permissions; only draft creation gets repository
write permission. Inputs are passed through environment variables and argument
arrays. The downloaded applications are inspected as data, never executed by this
workflow. CI already owns executable/runtime tests.

## Local preparation without creating a release

Use Python 3.11+ and an authenticated GitHub CLI with repository Actions access:

```text
python tools/prepare_release.py --run-id 38628752928 --tag beta-20261014.1 --output .build/beta-review
```

Use an output folder that does not exist. This command downloads artifacts,
checks their provenance, verifies the inner ZIP sidecars and every payload hash,
then writes the review folder. It performs no GitHub mutation, tag creation or
publication. Change the run/tag for a newer candidate. Artifact expiry still applies.

## October 14 rehearsal

Local preparation against actual main CI run `38628752928`, revision `45c210d`,
passed. The renamed source ZIP retained SHA-256
`eeb64ff25ccbf857f1ce0bd372a5cb31ace9bec5a61d6ddbe8ae524b6bbac559`;
Windows retained `b929daf929e5c029b9ac4f99dfea6b769210ab848b4c447b52a1624edca364f0`.
All embedded file hashes and clean-build identities matched. This is a local
preparation rehearsal, not an executed GitHub draft workflow or a published beta.
It does not include later accessibility or Trigger Coach changes.

The workflow follows GitHub's [artifact download](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)
and [`gh release create`](https://cli.github.com/manual/gh_release_create) interfaces.
