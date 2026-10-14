# October 14 release candidate review

The combined candidate `d56baec` passed all ten push/PR CI checks and the downloaded
CI artifacts passed independent checksum, payload and runtime checks. No additional
blocking integration defect was found in the reviewed boundaries below. This supports
controlled beta testing; the device acceptance gates remain open.

The [beta handoff](BETA_CANDIDATE_2026-10-14.md) pins the exact downloads, hashes,
install/upgrade steps, changes and first-test procedure. This review is a later
documentation addition; it does not relabel those artifacts as a newer build.

## Stack and integration

| Reference | Reviewed revision | Relationship |
| --- | --- | --- |
| main | `5418487db1ef4675e8777e3a531729d29bd75576` | Exact merge base of candidate |
| [PR 66](https://github.com/Coober666/strike-pro-remapper/pull/66) | `28574d0f56850f6d3e84522185a42d84067a693f` | Based on main |
| [PR 67](https://github.com/Coober666/strike-pro-remapper/pull/67) | `65faa2132bd0a27868f1174b1404510970a9cf96` | Contains PR 66 head |
| [PR 68](https://github.com/Coober666/strike-pro-remapper/pull/68) | `d56baecb53a1d537f13c8646f07317f488aee3d2` | Contains PR 67 head and final runtime fixes |

Git ancestry checks passed for both stack edges; GitHub reported all three PRs
mergeable/clean on October 14. The candidate contains 19 commits and 64 changed files
relative to the reviewed main. Review focused on launcher/runtime routing, package
contents, persistence boundaries, host guards, exports and release claims.

| Boundary reviewed | Finding and evidence |
| --- | --- |
| Source versus frozen workers | `runtime.py` selects Python modules or the bundled helper; the helper dispatches named operations and three allowlisted utilities. External library validation precedes utility execution. Runtime tests and extracted Windows checks cover these paths. |
| Packaging and first run | CI package jobs depend on Python, browser and Windows-host gates. Application payloads exclude user libraries; source command launchers retain LF and executable metadata. Actual CI source pairing/assets and Windows GUI/runtime checks passed. |
| Host and Wi-Fi | Source/frozen library guards coexist; query-aware MIDI routing preserves pairing guards. The backlog change does not change authentication. Existing stale-writer, restart, recovery and host tests pass on the candidate. |
| MIDI persistence | IndexedDB revision comparisons and writes share one transaction; legacy records default to revision zero. Save as new copy creates a new ID. Profile confirmation rechecks are narrower localStorage protection, not an atomic multi-tab transaction. Existing conflict/abort/restore tests passed in CI. |
| Balance and setlists | Balance revalidates evidence before selected edits and uses existing Undo. Dialog/preview generation guards prevent stale UI results. Setlist checks remain local previews with `writes_enabled: false`; catalog presence does not prove factory samples or card capacity. |
| Imports and exports | ZIP preflight and exclusive creation preserve existing files; later write failures report completed work. Bundle construction holds the editor lock, transfer releases it, and JSON reports use saved bytes. Exact restore, disconnect, lost-response and browser tests passed. |
| Backup boundaries | Host library, browser sessions and reusable profiles have separate backup instructions. Kit JSON is explicitly a report; bundles report missing assets and do not include the whole library. |

### Integration procedure when merging is authorized

The repository permits merge commits and automatically deletes merged branches.
Use merge commits to preserve the ancestry of this stack:

1. Recheck current heads, required checks and main for intervening changes.
2. Merge #66. Ensure #67 targets main after the base branch is removed or retarget
   it explicitly; inspect its refreshed diff and checks before merging #67.
3. Ensure #68 targets main, inspect its refreshed diff and checks, then merge #68.
4. Verify main contains all three reviewed heads. Wait for CI on the resulting main
   revision and build/download new candidate artifacts for that revision.
5. Record new hashes and acceptance results before replacing the pinned handoff or
   publishing a release. The d56baec hashes cannot identify a new merge build.

If squash/rebase merging is chosen instead, rebase the dependent PRs deliberately;
merely retargeting a stack with rewritten ancestry can leave misleading diffs.
No merge, branch deletion or release publication was performed for this review.

## Open issue reconciliation

All eight currently open issues retain real uncompleted scope; none should be closed
solely because this candidate passes CI. The repository roadmap links this matrix.

| Issue | Implemented or evidenced | Remaining completion condition |
| --- | --- | --- |
| [28 Setlist Builder](https://github.com/Coober666/strike-pro-remapper/issues/28) | Local lists merged in #65; #66 adds sample checks/collection preview; #68 improves focus. | Batch deployment through normal preflight, destination capacity/collisions/layout, factory sample completeness, disposable-media restore, mobile and playback acceptance. Keep open. |
| [29 Kit Balance](https://github.com/Coober666/strike-pro-remapper/issues/29) | #66 implements bounded analysis/audition/selected Undo; #68 prevents stale preview/analysis UI. | Real-library listening, A/B and overlapping layers on the module, physical mobile audio/download acceptance (H1/H3). Keep open. |
| [35 SD read stalls](https://github.com/Coober666/strike-pro-remapper/issues/35) | Retry/backoff and discovery protection predate this stack; bundle export now uses the retry reader. | Sustained hardware comparisons and disposable-media interruption/restore. The recorded outage also occurred with the official editor open; opening it is not a guaranteed fix. Keep open. |
| [30 Trigger Coach](https://github.com/Coober666/strike-pro-remapper/issues/30) | Input capture, analysis, profiles, notes and comparison are implemented; limited Mac/Strike capture is evidenced. | Advisory logic with defensible observations, sample sufficiency and uncertainty, plus physical input acceptance. MIDI alone cannot establish missed physical hits. Keep open. |
| [54 Windows/Linux activation](https://github.com/Coober666/strike-pro-remapper/issues/54) | Explicit activation and Mac evidence exist. | Real Windows/Linux transport and module verification; simulated tests do not close it. |
| [56 Mobile browser acceptance](https://github.com/Coober666/strike-pro-remapper/issues/56) | Wi-Fi editor implemented; earlier physical iPad save/deploy/playback is recorded. | H1 on current iPad/iPhone: touch, orientation, audio, pairing, Downloads/Files and reconnect. Earlier evidence does not accept later changes. |
| [57 Pi host spike](https://github.com/Coober666/strike-pro-remapper/issues/57) | Reusable paired host and MIDI toolkit exist. | Pi inventory/coexistence, real ALSA/USB/storage checks, deployment and rollback assessment (H7). |
| [55 Direct iPad USB spike](https://github.com/Coober666/strike-pro-remapper/issues/55) | Separate feasibility criteria are documented. | Owner-paused work; requires resumption and its hardware feasibility evidence. |

## Verified candidate gates

- [x] Both CI workflows passed: [push run](https://github.com/Coober666/strike-pro-remapper/actions/runs/38624534354)
  and [PR run](https://github.com/Coober666/strike-pro-remapper/actions/runs/38624541583).
- [x] Downloaded the push-run artifacts; inner ZIP SHA-256 sidecars match and every
  manifest payload hash matches: 1,045 Windows files and 71 source files.
- [x] Extracted CI Windows runtime uses bundled Python 3.11.9, Tk 8.6 and MIDI 1.5.8;
  GUI/demo, pairing, helper, save/recovery, bundle import/export and JSON report passed.
  Python was removed from the child PATH; no MIDI input/output port was opened.
- [x] Extracted CI source starts with an external temporary library and serves the
  paired editor/MIDI assets. Source Mac launcher metadata is executable with LF endings.
- [x] Existing automated recovery, stale-writer, import/export, setlist, MIDI storage,
  format round-trip, parser parity, lint and generated-viewer gates pass in CI.
- [ ] Independent Windows installation and connected-module acceptance (H6).
- [ ] Physical mobile, playing and listening sessions (H1-H3).
- [ ] Authorized reconnect and disposable-media failure/restore sessions (H4-H5).
- [ ] Pi, other modules and outside-user acceptance as scoped (H7-H9).

The generic [release checklist](RELEASE_CHECKLIST.md) remains a template for the final
release revision; these checked entries apply only to d56baec. No extra runtime test
runs are needed for this documentation-only review unless a new failure is evidenced.
