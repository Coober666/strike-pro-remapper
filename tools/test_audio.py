#!/usr/bin/env python3
"""Contract tests for state-independent WAV utilities."""

import io
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import strike_remap as app
from strike_remapper import audio


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
        if len(values) != channels:
            raise ValueError('frame does not match channel count')
        for value in values:
            raw += _sample_bytes(value, width)
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(bytes(raw))
    return out.getvalue()


def _metadata(data):
    with wave.open(io.BytesIO(data), 'rb') as wav:
        return (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                wav.getnframes())


def main():
    failures = []

    def check(condition, message):
        print(('  ok   ' if condition else '  FAIL ') + message)
        if not condition:
            failures.append(message)

    for name in ('wav_peak', 'normalize_wav', 'compute_waveform'):
        check(getattr(app, name) is getattr(audio, name),
              f'strike_remap.{name} is the audio compatibility alias')

    wav16 = _wav_bytes([0, 8192, -16384, 4096], width=2)
    wav24 = _wav_bytes([0, 2097152, -4194304, 1048576], width=3)
    check(abs(audio.wav_peak(wav16) - 16384 / 32767) < 1e-12,
          '16-bit peak uses the PCM full-scale denominator')
    check(abs(audio.wav_peak(wav24) - 4194304 / 8388607) < 1e-12,
          '24-bit peak preserves signed sample decoding')
    check(audio.wav_peak(b'not a wav') == 0.0,
          'malformed audio has a harmless zero peak')

    stereo16 = _wav_bytes([(0, 0), (4096, -8192), (16384, -4096)],
                          width=2, channels=2, rate=22050)
    normalized16, original_peak16 = audio.normalize_wav(stereo16)
    check(original_peak16 == '-6.0 dBFS',
          '16-bit normalization reports the original peak')
    check(_metadata(normalized16) == _metadata(stereo16),
          '16-bit normalization preserves channels, rate, width, and frame count')
    check(abs(audio.wav_peak(normalized16) - 10 ** (-0.1 / 20)) < 0.0001,
          '16-bit normalization reaches the requested peak')

    normalized24, original_peak24 = audio.normalize_wav(wav24)
    check(original_peak24 == '-6.0 dBFS',
          '24-bit normalization reports the original peak')
    check(_metadata(normalized24) == _metadata(wav24),
          '24-bit normalization preserves WAV metadata')
    check(abs(audio.wav_peak(normalized24) - 10 ** (-0.1 / 20)) < 0.00001,
          '24-bit normalization reaches the requested peak')

    silent = _wav_bytes([0, 0, 0, 0], width=2)
    check(audio.normalize_wav(silent) == (silent, 'silent'),
          'silent audio is returned byte-identically')
    unsupported = _wav_bytes([0, 64, 128, 255], width=1)
    check(audio.normalize_wav(unsupported) == (unsupported, 'skipped'),
          'unsupported sample widths are skipped byte-identically')
    check(audio.normalize_wav(b'not a wav') == (b'not a wav', 'error'),
          'malformed audio is returned with an error status')

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        envelope16 = root / 'envelope16.wav'
        envelope16.write_bytes(_wav_bytes(
            [0, 1000, 0, 2000, 0, 3000, 0, 4000], width=2
        ))
        check(audio.compute_waveform(envelope16, 4) == [0.25, 0.5, 0.75, 1.0],
              '16-bit waveform returns the normalized peak envelope')

        envelope24 = root / 'envelope24.wav'
        envelope24.write_bytes(_wav_bytes(
            [0, 100000, 0, 200000, 0, 300000, 0, 400000], width=3
        ))
        check(audio.compute_waveform(envelope24, 4) == [0.25, 0.5, 0.75, 1.0],
              '24-bit waveform returns the normalized peak envelope')

        empty = root / 'empty.wav'
        empty.write_bytes(_wav_bytes([], width=2))
        check(audio.compute_waveform(empty, 4) is None,
              'an empty WAV has no waveform')

        eight_bit = root / 'eight-bit.wav'
        eight_bit.write_bytes(unsupported)
        check(audio.compute_waveform(eight_bit, 2) == [0.0, 0.0],
              'unsupported waveform widths retain the existing zero envelope')

        broken = root / 'broken.wav'
        broken.write_bytes(b'not a wav')
        check(audio.compute_waveform(broken, 4) is None,
              'a malformed WAV has no waveform')

    if failures:
        print(f'\n{len(failures)} audio contract(s) failed')
        sys.exit(1)
    print('\nall audio contracts passed')


if __name__ == '__main__':
    main()
