#!/usr/bin/env python3
"""
test_fingerprint.py — verify the "More like this" audio fingerprint extractor and the
z-scored k-NN ranking on synthetic tones with KNOWN spectral properties.

Runs on tools/make_fixtures.py output (no git-ignored library needed):
  bright_a/bright_b   high fundamental   → high centroid / brightness / ZCR
  dark_a/dark_b       low fundamental    → low  centroid / brightness / ZCR
  long_a/long_b       slow RMS decay     } same pitch, so only the decay feature
  short_a/short_b     fast RMS decay     } distinguishes the two pairs

Asserts the extractor tracks intuition and that nearest-neighbour ordering is
deterministic: a bright tone ranks nearer the other bright tone than any dark one,
and a long-decay tone ranks nearer the other long-decay tone than any short one.
"""
import io
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr
from strike_remapper import audio

FIX = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures'
NAMES = ['bright_a', 'bright_b', 'dark_a', 'dark_b',
         'long_a', 'long_b', 'short_a', 'short_b']


def _sample_bytes(value, width):
    if width == 1:
        return bytes([value])
    if width == 2:
        return struct.pack('<h', value)
    if width == 3:
        return int(value).to_bytes(3, 'little', signed=True)
    raise ValueError(width)


def _wav_bytes(frames, width=2, channels=1, rate=8000):
    raw = bytearray()
    for frame in frames:
        values = frame if channels > 1 else (frame,)
        for value in values:
            raw += _sample_bytes(value, width)
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(bytes(raw))
    return out.getvalue()


