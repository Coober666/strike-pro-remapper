# Fresh-Start QA Playbook

A mock "brand-new user" acceptance test for Strike Pro Remapper, designed to be **run as an
interactive Claude Code session** on a Mac with the Strike Pro module available. It verifies
that a stranger cloning the public repo can succeed with nothing but the README — first with
no hardware at all, then with the module connected over USB, then offline again against the
synced library.

**Hardware/setup assumed:** MacBook (macOS) for Phases A–B, a **Windows desktop** for
Phase C (full independence + Windows coverage), the module's USB-B → USB-C cable, the
module with its SD card installed, Google Chrome installed on both machines (any default
browser is fine — that's part of the test). Python 3.10+ and Claude Code on both machines.

**Time budget:** ~3–4½ hours for a full two-run pass. Phases are independent enough to
split across sessions; finish any phase you start (some steps deliberately leave state for
later steps). The two slow data moves (SD backup, library sync) both live in Phase B —
start them first when you sit down.

**Remote/unattended execution:** Phase A0 (cloud pre-flight) runs with no human and no
target machine at all. Within Phase A, only steps tagged `[DISPLAY]` need a human at a
real screen — everything else is headless-safe and can run early via SSH to a home
machine, or in a cloud session against a fresh clone.

---

## 0. Roles, protocol, and rubric

### Roles

| Role | Who | Does |
|---|---|---|
| **Manager** | Fable (the main session agent) | Plans and dispatches steps, maintains the findings log, adjudicates pass/fail, reviews all subagent output against this checklist, writes the final report |
| **Fresh-eyes user** | Opus subagent | Gets **only** the README and the localhost URL — nothing else, no source, no CLAUDE.md. Attempts the tasks a new user would, narrating first impressions and keeping a friction log. Its confusion is data, not error |
| **Executors** | Sonnet subagents | Mechanical work: Playwright walkthroughs + screenshots, API smoke probes with `curl`, running the repo's own test suite, file comparisons, evidence collection |
| **Hands & ears** | The human | Everything physical or audible: cabling, SD eject/insert, module screen reads, "what do you hear" verdicts, drumming |

Every checklist step is tagged:
- `[AGENT]` — agents do it end-to-end
- `[HUMAN]` — requires the human's hands, eyes on the module, or ears
- `[PAIR]` — agent drives, human observes/confirms (e.g. agent clicks Preview, human reports what played)

For `[HUMAN]` audio steps, the manager must ask a **specific, closed question** ("did you hear
two distinct hits or one?", "is the second hit brighter?"), never "does it sound right?".

### Two-run protocol

- **Run 1 — everyone blind.** No agent (manager included) reads the source, CLAUDE.md,
  FORMAT.md, or PLANNED.md. Only public-user surfaces: README, the running app, error
  messages. Failures are logged as **symptoms, verbatim** — no diagnosis, no fixing.
- **Run 2 — manager informed.** The manager may now read everything. Re-run every Run 1
  failure or friction item, plus any checklist item Run 1 skipped. Classify each finding.
- **Reconcile.** Merge both logs into the final report (§6).

Run 2 does not need to repeat steps Run 1 passed cleanly, except the core round-trips
(A4, B5, C3), which are always run twice.

### Severity rubric

| Severity | Meaning |
|---|---|
| **Blocker** | Data loss/corruption, or a new user cannot complete the README quick start |
| **Major** | A promised feature is broken, or behavior contradicts the README |
| **Minor** | Works, but confusing, mislabeled, or needs undocumented knowledge |
| **Polish** | Cosmetic, wording, layout |

### Finding format

Each finding gets: `id` (e.g. `A3-2`), phase/step, severity, symptom (verbatim message or
screenshot), expected behavior, evidence path, Run 2 classification — one of **bug**,
**doc gap**, **UX friction**, **known limitation** — and proposed action (fix / file issue /
patch docs / accept).

### Exit criteria (release gate)

- **0 Blockers.**
- Every Major triaged into a GitHub issue or fixed.
- README quick start passes **verbatim** on a machine that has never seen the project.
- The lossless byte-identity checks (B5c, and the untouched-kit `cmp`) pass.
- Fresh-eyes verdict (D3) answers "yes" to: *could a stranger articulate what this app is,
  why it exists, and complete a basic kit edit within ~10 minutes, unaided?*

---

## 1. Preconditions & environment reset

The point is **fresh**. The developer's machine has years of contamination; neutralize it.

- [ ] `[AGENT]` Clone the public repo into a brand-new directory (not the dev checkout):
      `git clone https://github.com/Coober666/strike-pro-remapper ~/qa-fresh/strike-pro-remapper`
- [ ] `[AGENT]` Verify freshness: `library/` does **not** exist in the clone, `dist/` does
      not exist, no `.autosave.skt` anywhere.
- [ ] `[AGENT]` `python3 --version` ≥ 3.10; note the exact version in the log.
- [ ] `[AGENT]` Confirm nothing is listening on port 8765 (`lsof -i :8765`) — kill any dev
      instance first.
- [ ] `[HUMAN]` Note the Mac's default browser (this is what the first launch will open).
- [ ] `[AGENT]` Prepare a **fresh Chrome profile** for all Chrome testing:
      `open -na "Google Chrome" --args --user-data-dir="$HOME/qa-fresh/chrome-profile"` —
      the daily profile carries `strike_*` localStorage (pad overrides, favorites, theme)
      that would contaminate first-run behavior.
- [ ] `[AGENT]` Create the evidence directory: `~/qa-fresh/evidence/` (screenshots, logs,
      findings.md live here).

**SD backup gate — mandatory before Phase B.** When the card first mounts (Phase B step B1):

- [ ] `[PAIR]` Copy **both** volumes to the Mac:
      `cp -R "/Volumes/NO NAME" ~/qa-fresh/sd-backup-$(date +%Y%m%d)/user/` and the same
      for the preset volume.
- [ ] `[AGENT]` Verify the backup: file count and total size of each copy match the source
      (`find | wc -l` and `du -s`). **Abort all Phase B write tests if they don't.**

---

## 2. Phase A — no module, no SD (pure fresh start)

> **Tag key for this phase:** `[DISPLAY]` = needs a human at a real screen (first-run
> experience, OS prompts, visual judgment). Untagged `[AGENT]` steps are headless-safe.

### A0. Cloud pre-flight (optional, run any time, no hardware, no human)

A Linux cloud/CI session with the public repo, Python, and headless Chromium can
functionally smoke most of Phase A before anyone is home. It **covers**: fresh-clone
verification, server start, all empty states, kit create/edit/undo/snapshot flows,
crash recovery, junk-zip/CSV rejection, the localhost 403 guard, the test suite, and the
viewer build + `file://` load. It **cannot cover** (defer to at-home): macOS/Windows
launch scripts and their OS prompts, the default-browser auto-open, Safari behavior,
audio, and any judgment about how the experience *feels*. Findings from A0 go in the same
log with phase id `A0`; at-home Run 1 then only needs the `[DISPLAY]` steps plus anything
A0 flagged.

### A1. First launch

- [ ] `[PAIR]` `[DISPLAY]` Follow the README quick start **verbatim** (clone →
      `python strike_remap.py`). Note: README says `python`, macOS ships `python3` — does a
      fresh Mac user hit `command not found: python`? Log exactly what happens.
- [ ] `[HUMAN]` `[DISPLAY]` Quit, then launch via double-clicking `launch.command`. Log any
      Gatekeeper / "unidentified developer" / quarantine prompt and whether a normal user
      could get past it.
- [ ] `[AGENT]` Confirm the terminal prints the startup lines (URL, SD-card hint, Ctrl-C
      hint); `[DISPLAY]` confirm the **default browser** auto-opens to
      `http://localhost:8765`.
- [ ] `[PAIR]` `[DISPLAY]` If the default browser is Safari: confirm the app loads and
      works, and note every message a Safari user sees when touching MIDI features ("Web
      MIDI requires Chrome or Edge" toast). This is the true first-run experience — judge
      it as such.

### A2. Empty states (fresh-eyes walkthrough — Opus, blind)

- [ ] `[AGENT]` Instruments panel shows **"No instruments found."**
- [ ] `[AGENT]` Status chip shows **"⚠ User card NOT mounted"**; Save menu hint says to
      mount the user card.
- [ ] `[AGENT]` Save / Save-to-SD / Duplicate / Clear all pads / Undo all start disabled.
- [ ] `[AGENT]` Pad-detail area shows the "Load a kit, then click a pad" placeholder.
- [ ] `[AGENT]` `[DISPLAY]` Fresh-eyes verdict: from this screen alone, is it clear what to
      do next? (This is the moment a new user without an SD card decides whether to keep
      going.)

### A3. Create and edit a kit from nothing

- [ ] `[AGENT]` Kits ▾ → **+ New kit from scratch** → name it → Create. Kit loads, 24 pads
      render on the drum map, kit-size badge appears.
- [ ] `[AGENT]` Kits ▾ → **New from template… → Metal Baseline** with the empty library.
      Expected: graceful, comprehensible failure (it needs library instruments). Log the
      actual message — a stack trace or silent no-op is a finding.
- [ ] `[AGENT]` Click pads: selection glow, detail panel populates; arrow keys ←/→/↑/↓ walk
      pad groups; Esc clears selection.
- [ ] `[AGENT]` Edit params on a pad (level, pan, pitch, decay, MIDI note); dirty badge
      (`● Unsaved`) appears; each edit lands in undo history (▼ next to Undo) with a
      readable label; Ctrl/⌘+Z undoes; Ctrl/⌘+S saves to library.
- [ ] `[AGENT]` **Duplicate…** → save a copy; both kits appear in the Kits menu with their
      source labels. Rename the kit via the inline name field in the Drum Map header
      (Enter commits, Esc reverts).
- [ ] `[AGENT]` Kits ▾ → **📤 Export kits to JSON** and **🖨 Print MIDI map** — both produce
      sensible output for the from-scratch kit (the MIDI map sheet is readable/printable).
- [ ] `[AGENT]` **Clear all pads** → themed confirm dialog (Enter confirms / Esc cancels) →
      then Undo restores.
- [ ] `[AGENT]` Pad layout editing: drag a pad, resize/rotate via gold handles (Shift snaps),
      change a shell finish, **Save layout** → **Load layout** round-trips the JSON file,
      **Reset layout** restores defaults.

### A4. Persistence & crash recovery

- [ ] `[AGENT]` Kit time machine: **📸 Snapshot now**, make edits, snapshot again, scrub the
      timeline, **Diff** two points (readable per-pad diff), **Restore** an older point —
      and the restore itself is undoable.
- [ ] `[PAIR]` Crash recovery: make edits, do NOT save, wait ≥60 s (autosave interval),
      `kill -9` the server, relaunch. Expected: **"⚠ Unsaved changes found:"** banner with
      Recover; Recover restores the edits and points the save path at the original kit.
- [ ] `[AGENT]` Reload the browser tab mid-session: **"Restored session — <kit>"** appears
      and state survives (server-side memory, not localStorage).

### A5. Standalone extras (no hardware needed)

- [ ] `[AGENT]` Virtual module with no samples: toggle **Virtual**, press keys 1–0.
      Expected: graceful (no sound but no crash/console spew). Log what actually happens.
- [ ] `[AGENT]` Theme toggle (☾) persists across reloads. `[DISPLAY]` Drag-drop a `.skt`
      file onto the window → drop overlay appears → kit loads (real OS drag, not a
      synthesized event).
- [ ] `[AGENT]` Import bundle with a **junk zip** (e.g. zipped text files): comprehensible
      error, no crash.
- [ ] `[AGENT]` Import assignment CSV with a malformed CSV: same standard.
- [ ] `[AGENT]` Repo's own suite on the Mac: `python3 tools/make_fixtures.py`, then the
      round-trip tests, `tools/test_fingerprint.py`, `test_time_machine.py`,
      `test_playback_manifest.py` — all green on macOS, not just Linux CI.
- [ ] `[AGENT]` Web viewer: `python3 tools/build_viewer.py` (plain build — should not need
      node; `--check` does). Double-click `dist/strike_viewer.html` (file://). Drop a `.skt`
      on it, browse the factory catalog, run "More like this". Verify read-only gating:
      no save/edit affordance dead-ends, mutating actions clearly absent or labeled.
- [ ] `[AGENT]` Security spot-check (README Safety claim): `curl -s -o /dev/null -w '%{http_code}'
      -H 'Host: evil.example.com' http://127.0.0.1:8765/api/kits` → expect **403**; same for a
      cross-origin POST with `Origin: https://evil.example.com` → **403**; normal requests 200.

---

## 3. Phase B — module connected (USB-B → USB-C)

### B1. Detection & the backup gate

- [ ] `[HUMAN]` Power the module, connect USB-B → USB-C to the Mac.
- [ ] `[PAIR]` Verify the composite-device assumption: does the SD appear under `/Volumes`
      as mass storage over USB? Log volume names. **If it doesn't mount over USB**, fall
      back to pulling the card into a reader — and file that as a doc-gap finding (README
      implies card-in-Mac workflows; the USB path is undocumented territory).
- [ ] `[AGENT]` **Run the SD backup gate from §1 now.** No write tests until it passes.
- [ ] `[AGENT]` Status chip updates without a restart: **💾 User: <path>** (+ preset chip if
      the second volume mounts); Save-to-SD becomes enabled; save-hint text updates.
- [ ] `[AGENT]` Volume classification is correct (user vs. preset — `NO NAME` / `NO NAME 1`,
      or positional fallback if renamed).

### B2. Browse & preview factory content

- [ ] `[AGENT]` Kits menu lists card kits with source labels; load a factory kit from the
      **preset** card.
- [ ] `[AGENT]` Attempt to save over a preset-card path. Expected: **"Cannot save over a
      preset file."** error, no write.
- [ ] `[AGENT]` On the loaded factory kit: the **`⚠ parser`** badge must be **absent**
      (lossless round-trip check passed), and the kit-size badge shows a plausible MB
      figure with a found/total WAV tooltip.
- [ ] `[AGENT]` With a pad selected, press **Space** — its assigned instrument previews.
- [ ] `[PAIR]` Instrument browser: search, expand groups, waveform thumbnails render.
      Preview an instrument at low/high velocity — `[HUMAN]`: "is the high-velocity hit
      louder/brighter than the low one?"
- [ ] `[AGENT]` Tags: add a tag inline, filter by chip; favorites star + Recents + sort modes.
- [ ] `[AGENT]` **"More like this" (≈)** on a factory instrument works **immediately** —
      no build step, no sample sync (baked fingerprints claim). Neighbours look plausible
      (a snare's neighbours are mostly snare-like).
- [ ] `[PAIR]` A/B blend preview on a two-layer pad — `[HUMAN]`: "do you hear both layers?"

### B3. Sync

- [ ] `[AGENT]` **💾 Sync kits from card**, then **⬇ Sync full library from SD**: progress
      bar runs to completion, no errors; spot-check `library/` file counts vs. card counts.
      Log elapsed time (this is a first-run UX number worth knowing).

### B4. Edit workflows against real content

- [ ] `[AGENT]` Load a factory kit, reassign a pad's Layer A from the browser, adjust the
      velocity crossfade by dragging, swap two pads, batch-edit (select several pads →
      apply one param), copy pad settings to another pad.
- [ ] `[AGENT]` Kits ▾ → **🔍 Compare with kit…**: diff the edited kit against its factory
      original — the per-pad diff lists exactly the edits made, nothing else.
- [ ] `[AGENT]` Kit FX editor: change reverb type/level, FX1 type, EQ gains — all undoable;
      the "inferred type names" caveat badge is visible.
- [ ] `[AGENT]` Instrument editor (⚙) on an **SD preset**: read-only badge shows, edits
      blocked. On a **library copy**: edit velocity zones (drag a split point), split a
      zone, add a round-robin, Revert restores the original.
- [ ] `[AGENT]` Relink wizard: rename a synced sample folder on disk → broken-path warning
      appears (⚠ count toast + pad glyphs) → **🔧 Fix broken paths…** suggests the right
      match → relink in one step → rename the folder back afterwards.
- [ ] `[AGENT]` Bundle: **📦 Export kit bundle (.zip)** → import it into a **second fresh
      clone** → kit loads with zero broken paths.

### B5. The core round-trip (highest-value test in the playbook)

- [ ] `[AGENT]` Duplicate a factory kit to the **user** card, make clearly audible edits
      (e.g. snare → cowbell on Layer A, kick pitch +12).
- [ ] `[AGENT]` **Save to SD card**, then verify: the file exists on the card; its autosave
      sibling is cleaned up.
- [ ] `[AGENT]` Lossless check on untouched content: `cmp` an **unedited** factory kit on
      the card against its copy in the §1 backup — byte-identical.
- [ ] `[HUMAN]` Eject cleanly, load the edited kit **on the module**: the edits are there
      (cowbell on snare, kick up an octave), everything else sounds unchanged, and the
      module shows no load errors. **This is the claim the whole project rests on.**
- [ ] `[HUMAN]` Also load one **untouched** factory kit on the module and confirm it's
      unaffected.

### B6. Chrome-only trio (fresh Chrome profile from §1)

- [ ] `[PAIR]` **MIDI monitor**: enable, `[HUMAN]` hits each pad/zone (heads, rims, cymbal
      edges/bells, hi-hat pedal) — each hit lights the right pad on the map with a
      plausible velocity.
- [ ] `[PAIR]` **Virtual module from the real pads**: toggle Virtual, wait for pre-decode,
      `[HUMAN]` plays. Closed questions: does the pad you hit make its assigned sound?
      Do fast rolls trip round-robin variation? Does the hi-hat choke when you close the
      pedal (CC#4)? Is latency playable or annoying? (README promises an editing aid, not
      perfection — judge against that.)
- [ ] `[PAIR]` **Trigger settings backup**: open the modal, `[HUMAN]` presses the module's
      trigger-settings Send; capture arrives, byte count shown, hex inspector renders;
      save `.syx`; reload the `.syx` from disk.
- [ ] `[HUMAN]` *(Optional, last, at your discretion — labeled experimental in-app)*
      **Restore to module** using the dump captured five minutes ago (never a foreign
      file). Confirm the module's trigger settings still behave (hit pads, check
      sensitivity feels unchanged).

### B7. Hot-unplug behavior

- [ ] `[PAIR]` With the app open, eject/unplug the card. Status chip flips to NOT mounted
      within a few seconds; Save-to-SD disables; previews of card-only WAVs fail
      **gracefully** (message, not console errors).

---

## 4. Phase C — offline against the synced library (Windows desktop + MacBook mini-C)

The founding use case: editing away from the kit, with no card and no module. Run **after**
B3's sync. The full offline workflow runs on the **Windows desktop** — a different machine
and OS gives true independence from the Phase A/B environment, exercises the documented
"copy `library/` between machines" path, and covers the Windows-specific code the MacBook
phases never touch.

### C1. Mini-C on the MacBook (~5 min — keep it, it's cheap)

- [ ] `[HUMAN]` Unplug the module entirely.
- [ ] `[AGENT]` **Quit and relaunch the server** (fresh process), load a kit synced in B3,
      edit it, save to library — works with zero broken-path warnings. This is the one
      check that proves nothing on the *same* machine depended on mounted volumes or
      in-memory state from the connected session.

### C2. Windows desktop — full offline run, fully independent

- [ ] `[AGENT]` Fresh clone of the public repo on the desktop (same freshness checks as §1:
      no `library/`, no `dist/`); note Python version and how it was invoked (`python`,
      `py`, Microsoft Store shim?).
- [ ] `[PAIR]` Copy `library/` from the MacBook to the desktop clone (network share /
      external drive) — this **is** the documented cross-machine path; log anything
      awkward about it.
- [ ] `[HUMAN]` `[DISPLAY]` Launch via double-clicking `launch.bat`. Log any SmartScreen /
      Defender prompt and whether a normal user could get past it.
- [ ] `[AGENT]` With no SD card in the machine: the drive-letter scan (D–Z) does **not**
      false-positive on other drives/USB sticks; status chip correctly says NOT mounted.
- [ ] `[AGENT]` Full offline workflow on Windows: browse the complete synced library;
      previews and waveform thumbnails from synced WAVs (`[HUMAN]` confirms playback);
      "More like this"; load a kit synced in B3; edit it; sin-edit a library instrument
      copy; save to library. **Zero broken-path warnings** on synced content — forward/
      backslash path handling is exactly what this smokes out.
- [ ] `[AGENT]` Kit bundle export while offline → import into a second clean clone (still
      offline) → loads with zero broken paths.

### C3. Reconnect round-trip (whichever machine is near the module)

- [ ] `[PAIR]` Plug the module back in, Save-to-SD the kit edited offline in C2 (if the
      desktop can't reach the module, carry it back via bundle import on the MacBook —
      note that this then also witnesses cross-OS bundle portability), eject, `[HUMAN]`
      loads it on the module — the offline edits arrive intact.

---

## 5. Phase D — docs & claims audit

- [ ] `[AGENT]` Map **every claim in the README** (features list, comparison table rows,
      Safety section, quick start) to the checklist item that witnessed it. Any claim with
      no witnessing step gets tested now or flagged. Any claim a step contradicted is a
      finding at Major or higher.
- [ ] `[AGENT]` Same pass over the announcement draft, if it's being posted — nothing in
      the post may overpromise what this playbook observed.
- [ ] `[AGENT]` Fresh-eyes verdict (Opus, end of Run 1, still blind): in its own words,
      (a) what is this app, (b) why does it exist, (c) what was hardest to figure out?
      Pass requires a correct (a) and (b) and a fixable list for (c).

---

## 6. Reporting & reconciliation

- [ ] Merge Run 1 (blind) and Run 2 (informed) logs; de-duplicate.
- [ ] Every finding carries its Run 2 classification: **bug / doc gap / UX friction /
      known limitation** — nothing left unclassified.
- [ ] Output three artifacts into `~/qa-fresh/evidence/`:
  1. `findings.md` — the full log, ordered by severity.
  2. `issues-to-file.md` — one section per GitHub issue to open (title, body, evidence).
  3. `report.md` — go/no-go against the exit criteria (§0), with the fresh-eyes verdict
     quoted and the core round-trip results (B5, C3) stated explicitly.
- [ ] Go/no-go decision against the §0 exit criteria — stated plainly, no hedging.

---

## Appendix: surface inventory (coverage reference)

The checklists above must collectively touch every item below (the manager greps this list
during §6 to confirm coverage):

- **Toolbar:** Kits ▾ (kit list · New kit from scratch · New from template/Metal Baseline ·
  Sync kits from card · Sync full library from SD · Export kits to JSON · Print MIDI map ·
  Import assignment CSV · Compare with kit… · Kit time machine… · Fix broken paths… ·
  Kit FX editor… · Export kit bundle · Import bundle/zip) · Save split (library / SD /
  custom path) · Duplicate… · Clear all pads · status message · kit-size badge · dirty
  badge · Undo + history · Tools ▾ (Trigger settings backup… · tools list) · Virtual ·
  MIDI · SD status chip · theme toggle
- **Modals:** compare/diff · time machine · relink · kit FX · trigger SysEx · instrument
  (sin) editor · similar-instruments · confirm dialog · drop overlay · autosave banner
- **Shortcuts:** Ctrl/⌘+Z · Ctrl/⌘+S · Esc · Space (preview) · ←/→ · ↑/↓ · Virtual keys 1–0 ·
  Enter/Esc in inline forms
- **Edge states:** broken-path warning + relink · kit-size amber threshold · autosave/crash
  recovery · `⚠ parser` lossless badge · read-only preset badge + save-over-preset error ·
  localhost 403 guard · junk-zip / malformed-CSV imports · empty-library template kit ·
  Virtual with no samples · Safari MIDI gating · hot-unplug
