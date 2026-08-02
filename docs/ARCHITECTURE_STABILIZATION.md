# Architecture stabilization roadmap

The remapper remains a clone-and-run Python application with no third-party runtime
dependencies. Its source may be split into focused modules as those boundaries become clear.

## Measured baseline

- `strike_remap.py` is 12,308 lines on the initial baseline.
- 7,287 lines are the embedded UI: 5,541 JavaScript and 1,131 CSS.
- The Python portion contains roughly 150 top-level functions.
- Static dependency analysis found 79 transitively pure functions (about 1,411 lines) and
  71 stateful functions (about 1,823 lines).

The immediate risk is therefore insufficient behavioral coverage around a large embedded
frontend. Backend decomposition follows, but it does not require treating every function as
stateful.

## Phase 1: browser and JavaScript safety net

- Run pinned Playwright/Chromium tests against the real embedded application.
- Cover startup failure recovery, modal isolation, focus restoration, keyboard shortcuts,
  sync confirmation, quoted paths, recent-kit loading, and the 620px breakpoint.
- Extract embedded JavaScript to a temporary build directory and lint that exact artifact.
- Preserve the existing viewer extraction and single-file bundle checks.

## Phase 2a: mechanically extract pure clusters

Move transitively pure code without redesigning behavior:

- `.skt` and `.sin` parsing, building, and patching.
- Audio/DSP helpers: WAV reading, normalization, waveform calculation, FFT, and fingerprint
  feature extraction.
- Volume classification and device-identity comparison, separate from physical discovery.

Existing byte-equality, parser parity, fingerprint, and volume-classification tests remain
mandatory gates. If Python tests move out of `tools/test_*.py`, CI auto-discovery and its
non-empty guard must change in the same PR.

## Phase 2b: state boundary and stateful services

- Introduce an `AppState` compatibility boundary before moving stateful services.
- Pass only the state and paths a service needs; do not relocate the global dictionary under
  a new module name and call that separation.
- Then extract library management, recents, recovery, relinking, deployment, and playback in
  small behavior-preserving changes.

## Phase 3: hardware boundary

- Define an explicit interface for discovery, reads, writeability, retries, and removal.
- Simulate stalls, drive-letter changes, removal, reconnection, and permission failures.
- Keep real Strike hardware verification in the release checklist.

Pure card classification moves in Phase 2a; physical I/O behavior belongs here.

## Phase 4: API separation

- Convert endpoints into ordinary validated functions returning serializable results.
- Restrict the HTTP handler to request decoding, dispatch, error translation, and encoding.
- Test endpoint behavior without binding a socket where practical.

## Separate product RFC: UI source direction

The embedded UI remains the source of truth. Moving it to `web/app/` and generating the
runtime UI would add another generation hop and change the review model, so it is not part of
stabilization. Any such change requires a separate product decision.

## Delivery rules

- Keep `main` releasable after every PR.
- Separate mechanical extraction from behavioral changes.
- Do not impose a blanket feature freeze; avoid only changes that overlap an active extraction.
- Never weaken byte-for-byte format tests or generated-viewer drift gates.
