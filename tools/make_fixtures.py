#!/usr/bin/env python3
"""
make_fixtures.py — generate synthetic .skt/.sin test fixtures into tests/fixtures/.

Everything is built by this project's own writers (no factory content), so the
round-trip suites can run on a fresh clone without the git-ignored library.
"""
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as sr

OUT = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures'


def _write_tone(path, freq_hz, decay_sec, rate=44100, dur=1.5, harmonics=(1,)):
    """Write a 16-bit mono WAV of an exponentially-decaying tone with KNOWN spectral
    properties — used to make the fingerprint / nearest-neighbour tests deterministic.
      freq_hz  → controls spectral centroid / brightness / zero-crossing rate
      decay_sec→ controls the RMS-envelope decay time
    """
    n = int(rate * dur)
    frames = bytearray()
    tau = decay_sec / math.log(1000)   # ~ -60 dB over decay_sec
    for i in range(n):
        t = i / rate
        env = math.exp(-t / tau) if tau > 0 else (1.0 if i == 0 else 0.0)
        s = sum(math.sin(2 * math.pi * freq_hz * h * t) / h for h in harmonics)
        s = s / len(harmonics)
        frames += struct.pack('<h', int(max(-1.0, min(1.0, s * env)) * 30000))
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))


def _make_audio_fixtures():
    """Synthetic tones for tools/test_fingerprint.py — bright vs dark, long vs short."""
    # Bright pair (high fundamental → high centroid/ZCR/brightness), medium decay.
    _write_tone(OUT / 'bright_a.wav', 6000, 0.30)
    _write_tone(OUT / 'bright_b.wav', 5200, 0.30)
    # Dark pair (low fundamental → low centroid/ZCR/brightness), medium decay.
    _write_tone(OUT / 'dark_a.wav', 220, 0.30, harmonics=(1, 2))
    _write_tone(OUT / 'dark_b.wav', 300, 0.30, harmonics=(1, 2))
    # Decay pairs at a shared mid frequency: only the envelope differs, so the decay
    # feature (not pitch) decides nearest-neighbour ordering within the pair.
    _write_tone(OUT / 'long_a.wav', 900, 1.10)
    _write_tone(OUT / 'long_b.wav', 900, 0.90)
    _write_tone(OUT / 'short_a.wav', 900, 0.05)
    _write_tone(OUT / 'short_b.wav', 900, 0.08)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _make_audio_fixtures()

    (OUT / 'single_zone.sin').write_bytes(
        sr._build_sin([('Fixtures/kick.wav', 1, 127, 1)]))
    (OUT / 'multi_velocity.sin').write_bytes(
        sr._build_sin([
            ('Fixtures/snare_soft.wav', 1, 42, 1),
            ('Fixtures/snare_med.wav', 43, 84, 1),
            ('Fixtures/snare_hard.wav', 85, 127, 1),
        ]))
    (OUT / 'round_robin.sin').write_bytes(
        sr._build_sin([
            ('Fixtures/tom_a.wav', 1, 127, 1),
            ('Fixtures/tom_b.wav', 1, 127, 2),
        ]))

    # Structural-edit fixture: split + RR variant via the zone rebuilder
    base = (OUT / 'multi_velocity.sin').read_bytes()
    (OUT / 'rebuilt_zones.sin').write_bytes(
        sr.rebuild_sin_zones(base, [
            {'src': 0, 'vmin': 1, 'vmax': 21},
            {'src': 0, 'vmin': 22, 'vmax': 42},
            {'src': 1, 'vmin': 43, 'vmax': 84},
            {'src': 1, 'vmin': 43, 'vmax': 84, 'rr': 2},
            {'src': 2, 'vmin': 85, 'vmax': 127},
        ]))

    # Synthetic kit: blank 24-pad kit with assignments and edited params
    pads = []
    for pid in sr.PAD_ORDER:
        pads.append({'id': pid, 'label': sr.PAD_LABEL.get(pid, pid),
                     'layer_a': sr.NO_INSTRUMENT, 'layer_b': sr.NO_INSTRUMENT,
                     'payload': sr._blank_payload(pid)})
    instruments = ['Fixtures/single_zone.sin', 'Fixtures/multi_velocity.sin']
    pads[0]['layer_a'] = 0
    pads[1]['layer_a'] = 1
    pads[1]['layer_b'] = 0
    pl = pads[1]['payload']
    pl[sr.LA_PAN_OFF]   = 0x100 - 10   # pan -10
    pl[sr.LA_FINE_OFF]  = 25           # fine +25 cents
    pl[sr.LA_PITCH_OFF] = 0x100 - 2    # pitch -2 st
    pl[sr.XFADE_VEL_OFF] = 64
    pl[sr.MIDI_NOTE_OFF] = 38
    (OUT / 'synthetic_kit.skt').write_bytes(
        sr.build_skt(sr._KIT_BLOCK_TEMPLATE, pads, instruments))

    print(f'wrote {len(list(OUT.iterdir()))} fixtures to {OUT}')


if __name__ == '__main__':
    main()
