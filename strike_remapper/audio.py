"""State-independent WAV inspection, normalization, and waveform helpers."""

import struct
import wave as _wave


def wav_peak(wav_data: bytes) -> float:
    """Approximate peak amplitude (0.0–1.0) of a 16/24-bit PCM WAV, for loudness ordering.
    Samples at a stride so huge files stay fast; returns 0.0 for unsupported formats."""
    import io, wave as _wave
    try:
        with _wave.open(io.BytesIO(wav_data)) as wf:
            sw, ctype = wf.getsampwidth(), wf.getcomptype()
            raw = wf.readframes(wf.getnframes())
        if ctype != 'NONE' or sw not in (2, 3):
            return 0.0
        peak = 0
        if sw == 2:
            n = len(raw) // 2
            step = max(1, n // 200_000)
            for i in range(0, n, step):
                v = struct.unpack_from('<h', raw, i * 2)[0]
                peak = max(peak, abs(v))
            return peak / 32767
        n = len(raw) // 3
        step = max(1, n // 200_000)
        for i in range(0, n, step):
            v = int.from_bytes(raw[i * 3:i * 3 + 3], 'little', signed=True)
            peak = max(peak, abs(v))
        return peak / 8388607
    except Exception:
        return 0.0


def normalize_wav(wav_data: bytes, target_db: float = -0.1) -> tuple:
    """Peak-normalize a PCM WAV to target_db dBFS. Supports 16-bit and 24-bit.
    Returns (new_bytes, peak_db_str) where peak_db_str describes the original peak.
    Returns (original_bytes, 'skipped') for compressed or unsupported formats."""
    import io, wave as _wave
    try:
        with _wave.open(io.BytesIO(wav_data)) as wf:
            nch, sw, rate, nfr, ctype = (wf.getnchannels(), wf.getsampwidth(),
                                          wf.getframerate(), wf.getnframes(), wf.getcomptype())
            raw = wf.readframes(nfr)
        if ctype != 'NONE' or sw not in (2, 3):
            return wav_data, 'skipped'
        max_val = (2 ** (sw * 8 - 1) - 1)
        target_peak = max_val * (10 ** (target_db / 20))
        if sw == 2:
            samples = list(struct.unpack_from(f'<{len(raw)//2}h', raw))
            peak = max(abs(s) for s in samples) if samples else 0
            if peak == 0: return wav_data, 'silent'
            gain = target_peak / peak
            new_samples = [max(-32768, min(32767, int(round(s * gain)))) for s in samples]
            new_raw = struct.pack(f'<{len(new_samples)}h', *new_samples)
        else:  # 24-bit
            n = len(raw) // 3
            samples = []
            for i in range(n):
                v = raw[3*i] | (raw[3*i+1] << 8) | (raw[3*i+2] << 16)
                if v >= 0x800000: v -= 0x1000000
                samples.append(v)
            peak = max(abs(s) for s in samples) if samples else 0
            if peak == 0: return wav_data, 'silent'
            gain = target_peak / peak
            buf = bytearray(n * 3)
            for i, s in enumerate(samples):
                v = max(-0x800000, min(0x7FFFFF, int(round(s * gain))))
                if v < 0: v += 0x1000000
                buf[3*i] = v & 0xFF; buf[3*i+1] = (v >> 8) & 0xFF; buf[3*i+2] = (v >> 16) & 0xFF
            new_raw = bytes(buf)
        import math
        peak_db = 20 * math.log10(peak / max_val) if peak > 0 else -float('inf')
        out = io.BytesIO()
        with _wave.open(out, 'wb') as wf:
            wf.setnchannels(nch); wf.setsampwidth(sw); wf.setframerate(rate)
            wf.writeframes(new_raw)
        return out.getvalue(), f'{peak_db:.1f} dBFS'
    except Exception:
        return wav_data, 'error'


def compute_waveform(wav_path: 'Path', n_points: int = 80) -> 'list | None':
    """Return a normalized peak envelope (list of n_points floats 0-1)."""
    try:
        with _wave.open(str(wav_path), 'rb') as wf:
            n_ch   = wf.getnchannels()
            sw     = wf.getsampwidth()
            n_fr   = wf.getnframes()
            raw    = wf.readframes(n_fr)
    except Exception:
        return None

    frame_bytes = n_ch * sw
    if not raw or frame_bytes == 0:
        return None

    stride = max(1, n_fr // n_points)
    peaks  = []
    for i in range(n_points):
        start = i * stride * frame_bytes
        end   = min(start + stride * frame_bytes, len(raw))
        chunk = raw[start:end]
        if not chunk:
            peaks.append(0)
            continue
        if sw == 2:
            vals  = struct.unpack_from(f'<{len(chunk)//2}h', chunk)
            peak  = max(abs(v) for v in vals) if vals else 0
        elif sw == 3:
            peak = 0
            for j in range(0, len(chunk) - 2, 3):
                v = int.from_bytes(chunk[j:j+3], 'little', signed=True)
                if abs(v) > peak:
                    peak = abs(v)
        else:
            peak = 0
        peaks.append(peak)

    max_peak = max(peaks) or 1
    return [round(p / max_peak, 3) for p in peaks]
