# Trigger Coach observations

Open Drum MIDI toolkit, record or import a take, then select **Review this take**.
The demo works without a device. Stop recording first. Expand a channel/note row
for measured evidence, a suggested next check and reference comparison. Use
Analysis focus to review one pad; saved profile names are your own labels.
**Export report** includes the current Coach observations even without opening
the review. No MIDI output or setting changes are performed.

## What the first version measures

- Received positive Note Ons per channel/note, MIDI velocity range and mean.
- Hits at velocity 120–127; at least 25% suggests comparing soft/firm exercises
  and reviewing the documented velocity curve/sensitivity if soft playing is also
  at the top. MIDI velocity is not measured loudness or force.
- Same-note intervals at most 30 ms, including identical timestamps. At least three
  prompts a slow single-hit check. Rolls explicitly explain that short intervals
  can be intentional. Routing duplicates and timestamp batching are alternatives.
- Adjacent different-note Note Ons on the same channel, at most 12 ms apart,
  with at least three occurrences. Only adjacent events are counted; this is not
  an exhaustive cross-correlation or a percentage of physical strikes. A chord,
  coordinated groove or multiple zones can produce this pattern. Repeat an
  isolated-pad exercise and check routing before attributing it to crosstalk.

These thresholds are visible **review heuristics**, chosen for this first version,
not calibrated fault classifiers. Twenty received hits per channel/note is a
practical review minimum, not a confidence interval or proof of exercise completion.
Sparse captures ask for more evidence. Partial captures ask for a complete repeat.
Demo captures remain clearly synthetic. No warning is not a clean bill of health.

The analysis ignores Note Off (including velocity-zero Note On), preserves channel
identity, and never computes intervals or adjacent pairs across recorded pauses.
Timing is based on received timestamps, without latency calibration. No audio,
physical strike counter or pad-position sensor is available: missed hits, hot spots,
actual crosstalk and hardware faults cannot be established from this report alone.

## Comparing before and after

Save a baseline, change only something you can identify, and repeat the same
exercise with the same pad, sticks, technique and routing. Choose the baseline
under Compare a session, then review again. Mean-velocity differences and both
hit counts are observations, never improvement scores.

Complete, non-demo captures with the same nonempty exercise selection and at least
20 hits each receive a review-minimum statement. All other comparisons are marked
exploratory. The app cannot verify that an exercise or physical setup was matched.
Names can differ between profiles: comparison is by channel/note.

The panel invalidates when a take, reference, focus, profile, exercise or capture
state changes. It shows at most 128 note rows and 20 adjacent-pair candidates;
the report includes all note rows and the same top-20 pair limit. Narrow focus
to inspect other candidates. Saved events are never filtered or rewritten.

## Verification and remaining scope

Synthetic contracts cover sparse takes, channel separation, Note Off handling,
pause boundaries, rolls, partial/demo markers, intentional simultaneous playing,
comparison eligibility and preservation of original events. Chromium/WebKit
checks cover review, context invalidation, safe text rendering and report export.
These do not establish physical pad or mobile acceptance. Issue #30 remains open
for hardware validation and any future module-specific recommendations.

October 14 local validation: all 72 MIDI/Wi-Fi Chromium and WebKit cases passed,
including four new review/export/context/text-rendering cases. All 22 analysis
contracts passed, including a dense 50,000-event review. Focused desktop and WebKit
review screenshots were captured; the desktop layout was inspected. Physical
device acceptance is not established by these checks.
