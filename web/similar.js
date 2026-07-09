// similar.js — READ-ONLY JavaScript port of strike_remap.py's "More like this"
// k-NN similarity ranking (_knn_rank / similar_instruments).
//
// Byte-for-byte faithful to the Python z-score + euclidean-distance ranking. No
// fingerprint EXTRACTION lives here — this module only ranks pre-computed feature
// vectors (the {centroid, rolloff, zcr, brightness, decay} dicts already baked into
// factory_fingerprints.json / library/fingerprints.json). It deliberately does NOT:
//   - read/decode WAV files or compute FFTs (that's extract_fingerprint(), Python-only)
//   - filter the corpus by filesystem availability (state['avail']) — the Python
//     version does (`similar_instruments`); here the CALLER decides what corpus items
//     to pass in, since a browser has no local filesystem to scan.
// Vanilla JS, no dependencies.

// FP_FEATURES (strike_remap.py:2374) — order matters: z-score stats are accumulated
// in this exact iteration order to match Python's summation order bit-for-bit.
export const FP_FEATURES = ['centroid', 'rolloff', 'zcr', 'brightness', 'decay'];

// Python's round() is banker's rounding (round-half-to-even), not the "round half
// away from zero" that Math.round() implements. _knn_rank rounds distances to 3
// decimals; ties at exactly x.xxx5 are rare for euclidean distances of z-scored
// floats, but replicate the exact semantics so parity holds if one ever shows up.
function roundHalfEven(x, ndigits) {
  const p = 10 ** ndigits;
  const scaled = x * p;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  const EPS = 1e-9; // guard float noise around the .5 boundary
  let rounded;
  if (Math.abs(diff - 0.5) < EPS) {
    // exactly (or effectively) half — round to even
    rounded = (floor % 2 === 0) ? floor : floor + 1;
  } else {
    rounded = Math.round(scaled);
  }
  return rounded / p;
}

// Faithful port of _knn_rank(query_key, corpus_items, n) (strike_remap.py:2756).
// corpusItems = [[key, feats], ...] INCLUDING the query item.
// Returns [[key, dist, feats], ...] nearest-first, excluding the query itself.
export function knnRank(queryKey, corpusItems, n = 10) {
  const featsBy = new Map(corpusItems);
  const q = featsBy.get(queryKey);
  if (q == null || corpusItems.length < 2) return [];

  const means = {};
  const stds = {};
  for (const key of FP_FEATURES) {
    const vals = corpusItems.map(([, f]) => (f[key] ?? 0.0));
    const m = vals.reduce((a, b) => a + b, 0) / vals.length;
    const varr = vals.reduce((a, v) => a + (v - m) ** 2, 0) / vals.length;
    means[key] = m;
    stds[key] = Math.sqrt(varr) || 1.0;
  }

  const vec = (f) => FP_FEATURES.map((k) => ((f[k] ?? 0.0) - means[k]) / stds[k]);

  const qv = vec(q);
  const scored = [];
  for (const [key, f] of corpusItems) {
    if (key === queryKey) continue;
    const fv = vec(f);
    let sumSq = 0.0;
    for (let i = 0; i < qv.length; i++) sumSq += (qv[i] - fv[i]) ** 2;
    scored.push([Math.sqrt(sumSq), key, f]);
  }
  scored.sort((a, b) => a[0] - b[0]);

  const count = Math.max(1, Math.trunc(n));
  return scored.slice(0, count).map(([d, key, f]) => [key, roundHalfEven(d, 3), f]);
}

// Faithful port of similar_instruments(sin_rel, n) (strike_remap.py:2783), minus the
// Python version's `avail` filesystem filter — the caller passes in whatever corpus
// it wants ranked (e.g. every fingerprints entry, or one already filtered to what's
// actually installed).
//
// fingerprints = the parsed factory_fingerprints.json (or user sidecar / merged
// union) object: { sin_rel: { feats: {...} | null, ... }, ... }. Entries with
// missing/null feats are skipped, matching `_fp_all_items()` filtered by `e.get('feats')`.
export function similarInstruments(sinRel, fingerprints, n = 10) {
  const entries = Object.entries(fingerprints);
  const corpusHave = entries.filter(([, e]) => e && e.feats).length;

  const q = fingerprints[sinRel] && fingerprints[sinRel].feats;
  if (!q) {
    return { query: sinRel, results: [], unfingerprinted: true, corpus: corpusHave };
  }

  const corpus = entries
    .filter(([, e]) => e && e.feats)
    .map(([rel, e]) => [rel, e.feats]);
  if (!corpus.some(([rel]) => rel === sinRel)) {
    corpus.push([sinRel, q]);
  }

  const ranked = knnRank(sinRel, corpus, n);
  const results = ranked.map(([rel, d, f]) => ({
    sin_rel: rel,
    name: rel.includes('/') ? rel.split('/').slice(1).join('/').replace(/\.[^.]*$/, '') : rel,
    group: rel.includes('/') ? rel.split('/', 1)[0] : rel,
    dist: d,
    centroid: f.centroid ?? null,
    brightness: f.brightness ?? null,
    decay: f.decay ?? null,
  }));

  return { query: sinRel, results, unfingerprinted: false, corpus: corpus.length };
}
