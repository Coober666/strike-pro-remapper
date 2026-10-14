# Kit Balance Assistant

Open a kit, choose **Kit Balance**, then **Analyze local samples**. The assistant
reads the selected host library without looking for cards. Factory sounds need
their local instrument and sample copies before they can be measured.

Each layer shows its current level, estimated RMS/peak, sample count and why a
change might help. Listen current and Listen proposed play the first representative
sample's 0.5-second window through your browser at the existing preview volume.
They do not send MIDI or change the kit. Audition the whole kit separately afterward.
Only the latest Listen request can play or report an error. Closing the dialog,
starting a new analysis, or applying changes stops the preview and discards pending
preview results.

Suggestions start unchecked. Select only the layers you want, then Apply selected.
All selected level changes form **one Undo step**. Exclude a pad by leaving both
layers unchecked. Save and Deploy remain separate actions. Normal recovery and
time-machine behavior still applies. No WAV or instrument file is rewritten.

## What the measurements mean

- The first 0.5 seconds of up to eight highest-velocity sample mappings per layer
  are measured; a request reads at most 96 unique local WAV windows. More complex
  or missing/unsupported layers are reported as unmeasured while others continue.
- RMS uses energy across all channels, so opposite-phase stereo does not disappear.
  A layer's RMS is the median of those sample measurements; peak uses their maximum.
- The estimate multiplies sample amplitude by layer level/127 and instrument
  level/127. This is a comparison model, not calibrated module loudness or LUFS.
- Same-group comparisons need at least three measured layers on distinct pads.
  Differences of at least 6 dB are flagged. Group comes from the instrument file;
  different tom/cymbal timbres and decay lengths can legitimately differ.
- A/B differences of at least 6 dB are flagged, including possible level jumps at
  non-overlapping velocity boundaries. Only the louder layer gets an A/B reduction.
- Overlapping layer peak sums warn about possible headroom pressure. Peaks may not
  occur together, and phase can change the sum; this cannot prove actual clipping.
- Suggestions are limited to 6 dB per pass and levels 1–127. Muted or silent-window
  layers are never boosted. Repeated passes can accumulate changes: listen and Undo
  rather than repeatedly applying until no warnings remain.

Velocity response, pitch, envelopes, effects, pan, actual round-robin playback and
the module mixer are not modeled. A window can miss later peaks or contain leading
silence. No warning does not mean the whole recording is free of clipping.

If the kit or measured sample evidence changes, Apply rejects the old analysis.
Analyze again. After a connection failure, reload the host state before another
attempt; the editor never automatically replays an unconfirmed write.

Synthetic 16/24-bit mono/stereo fixtures verify measurement direction, missing-file
handling, stale results and exact Undo restoration. Listening on a physical Strike
and final mobile audio behavior still need user acceptance.