def main():
    for n in NAMES:
        if not (FIX / (n + '.wav')).is_file():
            print('Run tools/make_fixtures.py first (missing %s.wav)' % n)
            sys.exit(1)

    fails = []

    def check(cond, msg):
        print(('  PASS  ' if cond else '  FAIL  ') + msg)
        if not cond:
            fails.append(msg)

    for name in ('_fft', '_read_wav_mono', '_decay_time', 'extract_fingerprint'):
        check(getattr(sr, name) is getattr(audio, name),
              f'strike_remap.{name} is the audio compatibility alias')
    for name in ('_FP_READ_SEC', '_FP_FFT_SIZE', '_FP_BRIGHT_HZ'):
        check(getattr(sr, name) == getattr(audio, name),
              f'strike_remap.{name} preserves the DSP constant')

    # --- low-level DSP contracts ---
    re = [1.0, -2.0, 0.5, 3.0]
    im = [0.0] * len(re)
    expected = [
        sum(complex(value) * complex(
            math.cos(-2 * math.pi * k * n / len(re)),
            math.sin(-2 * math.pi * k * n / len(re)),
        ) for n, value in enumerate(re))
        for k in range(len(re))
    ]
    result = audio._fft(re, im)
    check(result is None, 'FFT mutates its buffers in place')
    check(all(abs(complex(re[k], im[k]) - expected[k]) < 1e-9
              for k in range(len(re))),
          'FFT matches a direct DFT on a deterministic vector')

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        stereo16 = root / 'stereo16.wav'
        stereo16.write_bytes(_wav_bytes(
            [(32767, -32768), (16384, 0), (0, 0)],
            width=2, channels=2, rate=4,
        ))
        samples16, rate16 = audio._read_wav_mono(stereo16, 0.5)
        check(rate16 == 4 and len(samples16) == 2,
              'mono reader enforces its duration limit')
        check(abs(samples16[0] + 1 / 65536) < 1e-12 and samples16[1] == 0.25,
              '16-bit stereo channels are averaged and scaled')

        stereo24 = root / 'stereo24.wav'
        stereo24.write_bytes(_wav_bytes(
            [(4194304, -4194304), (8388607, 0)],
            width=3, channels=2, rate=8000,
        ))
        samples24, rate24 = audio._read_wav_mono(stereo24, None)
        check(rate24 == 8000 and samples24[0] == 0.0,
              '24-bit stereo channels are averaged')
        check(abs(samples24[1] - (8388607 / 2 / 8388608)) < 1e-12,
              '24-bit samples preserve the signed full-scale denominator')

        unsupported = root / 'eight-bit.wav'
        unsupported.write_bytes(_wav_bytes([0, 128, 255], width=1))
        check(audio._read_wav_mono(unsupported, None) == (None, 0),
              'unsupported sample widths return the safe fallback')
        broken = root / 'broken.wav'
        broken.write_bytes(b'not a wav')
        check(audio._read_wav_mono(broken, None) == (None, 0),
              'malformed WAVs return the safe fallback')

    check(audio._decay_time([], 10, 1000) == 0.0,
          'an empty envelope has zero decay')
    check(audio._decay_time([0.0, 0.0], 10, 1000) == 0.0,
          'a silent envelope has zero decay')
    check(audio._decay_time([0.2, 1.0, 0.5, 0.09], 10, 1000) == 0.02,
          'decay measures from the peak to the first -20 dB block')
    check(audio._decay_time([1.0, 0.5, 0.2], 10, 1000) == 0.03,
          'non-decaying envelopes return the remaining window length')

    fp = {n: audio.extract_fingerprint(FIX / (n + '.wav')) for n in NAMES}
    for n in NAMES:
        check(fp[n] is not None, f'{n}: extractor returned a fingerprint')
    if fails:
        sys.exit(1)

    # --- feature sanity: spectral features track the fundamental ---
    check(fp['bright_a']['centroid'] > fp['dark_a']['centroid'],
          'bright centroid > dark centroid')
    check(fp['bright_a']['brightness'] > fp['dark_a']['brightness'],
          'bright brightness > dark brightness')
    check(fp['bright_a']['zcr'] > fp['dark_a']['zcr'],
          'bright ZCR > dark ZCR')
    check(fp['bright_a']['rate'] == 44100, 'framerate captured (spectral features are rate-aware)')

    # --- feature sanity: decay time tracks the envelope ---
    check(fp['long_a']['decay'] > fp['short_a']['decay'],
          'long-decay decay time > short-decay decay time')

    # --- k-NN ordering: bright nearer bright than dark ---
    corpus = [(n, fp[n]) for n in NAMES]
    nn_bright = [k for k, _, _ in sr._knn_rank('bright_a', corpus, 8)]
    check(nn_bright[0] == 'bright_b',
          f'nearest to bright_a is bright_b (got {nn_bright[0]})')
    check(nn_bright.index('bright_b') < nn_bright.index('dark_a'),
          'bright_a ranks bright_b before dark_a')

    nn_dark = [k for k, _, _ in sr._knn_rank('dark_a', corpus, 8)]
    check(nn_dark[0] == 'dark_b',
          f'nearest to dark_a is dark_b (got {nn_dark[0]})')

    # --- k-NN ordering: long-decay nearer long-decay than short-decay ---
    nn_long = [k for k, _, _ in sr._knn_rank('long_a', corpus, 8)]
    check(nn_long[0] == 'long_b',
          f'nearest to long_a is long_b (got {nn_long[0]})')
    check(nn_long.index('long_b') < nn_long.index('short_a'),
          'long_a ranks long_b before short_a')

    nn_short = [k for k, _, _ in sr._knn_rank('short_a', corpus, 8)]
    check(nn_short[0] == 'short_b',
          f'nearest to short_a is short_b (got {nn_short[0]})')

    # --- empty/degenerate corpus is handled, not crashed ---
    check(sr._knn_rank('bright_a', [('bright_a', fp['bright_a'])], 5) == [],
          'single-item corpus returns no neighbours (no crash)')

    # --- baked factory base layer: size-only validation + user override ---
    # (mutate the module-level caches directly, like test_time_machine does with SNAP_DIR)
    sr._fp_factory = {'Fac/a.sin': {'v': sr.FP_SCHEMA, 'factory': True, 'size': 1, 'feats': fp['bright_a']}}
    sr._fp_cache   = {'Usr/b.sin': {'v': sr.FP_SCHEMA, 'mtime': 1.0, 'size': 2, 'feats': fp['dark_a']}}
    merged = sr._fp_all_items()
    check('Fac/a.sin' in merged and 'Usr/b.sin' in merged,
          'merged layer unions factory base + user sidecar')

    sr._fp_factory = {'K': {'v': sr.FP_SCHEMA, 'factory': True, 'size': 1, 'feats': {'centroid': 1.0}}}
    sr._fp_cache   = {'K': {'v': sr.FP_SCHEMA, 'mtime': 1.0, 'size': 1, 'feats': {'centroid': 2.0}}}
    check(sr._fp_all_items()['K']['feats']['centroid'] == 2.0,
          'user sidecar overrides factory on key collision')

    wp   = FIX / 'bright_a.wav'
    real = wp.stat().st_size
    check(sr._fp_entry_valid({'v': sr.FP_SCHEMA, 'factory': True, 'size': 999, 'feats': {}}, None),
          'factory entry trusted when WAV absent (mtime-agnostic — cards differ)')
    check(sr._fp_entry_valid({'v': sr.FP_SCHEMA, 'factory': True, 'size': real, 'feats': {}}, wp),
          'factory entry valid when WAV size matches (mtime ignored)')
    check(not sr._fp_entry_valid({'v': sr.FP_SCHEMA, 'factory': True, 'size': real + 1, 'feats': {}}, wp),
          'factory entry invalid when WAV size differs (sample replaced)')
    check(not sr._fp_entry_valid({'v': sr.FP_SCHEMA + 1, 'factory': True, 'size': real, 'feats': {}}, wp),
          'factory entry invalid on schema bump')

    print()
    if fails:
        print(f'{len(fails)} FAILED')
        sys.exit(1)
    print('All fingerprint checks passed')


if __name__ == '__main__':
    main()
