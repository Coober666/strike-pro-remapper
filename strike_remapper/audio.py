"""State-independent WAV utilities and audio fingerprint DSP."""

import math as _math
import struct
import wave as _wave


_FP_READ_SEC = 1.5
_FP_FFT_SIZE = 4096
_FP_BRIGHT_HZ = 2000.0


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


def _fft(re: list, im: list):
    """In-place iterative radix-2 Cooley-Tukey FFT. len must be a power of two.
    Pure stdlib — the project forbids numpy/scipy, so this is hand-rolled."""
    n = len(re)
    j = 0
    for i in range(1, n):                       # bit-reversal permutation
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2.0 * _math.pi / length
        wr, wi = _math.cos(ang), _math.sin(ang)
        half = length >> 1
        for start in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(half):
                i1 = start + k
                i2 = i1 + half
                tr = cr * re[i2] - ci * im[i2]
                ti = cr * im[i2] + ci * re[i2]
                re[i2] = re[i1] - tr
                im[i2] = im[i1] - ti
                re[i1] += tr
                im[i1] += ti
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1


def _read_wav_mono(wav_path, max_seconds):
    """Read up to max_seconds of a 16/24-bit PCM WAV → (mono samples -1..1, rate).
    Averages channels to mono; sample-rate is preserved (spectral features are
    rate-dependent). Returns (None, 0) for compressed/unsupported/broken files."""
    try:
        with _wave.open(str(wav_path), 'rb') as wf:
            nch, sw, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            nfr, ctype    = wf.getnframes(), wf.getcomptype()
            if ctype != 'NONE' or sw not in (2, 3) or rate <= 0 or nch < 1:
                return None, 0
            want = min(nfr, int(rate * max_seconds)) if max_seconds else nfr
            raw = wf.readframes(want)
    except Exception:
        return None, 0
    frame = nch * sw
    if not raw or frame == 0:
        return None, 0
    n = len(raw) // frame
    if n == 0:
        return None, 0
    if sw == 2:
        full = 32768.0
        allv = struct.unpack_from('<%dh' % (n * nch), raw)
        if nch == 1:
            out = [v / full for v in allv]
        else:
            out = [sum(allv[i*nch:i*nch+nch]) / (nch * full) for i in range(n)]
    else:  # 24-bit — no struct format code, unpack by hand
        full = 8388608.0
        out = [0.0] * n
        for i in range(n):
            b = i * frame
            s = 0
            for c in range(nch):
                o = b + c * 3
                s += int.from_bytes(raw[o:o+3], 'little', signed=True)
            out[i] = (s / nch) / full
    return out, rate


def _decay_time(env: list, win: int, rate: int) -> float:
    """Seconds for the RMS envelope to fall 20 dB below its peak (a cheap decay
    proxy). Returns the remaining read-window length if it never decays that far."""
    if not env or rate <= 0:
        return 0.0
    pk = max(env)
    if pk <= 0:
        return 0.0
    pk_i   = env.index(pk)
    target = pk * 0.1                            # -20 dB
    for i in range(pk_i, len(env)):
        if env[i] <= target:
            return (i - pk_i) * win / rate
    return (len(env) - pk_i) * win / rate


def extract_fingerprint(wav_path):
    """Compute a small, sample-rate-aware timbre vector from a WAV, or None.

    Features:
      centroid   — spectral centroid in Hz (brightness centre-of-mass)
      rolloff    — 85%-energy spectral rolloff in Hz
      zcr        — zero-crossing rate (crossings/sec; a no-FFT brightness proxy)
      brightness — fraction of spectral energy above 2 kHz
      decay      — seconds for the RMS envelope to drop 20 dB from its peak
    """
    samples, rate = _read_wav_mono(wav_path, _FP_READ_SEC)
    if not samples or rate <= 0:
        return None
    n = len(samples)

    zc, prev = 0, samples[0]
    for s in samples[1:]:
        if (prev >= 0.0) != (s >= 0.0):
            zc += 1
        prev = s
    zcr = zc * rate / n

    win = max(1, int(rate * 0.01))
    env = []
    for i in range(0, n, win):
        blk = samples[i:i+win]
        if not blk:
            break
        acc = 0.0
        for v in blk:
            acc += v * v
        env.append((acc / len(blk)) ** 0.5)
    decay = _decay_time(env, win, rate)

    peak_i = max(range(n), key=lambda i: abs(samples[i]))
    size   = _FP_FFT_SIZE
    start  = min(max(0, peak_i - size // 8), max(0, n - size))
    frame  = samples[start:start+size]
    if len(frame) < size:
        frame = frame + [0.0] * (size - len(frame))
    re = [0.0] * size
    im = [0.0] * size
    denom = size - 1
    for i in range(size):
        re[i] = frame[i] * (0.5 - 0.5 * _math.cos(2.0 * _math.pi * i / denom))
    _fft(re, im)
    half   = size // 2
    bin_hz = rate / size
    mags   = [(re[k]*re[k] + im[k]*im[k]) ** 0.5 for k in range(half)]
    total  = sum(mags) or 1e-9
    centroid = sum(mags[k] * k for k in range(half)) * bin_hz / total
    thresh, acc, rolloff = 0.85 * total, 0.0, 0.0
    for k in range(half):
        acc += mags[k]
        if acc >= thresh:
            rolloff = k * bin_hz
            break
    bright_bin = min(half, int(_FP_BRIGHT_HZ / bin_hz) if bin_hz else half)
    brightness = sum(mags[k] for k in range(bright_bin, half)) / total

    return {
        'centroid':   round(centroid, 2),
        'rolloff':    round(rolloff, 2),
        'zcr':        round(zcr, 2),
        'brightness': round(brightness, 5),
        'decay':      round(decay, 4),
        'rate':       rate,
    }
