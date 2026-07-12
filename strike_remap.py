#!/usr/bin/env python3
"""
Alesis Strike Pro kit remapper.

Decodes .skt kit files and lets you reassign .sin instrument files to each
pad zone via a local web UI at http://localhost:8765
"""

import base64
import datetime
import hashlib
import io
import json
import os
import platform
import shutil
import string as _string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

LIBRARY_DIR = Path(__file__).resolve().parent / 'library'

# ── Platform-aware SD card detection ─────────────────────────────────────────────

def _get_windows_volume_label(root: Path) -> str:
    """Return the volume label for a Windows drive root (e.g. Path('E:\\')), or '' on error."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        drive = str(root)
        if not drive.endswith('\\'):
            drive += '\\'
        ctypes.windll.kernel32.GetVolumeInformationW(
            drive, buf, len(buf), None, None, None, None, 0)
        return buf.value.strip()
    except Exception:
        return ''


def _strike_roots_under(base: Path) -> list:
    """
    Return all paths under base that look like Strike Pro roots (contain an Instruments/ folder).
    Checks base itself first, then one level of subdirectories.
    """
    roots = []
    if (base / 'Instruments').is_dir():
        roots.append(base)
    else:
        try:
            for sub in sorted(base.iterdir()):
                if sub.is_dir() and (sub / 'Instruments').is_dir():
                    roots.append(sub)
        except PermissionError:
            pass
    return roots


def _find_strike_volumes() -> dict:
    """
    Scan for mounted Strike Pro SD card volumes (those containing an 'Instruments' folder).
    Also searches one level of subdirectories, so a flash drive with files in e.g.
    STORAGE/Instruments/ is detected automatically.
    Returns {label: root_path}.
    """
    found = {}
    if platform.system() == 'Windows':
        for letter in _string.ascii_uppercase[3:]:   # D–Z, skip A/B/C
            drive = Path(f'{letter}:\\')
            if not drive.exists():
                continue
            label = _get_windows_volume_label(drive) or f'{letter}:'
            for root in _strike_roots_under(drive):
                # Use "LABEL/subdir" as key when files are in a subdirectory
                key = label if root == drive else f'{label}/{root.name}'
                found[key] = root
    else:
        vols_dir = Path('/Volumes')
        if vols_dir.is_dir():
            for v in sorted(vols_dir.iterdir()):
                for root in _strike_roots_under(v):
                    key = v.name if root == v else f'{v.name}/{root.name}'
                    found[key] = root
    return found


def _looks_like_preset_root(root: Path) -> bool:
    """
    True if root has the factory preset card's content shape: Kits/ holds
    CATEGORY SUBFOLDERS containing .skt files (ACOUSTIC/, ELECTRONIC/, ...).
    The user card's Kits/ holds flat .skt files (or is empty/absent).
    """
    kits = root / 'Kits'
    try:
        if not kits.is_dir():
            return False
        for sub in kits.iterdir():
            if sub.is_dir():
                try:
                    if any(f.is_file() and f.suffix.lower() == '.skt'
                           for f in sub.iterdir()):
                        return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


def _volume_writable(root: Path) -> bool:
    """Probe root with a create+delete of a temp file. Only ever called on
    volumes that do NOT look like the factory preset card (see
    _classify_volumes), so the factory card is never written — not even a
    probe file."""
    probe = root / '.strike-remap-write-probe.tmp'
    try:
        probe.write_bytes(b'')
        probe.unlink()
        return True
    except OSError:
        return False


def _classify_volumes(vols: dict):
    """
    Identify the user card and the preset card by CONTENT + WRITABILITY —
    never by volume label. (The physical Strike cards carry no FAT label at
    all: "NO NAME" is a macOS display name for unlabeled volumes, Windows
    reports an empty label, and label/mount-order/drive-letter/device-node
    all churn across remounts. Classifying by name inverted the save guard —
    see issue #3.)

    Pass 1: any volume with the factory content shape (Kits/<CATEGORY>/*.skt)
    is the preset card. Pass 2: of the rest, the first that accepts a write
    probe is the user card; anything unwritable/unprobeable falls into the
    preset slot so it is protected rather than used as a save target.
    Returns (user_root, preset_root); either may be None.
    """
    user = preset = None
    leftovers = []
    for path in vols.values():
        if preset is None and _looks_like_preset_root(path):
            preset = path
        else:
            leftovers.append(path)
    for path in leftovers:
        if user is None and not _looks_like_preset_root(path) and _volume_writable(path):
            user = path
        elif preset is None:
            preset = path
    return user, preset


def get_volumes():
    """Return (user_volume_root, preset_volume_root). Either may be None if not mounted."""
    return _classify_volumes(_find_strike_volumes())


def _is_under(path: Path, root: Path) -> bool:
    """Return True if path is inside root (resolves symlinks)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sd_save_path(user_vol, kit_path_str: str) -> str:
    """
    Return the best 'Save to SD' target path.
    - If the kit was loaded FROM the user SD card, save back to the exact
      same file so we don't create a duplicate in a different subfolder.
    - Otherwise (loaded from library or elsewhere) default to Kits/<name>.
    """
    if not user_vol:
        return ''
    loaded = Path(kit_path_str)
    if _is_under(loaded, user_vol):
        return str(loaded)          # save in-place
    return str(user_vol / 'Kits' / loaded.name)


def find_volumes():
    """Return list of Instruments root Paths for all mounted Strike Pro SD cards."""
    user, preset = get_volumes()
    roots = []
    for vol in (user, preset):
        if vol and (vol / 'Instruments').is_dir():
            roots.append(vol / 'Instruments')
    return roots


def scan_instruments(inst_roots):
    """
    Walk instrument roots and return {rel_path: abs_path}.
    Relative paths always use forward slashes (e.g. 'Kicks/Big Boom.sin').
    """
    found = {}
    for root in inst_roots:
        for path in sorted(root.rglob('*.sin')):
            rel = str(path.relative_to(root)).replace('\\', '/')
            found[rel] = path
    return found


def find_kit_files():
    """
    Return list of dicts {name, path, source} for all available kits.
    Sources: library/kits/, user SD card, preset SD card.
    Each source is deduplicated internally (the SD card stores .skt files in
    both the root and a Kits/ subfolder), but the same filename CAN appear
    from multiple sources so the user can choose which copy to load.
    """
    user, preset = get_volumes()
    sources = [
        ('library',   LIBRARY_DIR / 'kits'),
        ('user SD',   user),
        ('preset SD', preset),
    ]
    kits = []
    for source_label, root in sources:
        if not root or not root.is_dir():
            continue
        seen_in_source = set()
        for p in sorted(root.rglob('*.skt'), key=lambda p: p.name):
            if p.name.startswith('.') or p.name.startswith('._'):
                continue
            if p.name not in seen_in_source:
                seen_in_source.add(p.name)
                kits.append({'name': p.name, 'path': str(p), 'source': source_label})
    return kits

# ── .skt binary parser / writer ────────────────────────────────────────────────────

PAD_LABEL = {
    "K1H": "Kick 1 Head",      "K2H": "Kick 2 Head",
    "S1H": "Snare Head",       "S1R": "Snare Rim",
    "T1H": "Tom 1 Head",       "T1R": "Tom 1 Rim",
    "T2H": "Tom 2 Head",       "T2R": "Tom 2 Rim",
    "T3H": "Tom 3 Head",       "T3R": "Tom 3 Rim",
    "T4H": "Tom 4 Head",       "T4R": "Tom 4 Rim",
    "H1B": "Hi-Hat Bow",       "H1E": "Hi-Hat Edge",  "H1F": "Hi-Hat Foot",
    "C1B": "Cymbal 1 Bow",     "C1E": "Cymbal 1 Edge",
    "C2B": "Cymbal 2 Bow",     "C2E": "Cymbal 2 Edge",
    "C3B": "Cymbal 3 Bow",     "C3E": "Cymbal 3 Edge",
    "R1D": "Ride Bell",        "R1B": "Ride Bow",     "R1E": "Ride Edge",
}

PAD_INPUT = {
    "K1H": "KICK",              "K2H": "KICK (2nd)",
    "S1H": "SNARE · tip",       "S1R": "SNARE · ring",
    "T1H": "TOM 1 · tip",       "T1R": "TOM 1 · ring",
    "T2H": "TOM 2 · tip",       "T2R": "TOM 2 · ring",
    "T3H": "TOM 3 · tip",       "T3R": "TOM 3 · ring",
    "T4H": "TOM 4 · tip",       "T4R": "TOM 4 · ring",
    "H1B": "HI-HAT · tip",      "H1E": "HI-HAT · ring",  "H1F": "HH CONTROL",
    "C1B": "CRASH 1 · tip",     "C1E": "CRASH 1 · ring",
    "C2B": "CRASH 2 · tip",     "C2E": "CRASH 2 · ring",
    "C3B": "CRASH 3 · tip",     "C3E": "CRASH 3 · ring",
    "R1B": "RIDE 1 · tip",      "R1E": "RIDE 1 · ring",
    "R1D": "RIDE 2",
}

PAD_ORDER = [
    'K1H', 'K2H',
    'S1H', 'S1R',
    'T1H', 'T1R', 'T2H', 'T2R', 'T3H', 'T3R', 'T4H', 'T4R',
    'H1B', 'H1E', 'H1F',
    'C1B', 'C1E', 'C2B', 'C2E', 'C3B', 'C3E',
    'R1D', 'R1B', 'R1E',
]

DEFAULT_MIDI_NOTE = {
    'K1H': 36, 'K2H': 36,
    'S1H': 38, 'S1R': 37,
    'T1H': 48, 'T1R': 37, 'T2H': 47, 'T2R': 37,
    'T3H': 45, 'T3R': 37, 'T4H': 43, 'T4R': 37,
    'H1B': 42, 'H1E': 46, 'H1F': 44,
    'C1B': 49, 'C1E': 49, 'C2B': 57, 'C2E': 57, 'C3B': 55, 'C3E': 55,
    'R1D': 53, 'R1B': 51, 'R1E': 59,
}

LAYER_A_IDX_OFF = 4   # uint16 LE offset within payload for Layer A str index
LAYER_B_IDX_OFF = 24  # uint16 LE offset within payload for Layer B str index
NO_INSTRUMENT   = 0xFFFF

# Additional payload offsets (relative to start of inst block payload).
# NOTE: every offset below is hardware-confirmed as of May 2026 (hex diff against
# official-editor saves) — see FORMAT.md for the authoritative table. The bracketed
# tags record how each one was originally discovered.
MIDI_NOTE_OFF  = 52   # uint8  — GM MIDI note number         [confirmed]
LA_LEVEL_OFF   =  6   # uint8  — Layer A output level 0–127  [confirmed]
LA_PAN_OFF     =  7   # int8   — Layer A pan, -50 to +50     [CONFIRMED: user set hard-left → 0xce=-50]
LA_PITCH_OFF   = 11   # int8   — Layer A pitch, -12 to +12 semitones [CONFIRMED: was statistical
                       #          analysis of 116 preset kits; int8 mode=0, range 1-12 / 244-255]
LA_FCUT_OFF    = 13   # uint8  — Layer A Filter Cutoff 0-99   [CONFIRMED: was SEVEN REC diff + mode=99]
LA_FFLAG_OFF   = 14   # uint8  — Layer A Filter Enable flag    [CONFIRMED: 0=off, 1=on]
LA_DECAY_OFF    =  8   # uint8  — Layer A Decay 0-99            [CONFIRMED: screenshot K1H Decay=99=payload[8]]
LA_VEL_DEC_OFF  = 15   # uint8  — Layer A Velocity→Decay        [CONFIRMED: hex diff]
LA_VEL_PCH_OFF  = 16   # uint8  — Layer A Velocity→Pitch        [CONFIRMED: hex diff]
LA_VEL_FLT_OFF  = 17   # uint8  — Layer A Velocity→Filter       [CONFIRMED: hex diff]
LA_VEL_VOL_OFF  = 18   # uint8  — Layer A Velocity→Volume 0-127 [CONFIRMED: screenshot K1H VelVol=90=payload[18]]
LA_VEL_MIN_OFF  = 19   # uint8  — Layer A velocity range min 0-127 [CONFIRMED: mirrors LB off 39=XFADE_VEL]
LA_VEL_MAX_OFF  = 20   # uint8  — Layer A velocity range max 0-127 [CONFIRMED: mirrors LB off 40=always 127]
LB_LEVEL_OFF    = 26   # uint8  — Layer B output level 0–127  [confirmed]
LB_PAN_OFF      = 27   # int8   — Layer B pan, -50 to +50     [confirmed by symmetry]
LB_PITCH_OFF    = 31   # int8   — Layer B pitch, -12 to +12 semitones [mirrors LA_PITCH_OFF+20]
LB_FCUT_OFF     = 33   # uint8  — Layer B Filter Cutoff 0-99   [mirrors LA_FCUT_OFF+20]
LB_FFLAG_OFF    = 34   # uint8  — Layer B Filter Enable flag    [mirrors LA_FFLAG_OFF+20]
LB_DECAY_OFF    = 28   # uint8  — Layer B Decay 0-99            [CONFIRMED: mirrors LA_DECAY_OFF+20]
LB_VEL_DEC_OFF  = 35   # uint8  — Layer B Velocity→Decay        [CONFIRMED: by symmetry +20]
LB_VEL_PCH_OFF  = 36   # uint8  — Layer B Velocity→Pitch        [CONFIRMED: by symmetry +20]
LB_VEL_FLT_OFF  = 37   # uint8  — Layer B Velocity→Filter       [CONFIRMED: by symmetry +20]
LB_VEL_VOL_OFF  = 38   # uint8  — Layer B Velocity→Volume 0-127 [CONFIRMED: screenshot K1H VelVol=83=payload[38]]
XFADE_VEL_OFF   = 39   # uint8  — Layer B velocity minimum (xfade threshold) [CONFIRMED: hex diff]
EQ_COMP_OFF     = 46   # uint8  — EQ/Comp enable (0=off, 1=on)  [CONFIRMED: hex diff]
REVERB_OFF      = 44   # uint8  — FX Reverb send level 0-99     [CONFIRMED: hex diff — was wrongly XFADE_VEL_OFF]
FX1_OFF         = 45   # uint8  — FX1 send level 0-99           [CONFIRMED: hex diff]
FX2_OFF         = 61   # uint8  — FX2 send level 0-99           [CONFIRMED: hex diff]
PRIORITY_OFF    = 48   # uint8  — Playback priority (0=Low,1=Med,2=High) [CONFIRMED: hex diff]
MUTE_GRP_OFF    = 49   # uint8  — mute/choke group: 0=off, 1–9=groups 1–9 [CONFIRMED: hex diff]
NOTE_OFF_OFF    = 50   # uint8  — Note Off mode (0=SENT,1=NONE,2=ALT)     [CONFIRMED: hex diff]
MIDI_CHAN_OFF   = 51   # uint8  — MIDI channel, 0-indexed (0=ch1…15=ch16) [CONFIRMED: hex diff]
GATE_TIME_OFF   = 53   # uint8  — Gate time: 0–99 = Free (ms), 100–109 = Sync:32…Sync:2T, 255 = OFF
                       #   ✅ FULL LUT CONFIRMED via hex diff; ms semantics per official editor guide p.8
PLAY_MODE_OFF   = 54   # uint8  — Playback mode (0=Mono, 1=Poly)          [CONFIRMED: hex diff]
LA_FINE_OFF     = 12   # int8   — Layer A fine pitch -50 to +50 cents      [CONFIRMED: hex diff]
LB_FINE_OFF     = 32   # int8   — Layer B fine pitch -50 to +50 cents      [CONFIRMED: mirrors LA_FINE_OFF+20]
LA_LOOP_OFF     = 21   # uint8  — Layer A loop mode (0=OFF, 1=ON)          [CONFIRMED: hex diff]
LB_LOOP_OFF     = 41   # uint8  — Layer B loop mode (0=OFF, 1=ON)          [CONFIRMED: mirrors LA_LOOP_OFF+20]

GM_DRUMS = {
    35: 'Ac.Bass Drum',  36: 'Bass Drum 1',  37: 'Side Stick',
    38: 'Ac.Snare',      39: 'Hand Clap',    40: 'Elec.Snare',
    41: 'Lo Floor Tom',  42: 'Closed HH',    43: 'Hi Floor Tom',
    44: 'Pedal HH',      45: 'Lo Tom',       46: 'Open HH',
    47: 'Lo-Mid Tom',    48: 'Hi-Mid Tom',   49: 'Crash 1',
    50: 'Hi Tom',        51: 'Ride 1',       52: 'Chinese',
    53: 'Ride Bell',     54: 'Tambourine',   55: 'Splash',
    56: 'Cowbell',       57: 'Crash 2',      58: 'Vibraslap',
    59: 'Ride 2',        60: 'Hi Bongo',     61: 'Lo Bongo',
}


def parse_skt(data: bytes):
    """
    Parse a raw .skt file.
    Returns (kit_raw_header, pads, instruments, tail) where:
      kit_raw_header  = raw bytes of the KIT block (header+size+data)
      pads            = list of dicts: {id, label, layer_a, layer_b, payload}
      instruments     = list of str paths in order (the str table)
      tail            = any bytes after the str block (null padding, unknown blocks)
    """
    assert data[:4] == b'KIT ', "Not a KIT file"
    kit_size = struct.unpack_from('<I', data, 4)[0]
    kit_raw  = data[:8 + kit_size]
    pos      = 8 + kit_size

    pads = []
    while pos + 8 <= len(data) and data[pos:pos+4] == b'inst':
        blk_size = struct.unpack_from('<I', data, pos+4)[0]
        payload  = bytearray(data[pos+8 : pos+8+blk_size])
        pad_id   = bytes(payload[:4]).decode('ascii', errors='replace').strip()
        layer_a  = struct.unpack_from('<H', payload, LAYER_A_IDX_OFF)[0]
        layer_b  = struct.unpack_from('<H', payload, LAYER_B_IDX_OFF)[0]
        pads.append({
            'id':      pad_id,
            'label':   PAD_LABEL.get(pad_id, pad_id),
            'layer_a': layer_a,
            'layer_b': layer_b,
            'payload': payload,
        })
        pos += 8 + blk_size

    instruments = []
    tail = b''
    if pos + 8 <= len(data) and data[pos:pos+4] == b'str ':
        str_size = struct.unpack_from('<I', data, pos+4)[0]
        str_data = data[pos+8 : pos+8+str_size]
        i = 0
        while i < len(str_data):
            try:
                end = str_data.index(b'\x00', i)
            except ValueError:
                break
            s = str_data[i:end].decode('ascii', errors='replace')
            if s:
                instruments.append(s)
            i = end + 1
        tail = data[pos+8+str_size:]

    return kit_raw, pads, instruments, tail


# ── Custom instrument import ───────────────────────────────────────────────────

# INST block: 24-byte instrument-level params (cloned from 808 Clap.sin, group=CLAPS_SFX)
_SIN_INST_BYTES = bytes([
    0x00, 0x12, 0x01, 0x00, 0x00, 0x00, 0x4b, 0x00,
    0x63, 0x00, 0x00, 0x00, 0x00, 0x7f, 0x00, 0x00,
    0x00, 0x00, 0x4f, 0x00, 0x7f, 0x00, 0x00, 0x00,
])


def _build_sin(entries: list) -> bytes:
    """
    Build a .sin metadata file.

    entries: list of (wav_rel, min_vel, max_vel, rr_index) where:
      wav_rel   - WAV path relative to library/instruments root
      min_vel   - minimum velocity (0-127, inclusive)
      max_vel   - maximum velocity (0-127, inclusive)
      rr_index  - 1-based round-robin index within a velocity band (1 = only/first sample)

    Format confirmed by hex analysis of real multi-velocity preset .sin files:
    28 bytes per mapping; bytes [3]=minVel, [4]=maxVel, [7]=rr_index (1-based).
    """
    inst_block = b'INST' + struct.pack('<I', len(_SIN_INST_BYTES)) + _SIN_INST_BYTES

    count = len(entries)
    msmp_payload = bytearray([0x00, 0x00, count & 0xFF, 0x00])
    for i, (wav_rel, min_vel, max_vel, rr_index) in enumerate(entries):
        m = bytearray(28)
        struct.pack_into('<H', m, 0, i)   # strIdx → i-th WAV in str table
        m[2]  = 0x63
        m[3]  = min_vel & 0xFF
        m[4]  = max_vel & 0xFF
        m[5]  = 0x00
        m[6]  = 0x7F
        m[7]  = max(1, rr_index) & 0xFF
        m[11] = 0x7F
        m[18] = 0x40
        m[24] = 0x3C
        msmp_payload += bytes(m)
    msmp_block = b'msmp' + struct.pack('<I', len(msmp_payload)) + bytes(msmp_payload)

    wav_bytes = b''.join(wr.encode('ascii') + b'\x00' for wr, *_ in entries)
    str_block = b'str ' + struct.pack('<I', len(wav_bytes)) + wav_bytes

    return inst_block + msmp_block + str_block


def _safe_name(s: str) -> str:
    return ''.join(c for c in s if c not in r'\/:*?"<>|').strip()


def _vel_bands(n: int) -> list:
    """Divide 1–127 into n roughly equal velocity bands (ascending order)."""
    if n <= 0:
        return []
    if n == 1:
        return [(1, 127)]
    size  = 127 // n
    bands = []
    for i in range(n):
        lo = 1 + i * size
        hi = lo + size - 1 if i < n - 1 else 127
        bands.append((lo, hi))
    return bands


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


def import_instrument(wav_files: list, category: str, name: str, normalize: bool = False) -> str:
    """
    Create a .sin instrument from one or more WAV files with explicit velocity mapping.

    wav_files: list of (wav_data: bytes, filename: str, min_vel: int, max_vel: int, rr_index: int)
      rr_index is 1-based; use 1 for single-sample-per-band (no round-robin).
    Returns the sin_rel path for the new instrument.
    """
    if not wav_files:
        raise ValueError('No WAV files provided')

    cat  = _safe_name(category) or 'Custom'
    base = _safe_name(name.removesuffix('.wav').removesuffix('.WAV')) or 'Sample'

    dest_dir = LIBRARY_DIR / 'instruments' / cat
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Multi-WAV instruments get their own subdirectory to keep things tidy
    if len(wav_files) > 1:
        sub = base
        ctr = 2
        while (dest_dir / sub).exists():
            sub = f'{base} ({ctr})'
            ctr += 1
        wav_dir = dest_dir / sub
        wav_dir.mkdir(parents=True, exist_ok=True)
    else:
        wav_dir = dest_dir

    norm_notes = []
    entries = []
    for wav_data, filename, min_vel, max_vel, rr_index in wav_files:
        if len(wav_data) < 12 or wav_data[:4] != b'RIFF' or wav_data[8:12] != b'WAVE':
            raise ValueError(f'{filename}: not a valid WAV file')
        if normalize:
            wav_data, peak_info = normalize_wav(wav_data)
            norm_notes.append(f'{Path(filename).stem}: {peak_info}')
        stem = _safe_name(Path(filename).stem) or f'layer_{len(entries)+1}'
        wav_name = stem + '.wav'
        ctr = 2
        while (wav_dir / wav_name).exists():
            wav_name = f'{stem} ({ctr}).wav'
            ctr += 1
        (wav_dir / wav_name).write_bytes(wav_data)
        wav_rel = str((wav_dir / wav_name).relative_to(LIBRARY_DIR / 'instruments')).replace('\\', '/')
        entries.append((wav_rel, int(min_vel), int(max_vel), int(rr_index)))

    # Find unique .sin name
    sin_name = base + '.sin'
    ctr = 2
    while (dest_dir / sin_name).exists():
        sin_name = f'{base} ({ctr}).sin'
        ctr += 1
    sin_path = dest_dir / sin_name
    sin_path.write_bytes(_build_sin(entries))

    sin_rel = str(sin_path.relative_to(LIBRARY_DIR / 'instruments')).replace('\\', '/')
    refresh_available()
    return sin_rel, norm_notes


def import_custom_wav(wav_data: bytes, category: str, name: str) -> str:
    """Single-file import shim — wraps import_instrument for backward compatibility."""
    if len(wav_data) < 12 or wav_data[:4] != b'RIFF' or wav_data[8:12] != b'WAVE':
        raise ValueError('Not a valid WAV file (must be standard uncompressed PCM WAV)')
    sin_rel, _ = import_instrument([(wav_data, name + '.wav', 1, 127, 1)], category, name)
    return sin_rel


def parse_sin_first_wav(data: bytes) -> str | None:
    """
    Parse a .sin file's str block and return the first WAV path.
    The str block holds null-separated WAV filenames ordered by velocity (loudest first).
    Returns a relative path like 'Claps/808 Clap.WAV', or None if not found.
    """
    pos = 0
    while pos + 8 <= len(data):
        magic = data[pos:pos+4]
        size  = struct.unpack_from('<I', data, pos+4)[0]
        if magic == b'str ':
            str_data = data[pos+8 : pos+8+size]
            for raw in str_data.split(b'\x00'):
                s = raw.decode('ascii', errors='replace').strip()
                if s and s.lower().endswith(('.wav', '.wave')):
                    return s
            break
        if pos + 8 + size > len(data):
            break
        pos += 8 + size
    return None


def parse_sin_all_wavs(data: bytes) -> list:
    """Return every WAV path listed in a .sin str block (all velocity layers)."""
    pos = 0
    while pos + 8 <= len(data):
        magic = data[pos:pos+4]
        size  = struct.unpack_from('<I', data, pos+4)[0]
        if magic == b'str ':
            str_data = data[pos+8 : pos+8+size]
            return [
                raw.decode('ascii', errors='replace').strip()
                for raw in str_data.split(b'\x00')
                if raw and raw.decode('ascii', errors='replace').strip().lower().endswith(('.wav', '.wave'))
            ]
        if pos + 8 + size > len(data):
            break
        pos += 8 + size
    return []


# ── .sin instrument parameter editor ───────────────────────────────────────────
# INST 24-byte payload layout decoded by the strike4j project (github.com/cbuschka/strike4j),
# verified here against all 1749 library preset .sin files (constants hold with 0 exceptions).

SIN_GROUPS = {
    0: 'Kick', 1: 'Snare', 2: 'Tom', 3: 'Hi-Hat', 4: 'Crash', 5: 'Ride',
    6: 'Group 6', 7: 'E. Kick', 8: 'E. Snare', 9: 'E. Tom', 10: 'Percussion',
    11: 'Perc Ethnic', 12: 'Group 12', 13: 'Perc Orchestral', 14: 'E. Perc',
    15: 'Group 15', 16: 'Group 16', 17: 'Group 17', 18: 'Claps/SFX', 19: 'Melodic',
}

# name: (offset into INST payload, signed, lo, hi)
_SIN_PARAM_MAP = {
    'group':      (1,  False, 0, 19),
    'level':      (6,  False, 0, 127),
    'pan':        (7,  True, -50, 50),
    'decay':      (8,  False, 0, 127),
    'semi':       (11, True, -12, 12),
    'fine':       (12, True, -50, 50),
    'cutoff':     (13, False, 0, 127),
    'hipass':     (14, False, 0, 1),
    'vel_decay':  (15, True, -99, 99),
    'vel_pitch':  (16, True, -99, 99),
    'vel_filter': (17, True, -99, 99),
    'vel_level':  (18, True, -99, 99),
    'loop':       (21, False, 0, 1),
}

_SIN_MAPPING_SIZE = 28
# per-mapping offsets: str_idx u16 @0, command @2, vel min/max @3/4, rr index @7,
# hihat pedal-open range @10/11 — everything else preserved untouched

def _sin_blocks(data: bytes) -> dict:
    """Walk .sin chunks → {magic: (payload_offset, payload_size)}. Magics: INST/msmp/str ."""
    blocks, pos = {}, 0
    while pos + 8 <= len(data):
        magic = data[pos:pos+4]
        size  = struct.unpack_from('<I', data, pos+4)[0]
        if pos + 8 + size > len(data):
            break
        blocks[magic] = (pos + 8, size)
        pos += 8 + size
    return blocks


def parse_sin(data: bytes) -> dict:
    """Parse a .sin file → {params, cycle_random, mappings, strings}. Raises ValueError."""
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or blocks[b'INST'][1] < 24:
        raise ValueError('Not a valid .sin file (missing INST block)')
    ioff, _ = blocks[b'INST']

    def _val(off, signed):
        v = data[ioff + off]
        return v - 256 if signed and v > 127 else v

    params = {name: _val(off, signed) for name, (off, signed, _, _) in _SIN_PARAM_MAP.items()}

    strings = []
    if b'str ' in blocks:
        soff, ssize = blocks[b'str ']
        strings = [s.decode('ascii', errors='replace')
                   for s in data[soff:soff+ssize].split(b'\x00') if s]

    cycle_random, mappings = 0, []
    if b'msmp' in blocks:
        moff, msize = blocks[b'msmp']
        if msize >= 4:
            cycle_random = data[moff]
            count = data[moff + 2]
            for i in range(count):
                m = moff + 4 + i * _SIN_MAPPING_SIZE
                if m + _SIN_MAPPING_SIZE > moff + msize:
                    break
                str_idx = struct.unpack_from('<H', data, m)[0]
                mappings.append({
                    'sample':  strings[str_idx] if str_idx < len(strings) else f'<str {str_idx}>',
                    'vmin':    data[m + 3],
                    'vmax':    data[m + 4],
                    'rr':      data[m + 7],
                    'hh_min':  data[m + 10],
                    'hh_max':  data[m + 11],
                })
    return {'params': params, 'cycle_random': cycle_random, 'mappings': mappings,
            'strings': strings}


def patch_sin(data: bytes, params: dict = None, cycle_random=None, mappings: list = None) -> bytes:
    """
    Patch known fields of a .sin file in place; every unknown byte is preserved.
    params: {name: value} subset of _SIN_PARAM_MAP (values clamped to documented range).
    cycle_random: 0 = round-robin, 1 = random.
    mappings: [{index, vmin?, vmax?, rr?, hh_min?, hh_max?}] — patches per-mapping bytes.
    """
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or blocks[b'INST'][1] < 24:
        raise ValueError('Not a valid .sin file (missing INST block)')
    out  = bytearray(data)
    ioff = blocks[b'INST'][0]

    for name, value in (params or {}).items():
        if name not in _SIN_PARAM_MAP:
            raise ValueError(f'Unknown .sin param: {name}')
        off, signed, lo, hi = _SIN_PARAM_MAP[name]
        v = max(lo, min(hi, int(value)))
        out[ioff + off] = v & 0xFF

    if (cycle_random is not None or mappings) and b'msmp' not in blocks:
        raise ValueError('.sin file has no msmp block')
    if b'msmp' in blocks:
        moff, msize = blocks[b'msmp']
        if cycle_random is not None:
            out[moff] = 1 if int(cycle_random) else 0
        count = data[moff + 2] if msize >= 4 else 0
        for mp in (mappings or []):
            i = int(mp['index'])
            if not 0 <= i < count:
                raise ValueError(f'Mapping index {i} out of range (count={count})')
            m = moff + 4 + i * _SIN_MAPPING_SIZE
            for key, off in (('vmin', 3), ('vmax', 4), ('rr', 7),
                             ('hh_min', 10), ('hh_max', 11)):
                if key in mp and mp[key] is not None:
                    v = int(mp[key])
                    if key != 'rr':  # rr is signed: 0xFE/-2 marks hi-hat pedal function
                        v = max(0, min(127, v))
                    out[m + off] = v & 0xFF
    return bytes(out)


def rebuild_sin_zones(data: bytes, zones: list, cycle_random=None) -> bytes:
    """
    Rebuild the msmp + str blocks with a new zone list (add/remove/reorder mappings).

    zones: [{src, vmin, vmax, rr?, hh_min?, hh_max?, sample?}] — `src` is the index of an
    ORIGINAL mapping whose 28-byte block is cloned, so every unknown byte comes from a real
    sibling. New samples are appended to the string table; original string order is kept.
    The INST block is passed through untouched.
    """
    blocks = _sin_blocks(data)
    if b'INST' not in blocks or b'msmp' not in blocks or b'str ' not in blocks:
        raise ValueError('Not a rebuildable .sin (missing INST/msmp/str block)')
    if not zones:
        raise ValueError('An instrument needs at least one zone')
    if len(zones) > 255:
        raise ValueError('Too many zones (max 255)')

    old       = parse_sin(data)
    old_count = len(old['mappings'])
    moff, _   = blocks[b'msmp']
    ioff, isize = blocks[b'INST']

    strings = list(old['strings'])
    def _str_idx(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    maps_out = bytearray()
    for z in zones:
        src = int(z.get('src', -1))
        if not 0 <= src < old_count:
            raise ValueError(f'Zone src index {src} out of range (0-{old_count - 1})')
        m   = moff + 4 + src * _SIN_MAPPING_SIZE
        blk = bytearray(data[m:m + _SIN_MAPPING_SIZE])
        orig = old['mappings'][src]
        struct.pack_into('<H', blk, 0, _str_idx(z.get('sample', orig['sample'])))
        blk[3]  = max(0, min(127, int(z['vmin'])))
        blk[4]  = max(0, min(127, int(z['vmax'])))
        blk[7]  = int(z.get('rr', orig['rr'])) & 0xFF
        blk[10] = max(0, min(127, int(z.get('hh_min', orig['hh_min']))))
        blk[11] = max(0, min(127, int(z.get('hh_max', orig['hh_max']))))
        maps_out += blk

    msmp_hdr = bytearray(data[moff:moff + 4])  # preserve unknown header bytes 1 and 3
    if cycle_random is not None:
        msmp_hdr[0] = 1 if int(cycle_random) else 0
    msmp_hdr[2] = len(zones)
    msmp_payload = bytes(msmp_hdr) + bytes(maps_out)
    str_payload  = b''.join(s.encode('ascii', errors='replace') + b'\x00' for s in strings)

    out = (data[:ioff + isize]
           + b'msmp' + struct.pack('<I', len(msmp_payload)) + msmp_payload
           + b'str ' + struct.pack('<I', len(str_payload)) + str_payload)
    out += b'\x00' * (-len(out) % 4)   # module files are 4-byte aligned
    return bytes(out)


def _sin_abs(sin_rel: str) -> 'Path':
    # Prefer the library copy: scan_instruments lets a mounted SD card shadow
    # identical rel paths, but edits must always land in library/instruments.
    lib = LIBRARY_DIR / 'instruments' / sin_rel
    if lib.is_file():
        return lib
    p = state['avail'].get(sin_rel)
    if not p:
        refresh_available()
        p = state['avail'].get(sin_rel)
    if not p:
        raise ValueError(f'Instrument not found: {sin_rel}')
    return p


def _sin_editable(p: 'Path') -> bool:
    """Only instruments inside library/instruments are editable (SD presets stay read-only)."""
    try:
        return p.resolve().is_relative_to((LIBRARY_DIR / 'instruments').resolve())
    except (OSError, ValueError):
        return False


def sin_detail(sin_rel: str) -> dict:
    p = _sin_abs(sin_rel)
    det = parse_sin(p.read_bytes())
    det.pop('strings', None)
    det['sin_rel']   = sin_rel
    det['editable']  = _sin_editable(p)
    det['has_backup'] = sin_rel in state['sin_backups']
    det['groups']    = SIN_GROUPS
    return det


def sin_update(sin_rel: str, params: dict = None, cycle_random=None, mappings: list = None) -> dict:
    p = _sin_abs(sin_rel)
    if not _sin_editable(p):
        raise ValueError('Read-only instrument — sync it to the library to edit a copy')
    data = p.read_bytes()
    state['sin_backups'].setdefault(sin_rel, data)
    p.write_bytes(patch_sin(data, params=params, cycle_random=cycle_random, mappings=mappings))
    det = sin_detail(sin_rel)
    det['message'] = f'Saved {sin_rel}'
    return det


def sin_update_zones(sin_rel: str, zones: list, cycle_random=None, params: dict = None) -> dict:
    """Structural zone edit: rebuild msmp/str, then apply any pending INST param edits."""
    p = _sin_abs(sin_rel)
    if not _sin_editable(p):
        raise ValueError('Read-only instrument — sync it to the library to edit a copy')
    data = p.read_bytes()
    state['sin_backups'].setdefault(sin_rel, data)
    rebuilt = rebuild_sin_zones(data, zones, cycle_random=cycle_random)
    if params:
        rebuilt = patch_sin(rebuilt, params=params)
    parse_sin(rebuilt)  # sanity: must still parse before we write it
    p.write_bytes(rebuilt)
    det = sin_detail(sin_rel)
    det['message'] = f'Zones updated — {len(zones)} mapping(s) in {sin_rel}'
    return det


def sin_revert(sin_rel: str) -> dict:
    original = state['sin_backups'].pop(sin_rel, None)
    if original is None:
        raise ValueError('No backup to revert to')
    p = _sin_abs(sin_rel)
    if not _sin_editable(p):
        raise ValueError('Read-only instrument')
    p.write_bytes(original)
    det = sin_detail(sin_rel)
    det['message'] = f'Reverted {sin_rel} to its pre-edit state'
    return det


def _resolve_wav(wav_rel: str, search_roots: list) -> 'Path | None':
    for root in search_roots:
        p = root / wav_rel
        if p.exists():
            return p
    return None


def _sin_search_roots() -> list:
    roots = []
    lib_inst = LIBRARY_DIR / 'instruments'
    if lib_inst.is_dir():
        roots.append(lib_inst)
    lib_samp = LIBRARY_DIR / 'samples'
    if lib_samp.is_dir():
        roots.append(lib_samp)
    user, preset = get_volumes()
    for vol in (user, preset):
        if vol:
            s = vol / 'Samples'
            if s.is_dir():
                roots.append(s)
    return roots


def get_kit_size() -> dict:
    """Sum WAV file sizes for every instrument in the current kit."""
    pads = state.get('pads', [])
    avail = state.get('avail', {})
    roots = _sin_search_roots()
    seen_wavs: set = set()
    total_bytes = 0
    found = 0
    total = 0
    for pad in pads:
        for sin_key in ('layer_a', 'layer_b'):
            sin_rel = pad.get(sin_key)
            if not sin_rel:
                continue
            sin_abs = avail.get(sin_rel)
            if not sin_abs:
                continue
            try:
                data = Path(sin_abs).read_bytes()
            except OSError:
                continue
            for wav_rel in parse_sin_all_wavs(data):
                if wav_rel in seen_wavs:
                    continue
                seen_wavs.add(wav_rel)
                total += 1
                p = _resolve_wav(wav_rel, roots)
                if p:
                    try:
                        total_bytes += p.stat().st_size
                        found += 1
                    except OSError:
                        pass
    return {'total_bytes': total_bytes, 'found_wavs': found, 'total_wavs': total}


import wave as _wave

_waveform_cache: dict = {}


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


def find_wav_for_sin(sin_rel: str) -> 'Path | None':
    """
    Given a .sin relative path (e.g. 'Claps/808 Clap.sin'), locate the first
    WAV sample file it references and return its absolute path, or None.

    WAV paths inside preset .sin files are relative to <volume>/Samples/.
    WAV paths inside locally-imported .sin files are relative to library/instruments/.
    We search both.
    """
    sin_abs = state['avail'].get(sin_rel)
    if not sin_abs:
        return None
    try:
        data = Path(sin_abs).read_bytes()
    except OSError:
        return None

    wav_rel = parse_sin_first_wav(data)
    if not wav_rel:
        return None
    return _find_wav_in_roots(wav_rel)


def find_wav_for_sin_idx(sin_rel: str, idx: int) -> 'Path | None':
    """Locate the idx-th WAV referenced by a .sin (one per sample mapping)."""
    sin_abs = state['avail'].get(sin_rel)
    if not sin_abs:
        return None
    try:
        wavs = parse_sin_all_wavs(Path(sin_abs).read_bytes())
    except OSError:
        return None
    if not 0 <= idx < len(wavs):
        return None
    return _find_wav_in_roots(wavs[idx])


def _find_wav_in_roots(wav_rel: str) -> 'Path | None':

    # Candidate roots:
    #   1. library/instruments  (locally imported WAVs)
    #   2. library/samples      (synced from SD card via "Sync library" feature)
    #   3. <volume>/Samples     (live SD card)
    search_roots = []
    lib_inst = LIBRARY_DIR / 'instruments'
    if lib_inst.is_dir():
        search_roots.append(lib_inst)
    lib_samples = LIBRARY_DIR / 'samples'
    if lib_samples.is_dir():
        search_roots.append(lib_samples)
    user, preset = get_volumes()
    for vol in (user, preset):
        if vol:
            samples_dir = vol / 'Samples'
            if samples_dir.is_dir():
                search_roots.append(samples_dir)

    for root in search_roots:
        candidate = root / wav_rel
        if candidate.exists():
            return candidate
    return None


def build_skt(kit_raw: bytes, pads: list, instruments: list, tail: bytes = b'') -> bytes:
    """Reassemble a .skt from its components."""
    out = bytearray(kit_raw)

    for pad in pads:
        payload = pad['payload']
        struct.pack_into('<H', payload, LAYER_A_IDX_OFF, pad['layer_a'])
        struct.pack_into('<H', payload, LAYER_B_IDX_OFF, pad['layer_b'])
        blk_size = len(payload)
        out += b'inst'
        out += struct.pack('<I', blk_size)
        out += bytes(payload)

    # Build the str table (null-terminated strings, concatenated)
    str_bytes = b''.join(s.encode('ascii') + b'\x00' for s in instruments)
    out += b'str '
    out += struct.pack('<I', len(str_bytes))
    out += str_bytes
    out += tail

    return bytes(out)


# ── Global mutable state ───────────────────────────────────────────────────────

state = {
    'kit_path':    None,
    'kit_display': '',   # display name for the loaded kit (used to key the time machine)
    'kit_raw':     None,
    'pads':        [],
    'instruments': [],   # str table for the current kit
    'tail':        b'',  # bytes after the str block (null padding, preserved for lossless save)
    'skt_lossless': True, # False if parse→build doesn't reproduce the original bytes exactly
    'avail':       {},   # {rel_path: abs_path} from scanning volumes
    'dirty':       False,
    'message':     '',
    'history':     [],   # undo stack: list of {pads, instruments} snapshots
    'sin_backups': {},   # {sin_rel: original bytes} — first-edit backups for Revert
    'sel_pad':     None, # pad id mirrored from the browser UI (for external controllers)
    'param_rev':   0,    # bumped on every set_pad_param so pollers can detect changes
}


def load_kit(path_str: str):
    p = Path(path_str)
    data = p.read_bytes()
    kit_raw, pads, instruments, tail = parse_skt(data)
    rebuilt  = build_skt(kit_raw, pads, instruments, tail)
    lossless = (rebuilt == data)
    if not lossless:
        print(f'[warn] {p.name}: round-trip check FAILED ({len(data)}B → {len(rebuilt)}B)', flush=True)
    state['kit_path']     = str(p)
    state['kit_display']  = p.name
    state['kit_raw']      = kit_raw
    state['pads']         = pads
    state['instruments']  = instruments
    state['tail']         = tail
    state['skt_lossless'] = lossless
    state['dirty']        = False
    state['history']      = []
    state['message']      = f"Loaded {p.name}"
    _auto_snapshot(f'Loaded {p.name}', 'load')


def refresh_available():
    roots = find_volumes()
    lib_inst = LIBRARY_DIR / 'instruments'
    if lib_inst.is_dir() and lib_inst not in roots:
        roots = [lib_inst] + roots   # library first so it's always available
    state['avail'] = scan_instruments(roots)


def assign_instrument(pad_id: str, layer: str, sin_rel: str):
    """Set pad layer_a or layer_b to the given .sin relative path."""
    short = sin_rel.rsplit('/', 1)[-1].removesuffix('.sin').removesuffix('.SIN')
    _push_history(f'Assign {short} → {pad_id}')
    instruments = state['instruments']
    if sin_rel not in instruments:
        instruments.append(sin_rel)
    idx = instruments.index(sin_rel)

    for pad in state['pads']:
        if pad['id'] == pad_id:
            if layer == 'a':
                pad['layer_a'] = idx
            else:
                pad['layer_b'] = idx
            break

    state['dirty'] = True
    state['message'] = f"Assigned {sin_rel} → {pad_id} Layer {'A' if layer=='a' else 'B'}"


def clear_instrument(pad_id: str, layer: str):
    _push_history(f'Clear {pad_id} Layer {"A" if layer == "a" else "B"}')
    for pad in state['pads']:
        if pad['id'] == pad_id:
            if layer == 'a':
                pad['layer_a'] = NO_INSTRUMENT
            else:
                pad['layer_b'] = NO_INSTRUMENT
            break
    state['dirty'] = True
    state['message'] = f"Cleared {pad_id} Layer {'A' if layer=='a' else 'B'}"


_PARAM_MAP = {
    'midi_note': (MIDI_NOTE_OFF, 'B',   0,   127),
    'la_level':  (LA_LEVEL_OFF,  'B',   0,   127),
    'la_pan':    (LA_PAN_OFF,    'b',  -50,    50),
    'la_pitch':  (LA_PITCH_OFF,  'b',  -12,    12),
    'la_decay':    (LA_DECAY_OFF,    'B',   0,    99),
    'la_vel_dec':  (LA_VEL_DEC_OFF,  'B',   0,   127),
    'la_vel_pch':  (LA_VEL_PCH_OFF,  'B',   0,   127),
    'la_vel_flt':  (LA_VEL_FLT_OFF,  'B',   0,   127),
    'la_vel_vol':  (LA_VEL_VOL_OFF,  'B',   0,   127),
    'la_fcut':     (LA_FCUT_OFF,     'B',   0,    99),
    'la_fflag':    (LA_FFLAG_OFF,    'B',   0,     1),
    'la_fine':     (LA_FINE_OFF,     'b',  -50,    50),
    'la_loop':     (LA_LOOP_OFF,     'B',   0,     1),
    'la_vel_min':  (LA_VEL_MIN_OFF,  'B',   0,   127),
    'la_vel_max':  (LA_VEL_MAX_OFF,  'B',   0,   127),
    'lb_level':    (LB_LEVEL_OFF,    'B',   0,   127),
    'lb_pan':      (LB_PAN_OFF,      'b',  -50,    50),
    'lb_pitch':    (LB_PITCH_OFF,    'b',  -12,    12),
    'lb_decay':    (LB_DECAY_OFF,    'B',   0,    99),
    'lb_vel_dec':  (LB_VEL_DEC_OFF,  'B',   0,   127),
    'lb_vel_pch':  (LB_VEL_PCH_OFF,  'B',   0,   127),
    'lb_vel_flt':  (LB_VEL_FLT_OFF,  'B',   0,   127),
    'lb_vel_vol':  (LB_VEL_VOL_OFF,  'B',   0,   127),
    'xfade_vel':   (XFADE_VEL_OFF,   'B',   0,   127),
    'lb_fcut':     (LB_FCUT_OFF,     'B',   0,    99),
    'lb_fflag':    (LB_FFLAG_OFF,    'B',   0,     1),
    'lb_fine':     (LB_FINE_OFF,     'b',  -50,    50),
    'lb_loop':     (LB_LOOP_OFF,     'B',   0,     1),
    'reverb':      (REVERB_OFF,      'B',   0,    99),
    'fx1':         (FX1_OFF,         'B',   0,    99),
    'fx2':         (FX2_OFF,         'B',   0,    99),
    'eq_comp':     (EQ_COMP_OFF,     'B',   0,     1),
    'priority':    (PRIORITY_OFF,    'B',   0,     2),
    'note_off':    (NOTE_OFF_OFF,    'B',   0,     2),
    'midi_chan':   (MIDI_CHAN_OFF,   'B',   0,    15),
    'play_mode':   (PLAY_MODE_OFF,   'B',   0,     1),
}

# Gate time (off 53) is non-contiguous: 0–99 = Free gate length in ms,
# 100–109 = Sync:32/32T/16/16T/8/8T/4/4T/2/2T, 255 = OFF.
GATE_SYNC_NAMES = ['Sync:1/32', 'Sync:1/32T', 'Sync:1/16', 'Sync:1/16T',
                   'Sync:1/8', 'Sync:1/8T', 'Sync:1/4', 'Sync:1/4T',
                   'Sync:1/2', 'Sync:1/2T']


def _valid_gate_time(v: int) -> bool:
    return 0 <= v <= 109 or v == 255


def set_pad_param(pad_id: str, param: str, value: int, coalesce: bool = False):
    """Write a single numeric parameter into the pad payload bytearray.

    coalesce=True (dial/encoder streams): skip the history push when the last
    undo entry is the same pad+param, so a twist is one undo step, not twenty.
    """
    if not (coalesce and state['history']
            and state['history'][-1].get('label', '').startswith(f'{pad_id} {param} = ')):
        _push_history(f'{pad_id} {param} = {value}')
    for pad in state['pads']:
        if pad['id'] != pad_id:
            continue
        if param == 'mute_grp':
            if not (0 <= value <= 9):
                raise ValueError(f'mute_grp {value} out of range [0, 9]')
            pad['payload'][MUTE_GRP_OFF] = value
        elif param == 'midi_chan':
            if not (1 <= value <= 16):
                raise ValueError(f'midi_chan {value} out of range [1, 16]')
            pad['payload'][MIDI_CHAN_OFF] = value - 1
        elif param == 'gate_time':
            if not _valid_gate_time(value):
                raise ValueError(f'gate_time {value} invalid (0–99 ms, 100–109 sync, 255 off)')
            pad['payload'][GATE_TIME_OFF] = value
        elif param in _PARAM_MAP:
            off, fmt, lo, hi = _PARAM_MAP[param]
            if not (lo <= value <= hi):
                raise ValueError(f'{param} value {value} out of range [{lo}, {hi}]')
            struct.pack_into(fmt, pad['payload'], off, value)
        else:
            raise ValueError(f'Unknown param: {param!r}. Valid: {list(_PARAM_MAP)} + mute_grp')
        state['dirty']     = True
        state['message']   = f'{pad_id} {param} = {value}'
        state['param_rev'] += 1
        return
    raise ValueError(f'Pad not found: {pad_id}')


def selected_view():
    """Selected pad + the dial-editable params, for external controllers (Loupedeck)."""
    pid = state.get('sel_pad')
    pad = next((p for p in state['pads'] if p['id'] == pid), None) if pid else None
    if pad is None:
        return {'pad_id': None, 'rev': state['param_rev']}
    pl    = pad['payload']
    pitch = pl[LA_PITCH_OFF]
    return {
        'pad_id': pid,
        'label':  pad.get('label', pid),
        'rev':    state['param_rev'],
        'params': {
            'la_level': pl[LA_LEVEL_OFF],
            'la_pitch': pitch - 256 if pitch > 127 else pitch,
            'la_decay': pl[LA_DECAY_OFF],
            'la_fcut':  pl[LA_FCUT_OFF],
        },
    }


def kit_playback_manifest() -> dict:
    """One self-contained manifest for the loaded kit, consumed by the browser
    'Virtual module' engine to play the kit being edited straight from the drum pads
    (see GET /api/kit_playback). Per pad → per assigned layer → .skt payload params
    + .sin INST params + velocity mappings + WAV URLs.

    Reuses the same offset constants as _pad_view() and the same per-mapping WAV
    resolution as /api/wav (mapping index i == idx into parse_sin_all_wavs), so no
    parsing/offset logic is duplicated. Per-instrument parse failures are non-fatal:
    the layer entry carries an 'error' string and the rest of the manifest still builds.
    """
    instruments = state['instruments']
    _sin_cache = {}
    seen_urls = set()
    total_bytes = 0

    def _u8(pl, off):
        return pl[off] if off < len(pl) else 0

    def _i8(pl, off):
        v = pl[off] if off < len(pl) else 0
        return v - 256 if v > 127 else v

    def _layer(idx, skt):
        nonlocal total_bytes
        if idx == NO_INSTRUMENT or idx >= len(instruments):
            return None
        sin_rel = instruments[idx]
        entry = {'sin_rel': sin_rel, 'skt': skt}
        try:
            if sin_rel not in _sin_cache:
                _sin_cache[sin_rel] = parse_sin(_sin_abs(sin_rel).read_bytes())
            det = _sin_cache[sin_rel]
        except Exception as e:
            entry['error'] = str(e)
            return entry
        sp = det['params']
        entry['sin'] = {k: sp[k] for k in ('level', 'pan', 'semi', 'fine', 'decay', 'loop')}
        entry['cycle_random'] = det['cycle_random']
        maps_out = []
        for i, m in enumerate(det['mappings']):
            wav = find_wav_for_sin_idx(sin_rel, i)
            url, size = None, 0
            if wav:
                url = '/api/wav?sin=' + quote(sin_rel) + '&idx=' + str(i)
                try:
                    size = wav.stat().st_size
                except OSError:
                    size = 0
                if url not in seen_urls:
                    seen_urls.add(url)
                    total_bytes += size
            maps_out.append({
                'idx': i, 'vmin': m['vmin'], 'vmax': m['vmax'], 'rr': m['rr'],
                'hh_min': m['hh_min'], 'hh_max': m['hh_max'], 'wav_url': url, 'size': size,
            })
        entry['mappings'] = maps_out
        return entry

    pads_out = []
    for p in state['pads']:
        pl = p['payload']
        la = _layer(p['layer_a'], {
            'level': _u8(pl, LA_LEVEL_OFF), 'pan': _i8(pl, LA_PAN_OFF),
            'pitch': _i8(pl, LA_PITCH_OFF), 'fine': _i8(pl, LA_FINE_OFF),
            'decay': _u8(pl, LA_DECAY_OFF),
            'vel_min': _u8(pl, LA_VEL_MIN_OFF), 'vel_max': _u8(pl, LA_VEL_MAX_OFF),
        })
        lb = _layer(p['layer_b'], {
            'level': _u8(pl, LB_LEVEL_OFF), 'pan': _i8(pl, LB_PAN_OFF),
            'pitch': _i8(pl, LB_PITCH_OFF), 'fine': _i8(pl, LB_FINE_OFF),
            'decay': _u8(pl, LB_DECAY_OFF),
            'vel_min': _u8(pl, XFADE_VEL_OFF), 'vel_max': 127,
        })
        layers = {}
        if la:
            layers['a'] = la
        if lb:
            layers['b'] = lb
        pads_out.append({
            'id': p['id'], 'label': p['label'],
            'midi_note': _u8(pl, MIDI_NOTE_OFF),
            'mute_grp': _u8(pl, MUTE_GRP_OFF),
            'play_mode': _u8(pl, PLAY_MODE_OFF),
            'layers': layers,
        })

    return {
        'rev': state['param_rev'],
        'kit': Path(state['kit_path']).name if state.get('kit_path') else None,
        'pads': pads_out,
        'total_bytes': total_bytes,
    }


MAX_UNDO_STEPS = 20


def _snapshot():
    """Deep-copy mutable state (pads + instruments + KIT header) so it can be restored by undo."""
    return {
        'pads':        [{**p, 'payload': bytearray(p['payload'])} for p in state['pads']],
        'instruments': list(state['instruments']),
        'kit_raw':     bytes(state['kit_raw']) if state.get('kit_raw') else None,
    }


def _push_history(label: str = ''):
    """Capture the current state before a mutation."""
    snap = _snapshot()
    snap['label'] = label
    state['history'].append(snap)
    if len(state['history']) > MAX_UNDO_STEPS:
        state['history'].pop(0)
    # Every undoable mutation flags a change so pollers (Loupedeck /api/selected,
    # Virtual-module /api/kit_playback) can refresh. set_pad_param bumps separately
    # for coalesced dial twists, which skip the history push.
    state['param_rev'] += 1


def _history_labels() -> list:
    """Return action labels for the undo stack, newest first."""
    return [h.get('label', '') for h in reversed(state['history'])]


def undo():
    """Restore the previous pad/instrument state from the undo stack."""
    if not state['history']:
        raise ValueError('Nothing to undo')
    snap = state['history'].pop()
    state['pads']        = snap['pads']
    state['instruments'] = snap['instruments']
    if snap.get('kit_raw') is not None:
        state['kit_raw'] = snap['kit_raw']
    state['dirty']       = True
    state['message']     = 'Undo'
    state['param_rev']  += 1


def copy_pad(from_id: str, to_id: str):
    """Copy all pad params and instrument assignments from one pad to another."""
    from_pad = next((p for p in state['pads'] if p['id'] == from_id), None)
    to_pad   = next((p for p in state['pads'] if p['id'] == to_id),   None)
    if not from_pad:
        raise ValueError(f'Source pad not found: {from_id}')
    if not to_pad:
        raise ValueError(f'Target pad not found: {to_id}')
    _push_history(f'Copy {from_id} → {to_id}')
    new_payload     = bytearray(from_pad['payload'])
    new_payload[:4] = to_pad['payload'][:4]   # preserve target pad-ID bytes
    to_pad['payload'] = new_payload
    to_pad['layer_a'] = from_pad['layer_a']
    to_pad['layer_b'] = from_pad['layer_b']
    state['dirty']   = True
    state['message'] = f'Copied {from_id} → {to_id}'


def check_paths() -> dict:
    """Return sin_rel paths in the current kit that cannot be found in avail."""
    avail       = state.get('avail', {})
    instruments = state.get('instruments', [])
    broken = []
    for pad in state.get('pads', []):
        for key in ('layer_a', 'layer_b'):
            idx = pad.get(key)
            if idx is None or idx == NO_INSTRUMENT or idx >= len(instruments):
                continue
            sin_rel = instruments[idx]
            if sin_rel not in avail and sin_rel not in broken:
                broken.append(sin_rel)
    return {'broken': broken}


def relink_suggestions() -> dict:
    """For each broken sin_rel in the current kit, suggest replacements from avail.
    Exact (case-insensitive) filename matches first; otherwise fuzzy stem matches."""
    import difflib
    avail  = state.get('avail', {})
    broken = check_paths()['broken']
    by_base = {}
    for rel in avail:
        by_base.setdefault(rel.rsplit('/', 1)[-1].lower(), []).append(rel)
    out = []
    for b in broken:
        base  = b.rsplit('/', 1)[-1].lower()
        cands = [{'rel': r, 'score': 1.0} for r in sorted(by_base.get(base, []))]
        if not cands:
            stem   = base.removesuffix('.sin')
            scored = []
            for rel in avail:
                rstem = rel.rsplit('/', 1)[-1].lower().removesuffix('.sin')
                s = difflib.SequenceMatcher(None, stem, rstem).ratio()
                if s >= 0.6:
                    scored.append((s, rel))
            scored.sort(key=lambda t: (-t[0], t[1]))
            cands = [{'rel': r, 'score': round(s, 2)} for s, r in scored[:8]]
        out.append({'broken': b, 'candidates': cands})
    return {'suggestions': out}


def relink_apply(mapping: dict) -> int:
    """Rewrite instrument-table strings per {broken_rel: replacement_rel}.
    One undo entry; affects every pad referencing the old path."""
    if not mapping:
        raise ValueError('Nothing to relink')
    for old, new in mapping.items():
        if new not in state['avail']:
            raise ValueError(f'Replacement not found: {new}')
        if old not in state['instruments']:
            raise ValueError(f'Not referenced by current kit: {old}')
    _push_history(f'Relink {len(mapping)} instrument path(s)')
    n = 0
    for i, rel in enumerate(state['instruments']):
        if rel in mapping:
            state['instruments'][i] = mapping[rel]
            n += 1
    state['dirty']   = True
    state['message'] = f'Relinked {n} instrument reference(s)'
    return n


# ── Kit FX editor (layout hardware-confirmed — see CLAUDE.md/FORMAT.md) ────────

# 0-based with no Off entry (0xFF = off) — anchored by hex diff: 0=Mono Flanger,
# 1=Stereo Flanger, 3=Mono Chorus 1; remainder inferred from the manuals' table order.
SKT_FX_TYPES = ['Mono Flanger', 'Stereo Flanger', 'Xover Flanger',
                'Mono Chorus 1', 'Mono Chorus 2', 'Stereo Chorus', 'XOver Chorus',
                'Mono Vibrato', 'Vibrato', 'Mono Doubler', 'Doubler',
                'Mono Slapback', 'Slapback', 'Mono Delay', 'Delay',
                'XOver Delay', 'Ping Pong']

# Reverb type names: only these two are hex-diff-anchored; the module uses indices
# 0–21 across factory kits but no published list exists (official editor shows a bare
# 0–99 number). Unknown indices render as "Type N".
SKT_REVERB_TYPES = {2: 'Big Gate', 3: 'Close Mic'}
SKT_REVERB_MAX_SEEN = 21   # highest index observed in the 133-kit factory scan

# Compressor presets in official-editor dropdown order ("Off, Master 1, Radio 1–2,
# Soft Hyper, Bright, Country, Crunch, Dance, Hip Hop, Jazz, Lo Boost, Rock 1–3").
# 0=Master 1 and 1=Radio 1 are hex-diff-confirmed; Off appears to be the per-pad
# EQ/Comp enable rather than a preset index.
SKT_COMP_PRESETS = ['Master 1', 'Radio 1', 'Radio 2', 'Soft Hyper', 'Bright',
                    'Country', 'Crunch', 'Dance', 'Hip Hop', 'Jazz', 'Lo Boost',
                    'Rock 1', 'Rock 2', 'Rock 3']

# EQ freq bytes are sequential table indices (LF: 10=58 Hz, 11=66 Hz; HF: 77=8.7 kHz,
# 78=9.1 kHz; full 20 Hz–18.5 kHz table not yet enumerated) — edited as raw indices.
_KIT_FX_KNOWN_FREQS = {10: '58 Hz', 11: '66 Hz', 77: '8.7 kHz', 78: '9.1 kHz'}

_KIT_FX_PARAM_MAP = {
    # name: (kit_raw offset, fmt, lo, hi) — offsets include the 8-byte chunk header
    'reverb_type':    (16, 'B',  0,   99),
    'reverb_size':    (17, 'B',  0,   99),
    'reverb_color':   (18, 'B',  0,   99),
    'reverb_level':   (19, 'B',  0,   99),
    'fx1_type':       (20, 'B',  0,  255),   # 0–16 = SKT_FX_TYPES, 255 = Off
    'fx1_level':      (21, 'B',  0,   99),
    'fx1_delay_ms':   (22, '<H', 0, 3000),   # u16 LE, delay-family types only
    'fx1_feedback':   (26, 'B',  0,   99),
    'fx1_depth':      (28, 'B',  0,   99),
    'fx1_rate':       (29, 'B',  0,   99),
    'fx2_type':       (32, 'B',  0,  255),
    'fx2_level':      (33, 'B',  0,   99),
    'fx2_delay_ms':   (34, '<H', 0, 3000),
    'fx2_feedback':   (38, 'B',  0,   99),
    'fx2_depth':      (40, 'B',  0,   99),
    'fx2_rate':       (41, 'B',  0,   99),
    'comp_preset':    (44, 'B',  0,   13),   # SKT_COMP_PRESETS index
    'comp_threshold': (45, 'b', -90,   0),
    'eq_hf_gain':     (46, 'b', -60,  12),
    'eq_lf_gain':     (47, 'b', -60,  12),
    'eq_lf_freq':     (48, 'B',  0,  127),
    'comp_output':    (49, 'b', -24,  24),
    'eq_hf_freq':     (50, 'B',  0,  127),
}


def set_kit_fx(param: str, value: int):
    """Write one kit-level FX parameter into the KIT header (kit_raw)."""
    if not state.get('kit_raw'):
        raise ValueError('No kit loaded')
    if param not in _KIT_FX_PARAM_MAP:
        raise ValueError(f'Unknown kit FX param: {param!r}')
    off, fmt, lo, hi = _KIT_FX_PARAM_MAP[param]
    if param in ('fx1_type', 'fx2_type'):
        if not (0 <= value < len(SKT_FX_TYPES) or value == 0xFF):
            raise ValueError(f'{param} {value} invalid (0–{len(SKT_FX_TYPES)-1} or 255=Off)')
    elif not (lo <= value <= hi):
        raise ValueError(f'{param} value {value} out of range [{lo}, {hi}]')
    k = bytearray(state['kit_raw'])
    if len(k) < 52:
        raise ValueError(f'KIT block unexpectedly small ({len(k)} bytes)')
    _push_history(f'Kit FX {param} = {value}')
    struct.pack_into(fmt, k, off, value)
    state['kit_raw'] = bytes(k)
    state['dirty']   = True
    state['message'] = f'Kit FX: {param} = {value}'


def kit_fx_view() -> dict:
    """Decode the loaded kit's KIT header per the hardware-confirmed layout. Never writes.
    Offsets below are kit_raw-relative (payload + 8-byte chunk header)."""
    if not state.get('kit_raw'):
        raise ValueError('No kit loaded')
    k = state['kit_raw']
    if len(k) < 52:
        raise ValueError(f'KIT block unexpectedly small ({len(k)} bytes)')

    def s8(v): return v - 256 if v > 127 else v

    def fx(base):
        t = k[base]
        name = (SKT_FX_TYPES[t] if t < len(SKT_FX_TYPES)
                else 'Off' if t == 0xFF else f'type {t} (?)')
        return {
            'type':      t,
            'type_name': name,
            'level':     k[base + 1],
            'delay_ms':  struct.unpack_from('<H', k, base + 2)[0],  # delay-family types
            'feedback':  k[base + 6],
            'depth':     k[base + 8],
            'rate':      k[base + 9],
        }

    return {
        'reverb': {'type': k[16], 'size': k[17], 'color': k[18], 'level': k[19],
                   'type_name': SKT_REVERB_TYPES.get(k[16], f'Type {k[16]}')},
        'fx1':    fx(20),
        'fx2':    fx(32),
        'eq_comp': {
            'comp_preset':  k[44],
            'threshold_db': s8(k[45]),
            'hf_gain_db':   s8(k[46]),
            'lf_gain_db':   s8(k[47]),
            'lf_freq_idx':  k[48],
            'output_db':    s8(k[49]),
            'hf_freq_idx':  k[50],
        },
        # enums for the editor UI
        'fx_types':        SKT_FX_TYPES,
        'reverb_names':    SKT_REVERB_TYPES,
        'reverb_max_seen': SKT_REVERB_MAX_SEEN,
        'comp_presets':    SKT_COMP_PRESETS,
        'known_freqs':     _KIT_FX_KNOWN_FREQS,
    }


# ── Kit bundles (.zip with instruments + samples) ───────────────────────────────
# Layout: manifest.json + kit/<name>.skt + instruments/<sin_rel> + samples/<wav_rel>.
# Rel paths inside the zip mirror the library layout, so import needs no path rewriting:
# .sin internal WAV strings keep resolving via _sin_search_roots().

def export_bundle() -> tuple:
    """Bundle the current kit (incl. unsaved edits) → (zip_bytes, filename)."""
    import zipfile, datetime
    if not state.get('kit_path'):
        raise ValueError('No kit loaded')
    kit_name = Path(state['kit_path']).name
    kit_raw  = build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail'])

    used = []
    for pad in state['pads']:
        for key in ('layer_a', 'layer_b'):
            idx = pad.get(key)
            if idx is not None and idx != NO_INSTRUMENT and idx < len(state['instruments']):
                rel = state['instruments'][idx]
                if rel not in used:
                    used.append(rel)

    roots = _sin_search_roots()
    sins, wavs, missing_sins, missing_wavs = {}, {}, [], []
    for rel in used:
        p = state['avail'].get(rel)
        if not p:
            missing_sins.append(rel)
            continue
        data = Path(p).read_bytes()
        sins[rel] = data
        for wav_rel in parse_sin_all_wavs(data):
            if wav_rel in wavs or wav_rel in missing_wavs:
                continue
            wp = _resolve_wav(wav_rel, roots)
            if wp:
                wavs[wav_rel] = wp
            else:
                missing_wavs.append(wav_rel)

    manifest = {
        'format':  'strike-bundle', 'version': 1, 'module': 'strike',
        'kit':     kit_name,
        'created': datetime.datetime.now().isoformat(timespec='seconds'),
        'instruments': sorted(sins), 'samples': sorted(wavs),
        'missing': {'instruments': missing_sins, 'samples': missing_wavs},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))
        zf.writestr(f'kit/{kit_name}', kit_raw)
        for rel, data in sins.items():
            zf.writestr(f'instruments/{rel}', data)
        for wav_rel, wp in wavs.items():
            zf.write(wp, f'samples/{wav_rel}')
    fname = kit_name.rsplit('.', 1)[0] + '.strike-bundle.zip'
    return buf.getvalue(), fname


def _classify_zip_entry(parts: tuple, sin_wav_rels: dict) -> 'tuple | None':
    """Map one zip entry path → (kind, rel) in library layout, or None to skip.

    Handles our strike-bundle layout (kit/, instruments/, samples/), the official
    Strike Editor export layout and commercial pack zips (Kits/, Instruments/,
    Samples/ mirroring the SD card, possibly nested inside a pack folder), and
    loose .skt/.sin/.wav files via extension + basename fallbacks."""
    name = parts[-1]
    ext  = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    lower = [p.lower() for p in parts[:-1]]

    def after(*folder_names):
        # rel path after the LAST matching folder segment (handles pack-name nesting)
        for i in range(len(lower) - 1, -1, -1):
            if lower[i] in folder_names:
                return '/'.join(parts[i+1:])
        return None

    if ext == 'skt':
        return ('kits', name)                       # kits are always flat
    if ext == 'sin':
        rel = after('instruments', 'strikeinstruments')
        if rel is None:
            # module requires .sin inside one subfolder — synthesize from parent dir
            rel = f'{parts[-2]}/{name}' if len(parts) >= 2 else f'Imported/{name}'
        return ('instruments', rel)
    if ext in ('wav', 'wave'):
        rel = after('samples')
        if rel is None:
            # match by basename against wav paths referenced by .sin files in this zip
            rel = sin_wav_rels.get(name.lower())
        if rel is None:
            rel = '/'.join(parts[1:]) if len(parts) >= 2 else name
        return ('samples', rel)
    return None


def import_bundle(zip_bytes: bytes) -> dict:
    """Unpack a kit/instrument zip into the library. Accepts strike-bundle zips,
    official Strike Editor exports, and commercial pack zips (eDrumWorkshop etc.).
    Existing files are never overwritten: identical ones count as skipped,
    different ones as conflicts."""
    import zipfile
    from pathlib import PurePosixPath
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    entries = []
    for n in zf.namelist():
        if n.endswith('/') or PurePosixPath(n).name in ('manifest.json', '.DS_Store'):
            continue
        parts = PurePosixPath(n).parts
        if not parts or any(p in ('..', '') for p in parts) or PurePosixPath(n).is_absolute():
            continue  # blocks zip-slip
        entries.append((n, parts))

    # Pre-scan .sin files for their referenced WAV rel paths so loose WAVs can be
    # placed where instrument resolution expects them (basename → samples-rel).
    sin_wav_rels = {}
    for n, parts in entries:
        if parts[-1].lower().endswith('.sin'):
            try:
                for wav_rel in parse_sin_all_wavs(zf.read(n)):
                    base = wav_rel.replace('\\', '/').rsplit('/', 1)[-1].lower()
                    sin_wav_rels.setdefault(base, wav_rel.replace('\\', '/'))
            except Exception:
                pass  # malformed .sin → fall back to path-based placement

    kit_names = []
    counts = {'kits': 0, 'instruments': 0, 'samples': 0, 'skipped': 0, 'conflicts': []}
    for n, parts in entries:
        classified = _classify_zip_entry(parts, sin_wav_rels)
        if not classified:
            continue
        kind, rel = classified
        if any(p in ('..', '') for p in PurePosixPath(rel).parts):
            continue
        dest_dir = LIBRARY_DIR / kind
        data = zf.read(n)
        dest = dest_dir / rel
        if kind == 'kits':
            # never clobber an existing kit — find a free " (n)" name instead
            base, ext = dest.stem, dest.suffix
            ctr = 2
            while dest.exists() and dest.read_bytes() != data:
                dest = dest_dir / f'{base} ({ctr}){ext}'
                ctr += 1
            if dest.exists():
                counts['skipped'] += 1
                kit_names.append(dest.name)
                continue
            kit_names.append(dest.name)
        elif dest.exists():
            if dest.read_bytes() == data:
                counts['skipped'] += 1
            else:
                counts['conflicts'].append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        counts[kind] += 1

    if not kit_names and not counts['instruments'] and not counts['samples']:
        raise ValueError('No .skt, .sin, or .wav files found in zip — not a kit/instrument bundle')
    refresh_available()
    counts['kit_names'] = kit_names
    return counts


def swap_pads(pad_id_a: str, pad_id_b: str):
    """Swap full instrument assignments and params between two pads."""
    pad_a = next((p for p in state['pads'] if p['id'] == pad_id_a), None)
    pad_b = next((p for p in state['pads'] if p['id'] == pad_id_b), None)
    if not pad_a:
        raise ValueError(f'Pad not found: {pad_id_a}')
    if not pad_b:
        raise ValueError(f'Pad not found: {pad_id_b}')
    _push_history(f'Swap {pad_id_a} ⇔ {pad_id_b}')
    new_a = bytearray(pad_b['payload'])
    new_a[:4] = pad_a['payload'][:4]   # keep pad-ID bytes
    new_b = bytearray(pad_a['payload'])
    new_b[:4] = pad_b['payload'][:4]
    pad_a['payload'] = new_a
    pad_b['payload'] = new_b
    pad_a['layer_a'], pad_b['layer_a'] = pad_b['layer_a'], pad_a['layer_a']
    pad_a['layer_b'], pad_b['layer_b'] = pad_b['layer_b'], pad_a['layer_b']
    state['dirty']   = True
    state['message'] = f'Swapped {pad_id_a} ⇔ {pad_id_b}'


def batch_set_param(pad_ids: list, param: str, value: int):
    """Apply a single parameter change to multiple pads at once (single undo entry)."""
    _push_history(f'Batch {param}={value} ({len(pad_ids)} pads)')
    changed = 0
    for pad in state['pads']:
        if pad['id'] not in pad_ids:
            continue
        if param == 'mute_grp':
            if not (0 <= value <= 9):
                raise ValueError(f'mute_grp {value} out of range')
            pad['payload'][MUTE_GRP_OFF] = value
        elif param == 'midi_chan':
            if not (1 <= value <= 16):
                raise ValueError(f'midi_chan {value} out of range [1, 16]')
            pad['payload'][MIDI_CHAN_OFF] = value - 1
        elif param == 'gate_time':
            if not _valid_gate_time(value):
                raise ValueError(f'gate_time {value} invalid (0–99 ms, 100–109 sync, 255 off)')
            pad['payload'][GATE_TIME_OFF] = value
        elif param in _PARAM_MAP:
            off, fmt, lo, hi = _PARAM_MAP[param]
            if not (lo <= value <= hi):
                raise ValueError(f'{param} value {value} out of range [{lo}, {hi}]')
            struct.pack_into(fmt, pad['payload'], off, value)
        else:
            raise ValueError(f'Unknown param: {param!r}')
        changed += 1
    state['dirty']   = True
    state['message'] = f'Batch set {param}={value} on {changed} pads'


_TAGS_PATH = LIBRARY_DIR / 'tags.json'


def load_tags() -> dict:
    """Return {sin_rel: [tag, ...]} from library/tags.json."""
    if _TAGS_PATH.exists():
        try:
            return json.loads(_TAGS_PATH.read_text('utf-8'))
        except Exception:
            pass
    return {}


def save_tags(tags: dict):
    _TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TAGS_PATH.write_text(json.dumps(tags, indent=2, ensure_ascii=False), 'utf-8')


def set_instrument_tags(sin_rel: str, tags: list):
    """Set the tag list for a single instrument, persisting to tags.json."""
    data = load_tags()
    clean = [t.strip() for t in tags if t.strip()]
    if clean:
        data[sin_rel] = clean
    else:
        data.pop(sin_rel, None)
    save_tags(data)


def batch_assign_csv(assignments: list) -> dict:
    """Assign instruments from a list of {pad_id, layer, sin_rel} dicts. Single undo entry."""
    _push_history(f'CSV assign ({len(assignments)} rows)')
    changed, skipped = 0, []
    avail = state.get('avail', {})
    for row in assignments:
        pad_id  = str(row.get('pad_id', '')).strip().upper()
        layer   = str(row.get('layer', 'a')).strip().lower()
        sin_rel = str(row.get('sin_rel', '')).strip()
        if not pad_id or not sin_rel:
            continue
        if sin_rel not in avail:
            skipped.append(sin_rel)
            continue
        instruments = state['instruments']
        if sin_rel not in instruments:
            instruments.append(sin_rel)
        idx = instruments.index(sin_rel)
        for pad in state['pads']:
            if pad['id'] == pad_id:
                if layer == 'b':
                    pad['layer_b'] = idx
                else:
                    pad['layer_a'] = idx
                changed += 1
                break
    state['dirty'] = True
    msg = f'CSV assigned {changed} pads'
    if skipped:
        msg += f' ({len(skipped)} instruments not in library)'
    state['message'] = msg
    return {'changed': changed, 'skipped': skipped}


# Per-pad fields compared by the diff engine (both kit-vs-kit and snapshot-vs-snapshot).
_DIFF_KEYS = ('layer_a', 'layer_b', 'midi_note',
              'la_level', 'la_pan', 'la_pitch', 'la_fine', 'la_decay')


def _diff_pad_info(pad, instruments):
    """Resolve one pad's compared fields (assignments by name + a few params)."""
    def _u8(payload, off):
        return payload[off] if off < len(payload) else 0

    def _i8(payload, off):
        v = _u8(payload, off)
        return v if v < 128 else v - 256

    la = pad.get('layer_a', NO_INSTRUMENT)
    lb = pad.get('layer_b', NO_INSTRUMENT)
    pl = pad['payload']
    return {
        'layer_a':   instruments[la] if la != NO_INSTRUMENT and la < len(instruments) else None,
        'layer_b':   instruments[lb] if lb != NO_INSTRUMENT and lb < len(instruments) else None,
        'midi_note': _u8(pl, MIDI_NOTE_OFF),
        'la_level':  _u8(pl, LA_LEVEL_OFF),
        'la_pan':    _i8(pl, LA_PAN_OFF),
        'la_pitch':  _i8(pl, LA_PITCH_OFF),
        'la_fine':   _i8(pl, LA_FINE_OFF),
        'la_decay':  _u8(pl, LA_DECAY_OFF),
    }


def _diff_pad_lists(a_pads, a_insts, b_pads, b_insts) -> list:
    """Diff two (pads, instruments) pairs. 'current' = side A, 'other' = side B."""
    b_by_id = {p['id']: _diff_pad_info(p, b_insts) for p in b_pads}
    a_ids   = {p['id'] for p in a_pads}

    diff = []
    for cur in a_pads:
        pid      = cur['id']
        a_info   = _diff_pad_info(cur, a_insts)
        b_info   = b_by_id.get(pid)
        if b_info is None:
            diff.append({'id': pid, 'only_in': 'current'})
            continue
        changed = {}
        for key in _DIFF_KEYS:
            if a_info.get(key) != b_info.get(key):
                changed[key] = {'current': a_info.get(key), 'other': b_info.get(key)}
        if changed:
            diff.append({'id': pid, 'changed': changed})

    for p in b_pads:
        if p['id'] not in a_ids:
            diff.append({'id': p['id'], 'only_in': 'other'})

    return diff


def diff_kit(path: str) -> dict:
    """Compare another .skt file against the current state. Returns per-pad diffs."""
    raw = Path(path).read_bytes()
    _, other_pads, other_insts, _ = parse_skt(raw)
    diff = _diff_pad_lists(state['pads'], state['instruments'], other_pads, other_insts)
    return {
        'diff':          diff,
        'other_name':    Path(path).name,
        'total_pads':    len(state['pads']),
        'changed_count': len(diff),
    }


# ── Kit time machine (persistent version snapshots) ─────────────────────────────
# Snapshots are stored server-side as full .skt bytes (KB, not the samples) so they
# survive server restarts and browser reloads, round-trip byte-identical through
# parse_skt/build_skt, and never touch uncertain binary offsets. A JSON index holds
# the metadata; retention caps count-per-kit and age so the store can't grow forever.
SNAP_DIR          = LIBRARY_DIR / 'snapshots'
SNAP_INDEX_PATH   = SNAP_DIR / 'index.json'
SNAP_MAX_PER_KIT  = 50       # non-pinned snapshots kept per kit (newest win)
SNAP_MAX_AGE_DAYS = 30       # non-pinned snapshots older than this are pruned
_SNAP_LOCK        = threading.Lock()

_SNAP_KIND_LABEL = {'save': 'Saved', 'load': 'Loaded',
                    'auto': 'Auto-snapshot', 'manual': 'Snapshot'}


def _kit_key() -> str:
    """Stable key grouping snapshots by kit (filename if saved, else the display name)."""
    if state.get('kit_path'):
        return Path(state['kit_path']).name
    return state.get('kit_display') or 'untitled'


def _snap_index() -> list:
    if SNAP_INDEX_PATH.is_file():
        try:
            return json.loads(SNAP_INDEX_PATH.read_text('utf-8'))
        except Exception:
            return []
    return []


def _save_snap_index(idx: list):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_INDEX_PATH.write_text(json.dumps(idx, indent=1), 'utf-8')


def _cur_skt_bytes() -> bytes:
    return build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail'])


def _assigned_pad_count() -> int:
    return sum(1 for p in state['pads']
               if p.get('layer_a', NO_INSTRUMENT) != NO_INSTRUMENT
               or p.get('layer_b', NO_INSTRUMENT) != NO_INSTRUMENT)


def _prune_snapshots(idx: list) -> list:
    """Drop aged-out and over-cap non-pinned snapshots; delete their .skt files."""
    now     = time.time()
    cutoff  = now - SNAP_MAX_AGE_DAYS * 86400
    removed = []

    aged_kept = []
    for s in idx:
        if not s.get('pinned') and s.get('ts', 0) < cutoff:
            removed.append(s)
        else:
            aged_kept.append(s)

    by_kit = {}
    for s in aged_kept:
        by_kit.setdefault(s.get('kit', ''), []).append(s)

    final = []
    for snaps in by_kit.values():
        nonpinned = 0
        for s in sorted(snaps, key=lambda s: s.get('ts', 0), reverse=True):
            if s.get('pinned'):
                final.append(s)
            elif nonpinned < SNAP_MAX_PER_KIT:
                final.append(s)
                nonpinned += 1
            else:
                removed.append(s)

    for s in removed:
        try:
            (SNAP_DIR / f"{s['id']}.skt").unlink()
        except OSError:
            pass

    final.sort(key=lambda s: s.get('ts', 0))
    return final


def create_snapshot(label: str = '', kind: str = 'manual', pinned: bool = False) -> dict:
    """Capture the current kit as a persistent snapshot. Returns the entry, or
    {'deduped': True, ...} when the state is byte-identical to the kit's latest snapshot."""
    if not state.get('kit_raw'):
        return {'skipped': 'no kit loaded'}
    with _SNAP_LOCK:
        data = _cur_skt_bytes()
        sha  = hashlib.sha256(data).hexdigest()
        kit  = _kit_key()
        idx  = _snap_index()

        kit_snaps = [s for s in idx if s.get('kit') == kit]
        if kit_snaps:
            latest = max(kit_snaps, key=lambda s: s.get('ts', 0))
            if latest.get('sha') == sha:
                return {'deduped': True, 'id': latest['id'], 'kit': kit}

        snap_id = uuid.uuid4().hex[:12]
        ts      = time.time()
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / f'{snap_id}.skt').write_bytes(data)

        entry = {
            'id':       snap_id,
            'ts':       ts,
            'iso':      datetime.datetime.fromtimestamp(ts).isoformat(timespec='seconds'),
            'label':    label or _SNAP_KIND_LABEL.get(kind, kind),
            'kind':     kind,
            'kit':      kit,
            'size':     len(data),
            'sha':      sha,
            'pinned':   bool(pinned),
            'pads':     len(state['pads']),
            'assigned': _assigned_pad_count(),
        }
        idx.append(entry)
        idx = _prune_snapshots(idx)
        _save_snap_index(idx)
        return {'deduped': False, **entry}


def _auto_snapshot(label: str = '', kind: str = 'manual', pinned: bool = False):
    """Fire-and-forget snapshot for server-side triggers (save/load); never raises."""
    try:
        create_snapshot(label, kind, pinned)
    except Exception as e:
        print(f'[warn] snapshot failed: {e}', flush=True)


def list_snapshots(kit=None, all_kits: bool = False) -> list:
    """Snapshots newest-first, scoped to the given/current kit unless all_kits."""
    idx = _snap_index()
    if not all_kits:
        k   = kit if kit is not None else _kit_key()
        idx = [s for s in idx if s.get('kit') == k]
    return sorted(idx, key=lambda s: s.get('ts', 0), reverse=True)


def _snap_entry(snap_id: str) -> dict:
    return next((s for s in _snap_index() if s['id'] == snap_id), None)


def _snap_pads_insts(ident: str):
    """Resolve a diff source ('current' or a snapshot id) → (pads, insts, label)."""
    if ident == 'current':
        return state['pads'], state['instruments'], 'Current working state'
    entry = _snap_entry(ident)
    if not entry:
        raise ValueError(f'Snapshot not found: {ident}')
    raw = (SNAP_DIR / f'{ident}.skt').read_bytes()
    _, pads, insts, _ = parse_skt(raw)
    return pads, insts, f"{entry['label']} · {entry.get('iso', '')}"


def diff_snapshots(a: str, b: str) -> dict:
    """Diff any two snapshots (or the current state) by id. 'a' is side A, 'b' side B."""
    a_pads, a_insts, a_label = _snap_pads_insts(a)
    b_pads, b_insts, b_label = _snap_pads_insts(b)
    diff = _diff_pad_lists(a_pads, a_insts, b_pads, b_insts)
    return {
        'diff':          diff,
        'a_label':       a_label,
        'b_label':       b_label,
        'total_pads':    len(a_pads),
        'changed_count': len(diff),
    }


def restore_snapshot(snap_id: str) -> dict:
    """Load a snapshot back into the working state as a normal, undoable mutation."""
    entry = _snap_entry(snap_id)
    if not entry:
        raise ValueError(f'Snapshot not found: {snap_id}')
    raw = (SNAP_DIR / f'{snap_id}.skt').read_bytes()
    kit_raw, pads, instruments, tail = parse_skt(raw)
    _push_history(f"Restore snapshot · {entry['label']}")
    state['kit_raw']     = kit_raw
    state['pads']        = pads
    state['instruments'] = instruments
    state['tail']        = tail
    state['dirty']       = True
    state['param_rev']   = state.get('param_rev', 0) + 1
    state['message']     = f"Restored snapshot from {entry.get('iso', '')}"
    return entry


def delete_snapshot(snap_id: str):
    with _SNAP_LOCK:
        idx = _snap_index()
        if any(s['id'] == snap_id for s in idx):
            try:
                (SNAP_DIR / f'{snap_id}.skt').unlink()
            except OSError:
                pass
            _save_snap_index([s for s in idx if s['id'] != snap_id])


def set_snapshot_pin(snap_id: str, pinned: bool):
    with _SNAP_LOCK:
        idx = _snap_index()
        for s in idx:
            if s['id'] == snap_id:
                s['pinned'] = bool(pinned)
        _save_snap_index(idx)


def load_kit_bytes(data: bytes, filename: str = 'kit.skt'):
    """Parse a .skt from raw bytes (e.g. drag-dropped in browser). kit_path is empty until saved."""
    kit_raw, pads, instruments, tail = parse_skt(data)
    rebuilt  = build_skt(kit_raw, pads, instruments, tail)
    lossless = (rebuilt == data)
    if not lossless:
        print(f'[warn] {filename}: round-trip check FAILED ({len(data)}B → {len(rebuilt)}B)', flush=True)
    state['kit_path']     = ''
    state['kit_display']  = filename
    state['kit_raw']      = kit_raw
    state['pads']         = pads
    state['instruments']  = instruments
    state['tail']         = tail
    state['skt_lossless'] = lossless
    state['dirty']       = True
    state['history']     = []
    state['message']     = f'Loaded {filename}'
    _auto_snapshot(f'Loaded {filename}', 'load')


def clear_all_pads():
    """Remove all instrument assignments from every pad (undoable)."""
    _push_history('Clear all pads')
    for pad in state['pads']:
        payload = bytearray(pad['payload'])
        struct.pack_into('<H', payload, LAYER_A_IDX_OFF, NO_INSTRUMENT)
        struct.pack_into('<H', payload, LAYER_B_IDX_OFF, NO_INSTRUMENT)
        payload[REVERB_OFF] = 0
        pad['payload'] = bytes(payload)
        pad['layer_a'] = NO_INSTRUMENT
        pad['layer_b'] = NO_INSTRUMENT
    state['dirty']   = True
    state['message'] = 'All pads cleared'


def duplicate_kit(name: str) -> str:
    """Save a copy of the current kit to library/kits/<name>.skt. Returns the new path."""
    if not name:
        raise ValueError('Name cannot be empty')
    name = name.strip()
    if not name.lower().endswith('.skt'):
        name += '.skt'
    dest = LIBRARY_DIR / 'kits' / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail']))
    return str(dest)


def sync_kits_from_sd() -> dict:
    """Copy .skt files from all mounted SD cards to library/kits/. Returns {copied, skipped}."""
    user, preset = get_volumes()
    copied, skipped = [], []
    dest = LIBRARY_DIR / 'kits'
    dest.mkdir(parents=True, exist_ok=True)
    for root in [r for r in [user, preset] if r]:
        by_name: dict = {}
        for kit in sorted(root.rglob('*.skt')):
            if kit.name.startswith('.') or kit.name.startswith('._'):
                continue
            existing = by_name.get(kit.name)
            if existing is None or len(kit.parts) > len(existing.parts):
                by_name[kit.name] = kit
        for name, kit in sorted(by_name.items()):
            out = dest / name
            if out.exists():
                skipped.append(name)
            else:
                shutil.copy2(kit, out)
                copied.append(name)
    return {'copied': copied, 'skipped': skipped}


# ── Full library sync (background thread) ────────────────────────────────────

_sync_state = {
    'running':  False,
    'phase':    '',      # 'kits' | 'instruments' | 'samples' | 'done' | 'error'
    'detail':   '',      # current filename
    'done':     0,       # files processed so far
    'total':    0,       # total files in current phase
    'copied':   0,       # files actually written
    'skipped':  0,       # files already present
    'mb_copied': 0.0,
    'error':    '',
}
_sync_lock = threading.Lock()


def _sync_update(**kw):
    with _sync_lock:
        _sync_state.update(kw)


def _run_sync():
    """Background thread: copy kits → .sin instruments → WAV samples to library/."""
    try:
        user, preset = get_volumes()
        vols = [v for v in (user, preset) if v]
        if not vols:
            _sync_update(running=False, phase='error', error='No SD card volumes found.')
            return

        # ── Phase 1: kits ────────────────────────────────────────────────────
        _sync_update(phase='kits', detail='', done=0, total=0, copied=0, skipped=0, mb_copied=0.0)
        dest_kits = LIBRARY_DIR / 'kits'
        dest_kits.mkdir(parents=True, exist_ok=True)
        by_name: dict = {}
        for vol in vols:
            for kit in sorted(vol.rglob('*.skt')):
                if kit.name.startswith('.') or kit.name.startswith('._') or 'autosave' in kit.name:
                    continue
                existing = by_name.get(kit.name)
                if existing is None or len(kit.parts) > len(existing.parts):
                    by_name[kit.name] = kit
        kits_list = sorted(by_name.items())
        _sync_update(total=len(kits_list))
        cop = ski = 0
        for i, (name, src) in enumerate(kits_list):
            _sync_update(detail=name, done=i)
            out = dest_kits / name
            if out.exists():
                ski += 1
            else:
                shutil.copy2(src, out)
                cop += 1
        _sync_update(done=len(kits_list), copied=cop, skipped=ski)

        # ── Phase 2: .sin instrument metadata ───────────────────────────────
        _sync_update(phase='instruments', detail='', done=0, total=0, copied=0, skipped=0)
        dest_inst = LIBRARY_DIR / 'instruments'
        sins = []
        for vol in vols:
            inst_root = vol / 'Instruments'
            if not inst_root.is_dir():
                continue
            for sin in sorted(inst_root.rglob('*.sin')):
                sins.append((inst_root, sin))
        _sync_update(total=len(sins))
        cop = ski = 0
        for i, (inst_root, sin) in enumerate(sins):
            rel = sin.relative_to(inst_root)
            out = dest_inst / rel
            _sync_update(detail=str(rel), done=i)
            if out.exists():
                ski += 1
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sin, out)
                cop += 1
        _sync_update(done=len(sins), copied=cop, skipped=ski)

        # ── Phase 3: WAV samples ─────────────────────────────────────────────
        _sync_update(phase='samples', detail='', done=0, total=0, copied=0, skipped=0, mb_copied=0.0)
        dest_samples = LIBRARY_DIR / 'samples'
        wavs = []
        for vol in vols:
            samples_root = vol / 'Samples'
            if not samples_root.is_dir():
                continue
            for wav in sorted(samples_root.rglob('*')):
                if wav.suffix.lower() in ('.wav', '.wave') and not wav.name.startswith('.'):
                    wavs.append((samples_root, wav))
        _sync_update(total=len(wavs))
        cop = ski = 0
        mb = 0.0
        for i, (samples_root, wav) in enumerate(wavs):
            rel = wav.relative_to(samples_root)
            out = dest_samples / rel
            _sync_update(detail=str(rel), done=i)
            if out.exists():
                ski += 1
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(wav, out)
                sz = wav.stat().st_size
                mb += sz / 1e6
                cop += 1
                if cop % 50 == 0:
                    _sync_update(copied=cop, skipped=ski, mb_copied=round(mb, 1))
        _sync_update(done=len(wavs), copied=cop, skipped=ski, mb_copied=round(mb, 1))

        _sync_update(running=False, phase='done', detail='')
        # Refresh available instruments now that library is populated
        refresh_available()

    except Exception as e:
        _sync_update(running=False, phase='error', error=str(e))


def start_sync_library():
    with _sync_lock:
        if _sync_state['running']:
            return False
        _sync_state.update(running=True, phase='', detail='', done=0, total=0,
                           copied=0, skipped=0, mb_copied=0.0, error='')
    t = threading.Thread(target=_run_sync, daemon=True)
    t.start()
    return True


# ── Audio fingerprints + "More like this" similarity search ──────────────────
# Cheap, stdlib-only timbre fingerprints for every library instrument, so any
# instrument can surface its ~N closest-sounding neighbours across SIN groups.
# READ-ONLY: never writes/renames/modifies any WAV/.sin/.skt — vectors live in a
# sidecar (library/fingerprints.json), mirroring the tags.json pattern.
import math as _math

FP_PATH      = LIBRARY_DIR / 'fingerprints.json'                       # user sidecar (writable)
FACTORY_FP_PATH = Path(__file__).resolve().parent / 'factory_fingerprints.json'  # baked base layer (read-only, committed)
FP_SCHEMA    = 1              # bump to invalidate every cached vector on algo change
FP_FEATURES  = ('centroid', 'rolloff', 'zcr', 'brightness', 'decay')
_FP_READ_SEC   = 1.5          # only analyse the first ~1.5 s of each sample
_FP_FFT_SIZE   = 4096         # radix-2 window for the spectral frame (power of two)
_FP_BRIGHT_HZ  = 2000.0       # brightness = fraction of spectral energy above this


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

    # time-domain: zero-crossing rate (needs no FFT)
    zc, prev = 0, samples[0]
    for s in samples[1:]:
        if (prev >= 0.0) != (s >= 0.0):
            zc += 1
        prev = s
    zcr = zc * rate / n

    # RMS envelope in 10 ms blocks → decay time
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

    # spectral frame: Hann-windowed FFT starting a touch before the loudest sample
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
        re[i] = frame[i] * (0.5 - 0.5 * _math.cos(2.0 * _math.pi * i / denom))   # Hann
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


def _representative_wav_for_sin(sin_rel: str):
    """Choose the deliberate 'full hit' sample to fingerprint for an instrument:
    the mapping with the highest velocity ceiling (hardest-velocity layer), which
    dedupes round-robins to a single file. Falls back to the first listed WAV.
    Returns (abs_path | None, wav_rel | None)."""
    sin_abs = state['avail'].get(sin_rel)
    if not sin_abs:
        return None, None
    try:
        data = Path(sin_abs).read_bytes()
    except OSError:
        return None, None
    wav_rel = None
    try:
        best = None
        for m in parse_sin(data).get('mappings') or []:
            samp = m.get('sample', '')
            if not samp.lower().endswith(('.wav', '.wave')):
                continue
            key = (m.get('vmax', 0), m.get('vmin', 0))
            if best is None or key > best[0]:
                best = (key, samp)
        if best:
            wav_rel = best[1]
    except Exception:
        wav_rel = None
    if not wav_rel:
        wav_rel = parse_sin_first_wav(data)
    if not wav_rel:
        return None, None
    p = _find_wav_in_roots(wav_rel)
    return (p, wav_rel) if p else (None, wav_rel)


# In-memory fingerprint store (mirrors load_tags/save_tags). Entry shape:
#   {v: schema, wav_rel, mtime, size, feats: {...} | None}
# feats == None marks an instrument we tried but whose WAV was missing/broken.
_fp_cache = None
_fp_lock  = threading.Lock()


_fp_factory = None   # baked factory base layer (read-only; never saved)


def load_fingerprints() -> dict:
    global _fp_cache
    if _fp_cache is None:
        data = {}
        if FP_PATH.exists():
            try:
                data = json.loads(FP_PATH.read_text('utf-8'))
            except Exception:
                data = {}
        _fp_cache = data
    return _fp_cache


def load_factory_fingerprints() -> dict:
    """Read-only base layer of pre-computed vectors for the read-only factory content,
    which is byte-identical on every module — so it ships with the app (committed, not
    under git-ignored library/). Lets similarity work with ZERO sample sync and no
    first-run batch; entries are marked ``factory`` and validated on size only (their
    WAV mtimes differ between cards/copies even though the audio is identical)."""
    global _fp_factory
    if _fp_factory is None:
        data = {}
        if FACTORY_FP_PATH.exists():
            try:
                data = json.loads(FACTORY_FP_PATH.read_text('utf-8'))
            except Exception:
                data = {}
        _fp_factory = data
    return _fp_factory


def _fp_lookup(sin_rel: str):
    """A cached entry for one instrument: the user sidecar wins over the factory base."""
    cache = load_fingerprints()
    if sin_rel in cache:
        return cache[sin_rel]
    return load_factory_fingerprints().get(sin_rel)


def _fp_all_items() -> dict:
    """Union of the factory base + user sidecar (user overrides on key collision)."""
    merged = dict(load_factory_fingerprints())
    merged.update(load_fingerprints())
    return merged


def save_fingerprints():
    if _fp_cache is None:
        return
    FP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FP_PATH.with_suffix('.json.tmp')
    with _fp_lock:
        tmp.write_text(json.dumps(_fp_cache, ensure_ascii=False), 'utf-8')
    tmp.replace(FP_PATH)


def _fp_entry_valid(entry, wav_path) -> bool:
    """A cached entry is fresh if the schema matches and the representative WAV is
    unchanged (or still absent → keep the prior result). Factory entries are trusted on
    SIZE only: the audio is identical everywhere, but copied SD cards give the WAVs
    different mtimes, so an mtime check would needlessly discard the whole baked set."""
    if not entry or entry.get('v') != FP_SCHEMA:
        return False
    if entry.get('factory'):
        if wav_path is None:
            return True
        try:
            return entry.get('size') is None or wav_path.stat().st_size == entry['size']
        except OSError:
            return True
    if wav_path is None:
        return True
    try:
        st = wav_path.stat()
    except OSError:
        return True
    return entry.get('mtime') == st.st_mtime and entry.get('size') == st.st_size


def _compute_fp_entry(wav_path, wav_rel) -> dict:
    if wav_path is None:
        return {'v': FP_SCHEMA, 'wav_rel': wav_rel, 'feats': None}
    feats = extract_fingerprint(wav_path)
    try:
        st = wav_path.stat()
        mt, sz = st.st_mtime, st.st_size
    except OSError:
        mt, sz = None, None
    return {'v': FP_SCHEMA, 'wav_rel': wav_rel, 'mtime': mt, 'size': sz, 'feats': feats}


def ensure_fingerprint(sin_rel: str, force: bool = False):
    """Return the cached feats for one instrument, computing + caching on demand so
    a 'similar' click works before the full batch finishes. None if unfingerprintable."""
    cache = load_fingerprints()
    wav_path, wav_rel = _representative_wav_for_sin(sin_rel)
    ent = _fp_lookup(sin_rel)                    # user sidecar first, then factory base
    if not force and _fp_entry_valid(ent, wav_path):
        return ent.get('feats')
    entry = _compute_fp_entry(wav_path, wav_rel)
    with _fp_lock:
        cache[sin_rel] = entry                   # freshly computed entries go to the user sidecar
    return entry.get('feats')


# ── Fingerprint batch build (background thread, mirrors the SD-sync plumbing) ──
_fp_build_state = {
    'running':  False,
    'phase':    '',      # 'fingerprint' | 'done' | 'error'
    'detail':   '',      # current sin_rel
    'done':     0,
    'total':    0,
    'computed': 0,       # freshly analysed
    'cached':   0,       # reused from a valid sidecar entry
    'skipped':  0,       # WAV missing/broken → marked unfingerprinted
    'error':    '',
}
_fp_build_lock = threading.Lock()


def _fp_build_update(**kw):
    with _fp_build_lock:
        _fp_build_state.update(kw)


def _run_fingerprint_build():
    """Analyse every library instrument once; reuse valid sidecar entries. Reads real
    audio, so this is the slow part — hence the background thread + progress mirror."""
    try:
        refresh_available()
        rels  = sorted(state['avail'].keys())
        cache = load_fingerprints()
        _fp_build_update(phase='fingerprint', total=len(rels), done=0,
                         computed=0, cached=0, skipped=0)
        comp = cach = skip = 0
        for i, rel in enumerate(rels):
            _fp_build_update(detail=rel, done=i)
            wav_path, wav_rel = _representative_wav_for_sin(rel)
            ent = _fp_lookup(rel)                     # factory base counts as already-cached
            if _fp_entry_valid(ent, wav_path) and (wav_path is not None or ent is not None):
                cach += 1
            else:
                entry = _compute_fp_entry(wav_path, wav_rel)
                with _fp_lock:
                    cache[rel] = entry
                if entry.get('feats') is None:
                    skip += 1
                else:
                    comp += 1
            if (i + 1) % 100 == 0:
                _fp_build_update(computed=comp, cached=cach, skipped=skip)
                save_fingerprints()
        save_fingerprints()
        _fp_build_update(running=False, phase='done', detail='',
                         done=len(rels), computed=comp, cached=cach, skipped=skip)
    except Exception as e:
        _fp_build_update(running=False, phase='error', error=str(e))


def start_fingerprint_build():
    with _fp_build_lock:
        if _fp_build_state['running']:
            return False
        _fp_build_state.update(running=True, phase='', detail='', done=0, total=0,
                               computed=0, cached=0, skipped=0, error='')
    threading.Thread(target=_run_fingerprint_build, daemon=True).start()
    return True


def _knn_rank(query_key, corpus_items, n: int = 10):
    """Pure k-NN ranking. corpus_items = [(key, feats), ...] INCLUDING the query item.
    Features are z-score standardised across the whole corpus (so a Hz-scaled feature
    can't dominate a 0-1 one), then ranked by euclidean distance to the query.
    Returns [(key, dist, feats), ...] nearest-first, excluding the query itself."""
    feats_by = dict(corpus_items)
    q = feats_by.get(query_key)
    if q is None or len(corpus_items) < 2:
        return []
    means, stds = {}, {}
    for key in FP_FEATURES:
        vals = [f.get(key, 0.0) for _, f in corpus_items]
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / len(vals)
        means[key] = m
        stds[key]  = (var ** 0.5) or 1.0

    def vec(f):
        return [(f.get(k, 0.0) - means[k]) / stds[k] for k in FP_FEATURES]

    qv = vec(q)
    scored = [(sum((a - b) ** 2 for a, b in zip(qv, vec(f))) ** 0.5, key, f)
              for key, f in corpus_items if key != query_key]
    scored.sort(key=lambda x: x[0])
    return [(key, round(d, 3), f) for d, key, f in scored[:max(1, int(n))]]


def similar_instruments(sin_rel: str, n: int = 10) -> dict:
    """k-NN over z-scored fingerprint vectors → the N nearest-sounding instruments.
    Cross-group (no SIN-group hard filter); same-group items just rank near naturally."""
    q = ensure_fingerprint(sin_rel)
    allfp = _fp_all_items()                       # factory base + user sidecar
    corpus_have = sum(1 for e in allfp.values() if e.get('feats'))
    if q is None:
        return {'query': sin_rel, 'results': [], 'unfingerprinted': True,
                'corpus': corpus_have}
    avail = state.get('avail', {})
    corpus = [(rel, e['feats']) for rel, e in allfp.items()
              if e.get('feats') and rel in avail]
    if sin_rel not in {r for r, _ in corpus}:
        corpus.append((sin_rel, q))
    ranked = _knn_rank(sin_rel, corpus, n)
    results = [{
        'sin_rel':    rel,
        'name':       rel.split('/', 1)[-1].rsplit('.', 1)[0] if '/' in rel else rel,
        'group':      rel.split('/', 1)[0],
        'dist':       d,
        'centroid':   f.get('centroid'),
        'brightness': f.get('brightness'),
        'decay':      f.get('decay'),
    } for rel, d, f in ranked]
    return {'query': sin_rel, 'results': results, 'unfingerprinted': False,
            'corpus': len(corpus)}


def hex_inspect_pad(pad_id: str) -> str:
    """Return annotated hex dump for a pad in the current kit (runs hex_explorer.py)."""
    if not state['pads']:
        raise ValueError('No kit loaded')
    data = build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail'])
    with tempfile.NamedTemporaryFile(suffix='.skt', delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        r = subprocess.run(
            [sys.executable,
             str(Path(__file__).parent / 'tools' / 'hex_explorer.py'),
             tmp, pad_id.upper()],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or '') + (r.stderr or '')
    finally:
        Path(tmp).unlink(missing_ok=True)


def list_tools() -> list:
    """Return [{name, label}] for runnable scripts in tools/."""
    tools_dir = Path(__file__).parent / 'tools'
    skip = {'hex_explorer.py', 'sin_inspector.py',
            'build_factory_fingerprints.py'}         # not user-facing runners
    out = []
    for p in sorted(tools_dir.glob('*.py')):
        if p.name.startswith('_') or p.name in skip:
            continue
        # Extract first docstring line as label
        try:
            first_line = ''
            for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
                stripped = line.strip().strip('"\'')
                if stripped and not stripped.startswith('#!'):
                    first_line = stripped
                    break
        except OSError:
            first_line = ''
        out.append({'name': p.name, 'label': first_line or p.stem})
    return out


def run_tool(name: str, args: list | None = None) -> str:
    """Run a script from tools/ as a subprocess. Returns combined stdout+stderr."""
    tools_dir = Path(__file__).parent / 'tools'
    script = (tools_dir / name).resolve()
    if tools_dir.resolve() not in script.parents:
        raise ValueError('Path escape detected')
    if not script.exists():
        raise FileNotFoundError(f'Tool not found: {name}')
    cmd = [sys.executable, str(script)] + (args or [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       cwd=str(Path(__file__).parent))
    return (r.stdout or '') + (r.stderr or '')


# ── Kit creation ───────────────────────────────────────────────────────────────

# KIT block template: 44 bytes of mostly-zero global params (matches New User Kit)
_KIT_BLOCK_TEMPLATE = (
    b'KIT '
    + struct.pack('<I', 44)
    + b'\x00\x00\x63' + b'\x00' * 41
)


def _blank_payload(pad_id: str) -> bytearray:
    """Construct a default 72-byte pad payload with no instruments assigned."""
    p = bytearray(72)
    struct.pack_into('4s', p, 0, pad_id.ljust(4).encode('ascii')[:4])
    struct.pack_into('<H', p, LAYER_A_IDX_OFF, NO_INSTRUMENT)
    p[LA_LEVEL_OFF] = 95
    p[8]  = 98;   p[13] = 99;   p[18] = 90;   p[20] = 127   # layer A misc
    struct.pack_into('<H', p, LAYER_B_IDX_OFF, NO_INSTRUMENT)
    p[LB_LEVEL_OFF] = 95
    p[28] = 98;   p[33] = 99;   p[38] = 90;   p[40] = 127   # layer B misc
    p[MIDI_NOTE_OFF] = DEFAULT_MIDI_NOTE.get(pad_id, 38)
    for i in range(56, 61):
        p[i] = 0xFF                                            # choke: unset
    return p


def create_new_kit(name: str):
    """Create a blank 24-pad kit, save to library/kits/, and load into state."""
    safe = ''.join(c for c in name if c not in r'\/:*?"<>|').strip() or 'New Kit'
    pads = []
    for pid in PAD_ORDER:
        payload = _blank_payload(pid)
        pads.append({
            'id':      pid,
            'label':   PAD_LABEL.get(pid, pid),
            'layer_a': NO_INSTRUMENT,
            'layer_b': NO_INSTRUMENT,
            'payload': payload,
        })
    out = LIBRARY_DIR / 'kits' / f'{safe}.skt'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_skt(_KIT_BLOCK_TEMPLATE, pads, []))
    state.update({
        'kit_path':    str(out),
        'kit_display': out.name,
        'kit_raw':     _KIT_BLOCK_TEMPLATE,
        'pads':        pads,
        'instruments':  [],
        'tail':         b'',
        'skt_lossless': True,
        'dirty':        False,
        'history':      [],
        'message':      f'Created {safe}.skt',
    })
    _auto_snapshot(f'New kit {out.name}', 'load')


def save_kit(out_path_str: str):
    out = Path(out_path_str)
    _, preset_vol = get_volumes()
    if preset_vol:
        try:
            out.resolve().relative_to(preset_vol.resolve())
            raise ValueError("Cannot save over a preset file. Choose a path on the user card instead.")
        except ValueError as e:
            if "Cannot save" in str(e):
                raise
    data = build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail'])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    state['dirty']    = False
    state['kit_path'] = str(out)
    state['kit_display'] = out.name
    state['message']  = f"Saved to {out}"
    _auto_snapshot(f'Saved {out.name}', 'save')
    # Clean up matching autosave file if it exists
    autosave = out.parent / (out.stem + '.autosave.skt')
    if autosave.exists():
        try:
            autosave.unlink()
        except OSError:
            pass


def autosave_kit() -> 'str | None':
    """Write a .autosave.skt alongside the current kit while dirty. Returns path or None."""
    if not state['kit_path'] or not state['dirty']:
        return None
    src = Path(state['kit_path'])
    dst = src.parent / (src.stem + '.autosave.skt')
    dst.write_bytes(build_skt(state['kit_raw'], state['pads'], state['instruments'], state['tail']))
    return str(dst)


def find_autosaves() -> list:
    """Return [{name, autosave_path, kit_path}] for all found .autosave.skt files."""
    results = []
    user, _ = get_volumes()
    dirs = [LIBRARY_DIR / 'kits']
    if user:
        dirs += [user, user / 'Kits']
    seen = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob('*.autosave.skt')):
            if str(p) in seen:
                continue
            seen.add(str(p))
            stem     = p.stem.replace('.autosave', '')
            kit_path = p.parent / (stem + '.skt')
            results.append({
                'name':          stem,
                'autosave_path': str(p),
                'kit_path':      str(kit_path) if kit_path.exists() else '',
            })
    return results


def volume_status():
    user, preset = get_volumes()
    return {
        'user_mounted':   user is not None,
        'preset_mounted': preset is not None,
        'user_path':      str(user) if user else '',
        'preset_path':    str(preset) if preset else '',
    }


# ── Web server ─────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strike Pro Remapper</title>
<style>
:root {
  --bg: #0d0f15; --bg-deep: #0a0c11; --panel: #161a23; --raised: #1b202b;
  --field: #0b0e15; --border: #242c3d; --border-lt: #313a4d;
  --text: #e8ebf2; --text-2: #9aa3b2; --text-3: #5c6573;
  --accent: #f0b32e; --accent-dim: #d99e1f; --accent-soft: #f0b32e22;
  --info: #5b9dff; --ok: #3ecf8e; --danger: #e0626a;
  --r-sm: 4px; --r-md: 6px; --r-lg: 10px;
  --shadow-pop: 0 8px 28px #000000a0, 0 1px 0 #ffffff08 inset;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
*::-webkit-scrollbar { width: 10px; height: 10px; }
*::-webkit-scrollbar-thumb { background: #2a3140; border-radius: 5px; border: 2px solid transparent; background-clip: content-box; }
*::-webkit-scrollbar-thumb:hover { background: #38415a; border: 2px solid transparent; background-clip: content-box; }
*::-webkit-scrollbar-track { background: transparent; }
:focus-visible { outline: 2px solid #f0b32e66; outline-offset: 1px; }
body { font-family: 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif; background: #0d0f15; color: #e8ebf2; min-height: 100vh; -webkit-font-smoothing: antialiased; }
header { background: linear-gradient(180deg, #1a1f2a, #14181f); padding: 8px 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #242c3d; flex-wrap: nowrap; }
header h1 { font-size: .92rem; color: #f0b32e; text-transform: uppercase; letter-spacing: .16em; font-weight: 700; white-space: nowrap; }
#msg { color: #a0e0a0; font-size: .85rem; margin-left: auto; }
#dirty-badge { font-size: .75rem; color: #e0a030; background: #2a1800; border: 1px solid #604010; padding: 2px 8px; border-radius: 4px; }
#undo-btn { font-size: .75rem; padding: 4px 10px; }
#undo-btn:disabled { opacity: .35; cursor: not-allowed; }
#msg.err { color: #e08080; }
.main { display: grid; grid-template-columns: 280px 1fr 360px; grid-template-rows: 1fr; gap: 0; height: calc(100vh - 56px); overflow: hidden; }
#left-panel { grid-column: 1; grid-row: 1; display: flex; flex-direction: column; overflow: hidden; border-right: 1px solid #242c3d; }
#center-panel { grid-column: 2; grid-row: 1; }
#inst-panel { grid-column: 3; grid-row: 1; }
section { overflow-y: auto; padding: 12px; border-right: 1px solid #242c3d; }
/* ── Header kit controls ── */
.tb-group { position: relative; display: inline-flex; }
.tb-btn { padding: 5px 10px; font-size: .8rem; white-space: nowrap; }
.tb-popover { position: absolute; top: calc(100% + 6px); left: 0; background: #181d28; border: 1px solid #2e3749; border-radius: 10px; padding: 8px; z-index: 300; box-shadow: 0 8px 28px #000000a0, 0 1px 0 #ffffff08 inset; }
section h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .1em; color: #888; margin-bottom: 8px; }

/* ── Kit panel (popover in toolbar) ── */
.kit-list .kit-item { cursor: pointer; padding: 5px 8px; border-radius: 4px; font-size: .82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center; gap: 5px; }
.kit-list .kit-item:hover { background: #242c3d; }
.kit-list .kit-item.active { background: #1a3060; border-left: 2px solid #f0b32e; }
.kit-list .kit-src { font-size: .75rem; flex-shrink: 0; }

/* ── Center panel: drum map + detail ── */
#center-panel { display: flex; flex-direction: column; overflow: hidden; padding: 0; border-right: 1px solid #242c3d; }
.center-hdr { font-size: .8rem; text-transform: uppercase; letter-spacing: .1em; color: #888; padding: 8px 12px 4px; flex-shrink: 0; display: flex; align-items: center; gap: 8px; }
.center-hdr-kit { color: #f0b32e; text-transform: none; font-size: .85rem; font-weight: 400; letter-spacing: 0; }
#parse-warn { font-size: .7rem; color: #b8860b; background: #2a2000; border: 1px solid #6b5000; border-radius: 3px; padding: 1px 5px; cursor: default; }
#drum-svg-wrap { flex: 1 1 0; min-height: 0; overflow: hidden; padding: 4px 6px 6px; background: #0a0c11; }
#drum-svg { width: 100%; height: 100%; display: block; user-select: none; cursor: default; }
#pad-detail { overflow-y: auto; padding: 8px 12px; flex: 1 1 0; scrollbar-width: none; }
#pad-detail::-webkit-scrollbar { display: none; }
.map-pad { cursor: grab; }
.map-pad:active { cursor: grabbing; }
.pad-handle { cursor: pointer; }
.pad-handle[data-h="resize"] { cursor: nwse-resize; }
.pad-handle[data-h="rotate"] { cursor: grab; }
@keyframes pad-flash {
  0%   { filter: brightness(1.85) saturate(1.25) drop-shadow(0 0 11px #6effb0); }
  60%  { filter: brightness(1.2) drop-shadow(0 0 5px #00cc55); }
  100% { filter: none; }
}
.map-pad.midi-hit { animation: pad-flash 0.45s ease-out forwards; }
.det-empty { color: #555; font-size: .82rem; padding: 24px 8px; text-align: center; }
.det-card { background: #151923; border: 1px solid #222936; border-radius: 8px; padding: 10px 12px; }
.det-hdr { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.det-id { font-weight: 700; font-size: .9rem; color: #f0b32e; }
.det-label { font-size: .9rem; color: #ddd; }
.det-input { font-size: .68rem; color: #667; background: #0d1520; padding: 1px 6px; border-radius: 3px; margin-left: auto; white-space: nowrap; }
.det-layer { font-size: .75rem; color: #aaa; display: flex; align-items: center; gap: 6px; margin-top: 5px; }
.det-layer .name { color: #ddd; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.det-layer .pill { background: #242c3d; padding: 1px 6px; border-radius: 10px; font-size: .7rem; color: #88aaff; flex-shrink: 0; }
.layer-btn { padding: 2px 8px; border-radius: 4px; font-size: .7rem; cursor: pointer; border: 1px solid #555; background: #0d0f15; color: #ccc; }
.layer-btn:hover { background: #333; }
.layer-btn.clear { border-color: #600; color: #e08080; }
.layer-btn.active-layer { border-color: #44aaff; color: #44aaff; background: #0a1a30; }
.det-params { margin-top: 8px; padding-top: 7px; border-top: 1px solid #2a2a3e; display: flex; flex-direction: column; gap: 4px; }
.param-row { display: flex; align-items: center; gap: 6px; }
.param-lbl { font-size: .67rem; color: #778; width: 96px; flex-shrink: 0; line-height: 1.4; }
.param-slider-wrap { flex: 1; display: flex; align-items: center; gap: 5px; min-width: 0; }
.param-slider-wrap input[type=range] { flex: 1; height: 3px; accent-color: #f0b32e; cursor: pointer; min-width: 0; }
.param-val { font-size: .7rem; color: #aac; width: 28px; text-align: right; flex-shrink: 0; }
.midi-select { flex: 1; padding: 2px 4px; background: #0b0e15; border: 1px solid #313a4d; color: #e8ebf2; border-radius: 3px; font-size: .72rem; min-width: 0; }
.in-use-badge { font-size: .6rem; background: #0c2040; color: #4a6898; border: 1px solid #1a3060; padding: 0 4px; border-radius: 3px; white-space: nowrap; flex-shrink: 0; margin-right: 2px; cursor: default; }
.in-use-badge.mine { background: #082a16; color: #3a9060; border-color: #1a5030; }
.patch-hdr { display: flex; align-items: center; padding: 4px 8px 3px; cursor: pointer; border-bottom: 1px solid #0c1520; user-select: none; }
.patch-hdr:hover { background: #0c1220; }
.patch-hdr-lbl { font-size: .63rem; text-transform: uppercase; letter-spacing: .08em; color: #445; }
.det-customize { margin-top: 8px; padding-top: 6px; border-top: 1px solid #2a2a3e; }
.det-customize summary { font-size: .72rem; color: #556; cursor: pointer; user-select: none; }
.det-customize summary:hover { color: #778; }
.det-customize .cust-grid { display: grid; grid-template-columns: auto 1fr; gap: 5px 10px; align-items: center; margin-top: 6px; }
.det-customize .cust-grid span { font-size: .72rem; color: #888; }
.det-customize input[type=text], .det-customize select {
  padding: 3px 5px; background: #0b0e15; border: 1px solid #313a4d; color: #e8ebf2;
  border-radius: 3px; font-size: .78rem; }
.det-customize input[type=text] { width: 70px; }
.det-customize .cust-slider { display: flex; align-items: center; gap: 7px; }
.det-customize .cust-slider input[type=range] { flex: 1; min-width: 0; accent-color: #f0b32e; }
.det-customize .cust-slider > span { width: 36px; text-align: right; font-size: .72rem; color: #99a; font-variant-numeric: tabular-nums; }
.det-customize .cust-fin-lbl { font-size: .72rem; color: #888; margin: 9px 0 0; }
.det-customize .finish-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.det-customize .fin-sw { width: 20px; height: 20px; border-radius: 50%; padding: 0; cursor: pointer;
  border: 2px solid rgba(255,255,255,.18); box-shadow: inset 0 1px 2px rgba(255,255,255,.25), inset 0 -2px 3px rgba(0,0,0,.4); }
.det-customize .fin-sw:hover { border-color: rgba(240,179,46,.6); }
.det-customize .fin-sw.on { border-color: #f0b32e; box-shadow: 0 0 0 1px #f0b32e, inset 0 1px 2px rgba(255,255,255,.25); }
.det-customize .cust-hint { font-size: .66rem; color: #566; margin-top: 8px; line-height: 1.35; }
/* ── Zone rows (group detail) ── */
.det-zone { padding: 4px 4px 2px; margin: 2px 0; border-radius: 3px; border-left: 2px solid transparent; }
.det-zone.zone-sel { background: #0c1826; border-left-color: #f0b32e; }
.det-zone-id { font-size: .68rem; color: #556; font-weight: 700; margin-bottom: 2px; display: flex; align-items: baseline; gap: 5px; }
.det-zone-id .zlbl { font-weight: 400; color: #445; }

/* ── Patch panel ── */
#patch-panel-wrap { flex-shrink: 0; background: #07090f; border-bottom: 1px solid #20283a; }
#patch-panel { padding: 5px 6px 4px; }
.jack-row { display: flex; gap: 2px; margin-bottom: 3px; }
.jack-row:last-child { margin-bottom: 0; }
.jack-item { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; padding: 3px 1px 2px; border-radius: 3px; cursor: pointer; border: 1px solid transparent; gap: 1px; }
.jack-item:hover { background: #141c2c; border-color: #253045; }
.jack-item.jack-hot { background: #0c1828; border-color: #f0b32e; }
.jack-plug { width: 11px; height: 11px; border-radius: 50%; background: #0b0e16; border: 2px solid #232d3e; flex-shrink: 0; }
.jack-item.jack-hot .jack-plug { border-color: #f0b32e; box-shadow: 0 0 5px #1a408055; }
.jack-num { font-size: .52rem; color: #344; line-height: 1.2; }
.jack-lbl { font-size: .58rem; color: #4a5a6a; line-height: 1.1; text-align: center; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jack-item.jack-hot .jack-lbl { color: #7898d0; }

/* ── Instrument browser ── */
#inst-panel { border-right: none; }
#inst-search { width: 100%; padding: 6px 8px; background: #0b0e15; border: 1px solid #242c3d; color: #e8ebf2; border-radius: 4px; font-size: .85rem; margin-bottom: 0; }
.assign-target { font-size: .75rem; padding: 5px 8px; border-radius: 4px; margin-bottom: 6px; background: #0d2040; border: 1px solid #1a4080; color: #88aaff; display: flex; align-items: center; justify-content: space-between; }
.assign-target.empty { color: #555; background: none; border-color: #222; }
.assign-target .clr { cursor: pointer; color: #f0b32e; padding: 0 4px; font-size: .9rem; }
.cat-header { font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; color: #888; padding: 5px 4px 3px; border-top: 1px solid #222; margin-top: 4px; cursor: pointer; display: flex; align-items: center; gap: 5px; user-select: none; }
.cat-header:hover { color: #aaa; }
.cat-header:first-child { border-top: none; margin-top: 0; }
.cat-arrow { font-size: .6rem; }
.cat-count { margin-left: auto; opacity: .5; }
.inst-item { padding: 4px 8px; border-radius: 4px; font-size: .82rem; cursor: pointer; display: flex; align-items: center; }
.inst-item:hover { background: #242c3d; }
.inst-item .iname { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.inst-item .ab-btns { display: flex; gap: 3px; flex-shrink: 0; }
.inst-item .ab-btn { font-size: .65rem; padding: 1px 5px; border-radius: 3px; border: 1px solid #313a4d; background: #0b0e15; color: #88aaff; cursor: pointer; }
.inst-item .ab-btn:hover { background: #1a3060; }
.play-btn { font-size: .7rem; padding: 1px 5px; border-radius: 3px; border: 1px solid #1a3a20; background: #071410; color: #50a060; cursor: pointer; flex-shrink: 0; line-height: 1; }
.play-btn:hover { background: #0e2818; color: #70c880; }
.play-btn.playing { color: #e09040; border-color: #604010; background: #1a1004; }
.waveform-canvas { flex-shrink: 0; opacity: .55; border-radius: 2px; margin: 0 4px; cursor: default; }

/* ── Live loop panel ── */
#loop-panel { flex-shrink:0; background:#07090f; border-top:1px solid #20283a; }
.loop-hdr { display:flex; align-items:center; padding:4px 8px 3px; cursor:pointer; border-bottom:1px solid #0c1520; user-select:none; }
.loop-hdr:hover { background:#0c1220; }
.loop-hdr-lbl { font-size:.63rem; text-transform:uppercase; letter-spacing:.08em; color:#445; }
.loop-controls { display:flex; align-items:center; gap:8px; padding:5px 8px 4px; flex-wrap:wrap; font-size:.72rem; }
.loop-controls label { color:#667; flex-shrink:0; }
#loop-bpm { width:46px; padding:2px 4px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.78rem; text-align:center; }
#loop-pattern { padding:2px 4px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.72rem; }
#loop-play-btn { font-size:.72rem; padding:3px 10px; }
#loop-play-btn.playing { background:#1a3820; border-color:#2a6030; color:#70c880; }
.loop-grid { padding:4px 8px 6px; display:flex; flex-direction:column; gap:2px; }
.loop-row { display:flex; align-items:center; gap:4px; }
.loop-row-lbl { font-size:.58rem; color:#445; width:30px; flex-shrink:0; cursor:pointer; text-align:right; user-select:none; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.loop-row-lbl:hover { color:#778; }
.loop-row-lbl.muted { color:#2a2a3a; text-decoration:line-through; }
.loop-steps { display:flex; gap:2px; }
.loop-step { width:14px; height:14px; border-radius:2px; border:1px solid #1a2a3a; background:#0d1520; cursor:pointer; flex-shrink:0; padding:0; }
.loop-step:hover { border-color:#2a4a6a; }
.loop-step.on { background:#2a5090; border-color:#3a70c0; }
.loop-step.cur { border-color:#f0b32e !important; box-shadow:0 0 4px #f0b32e60; }
.loop-step.on.cur { background:#3a60a0; }
.loop-beat-gap { width:5px; flex-shrink:0; }
/* ── Autosave recovery banner ── */
#autosave-banner { background:#1c1505; border-bottom:1px solid #4a3a10; padding:5px 16px; font-size:.78rem; color:#d9bd6a; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
#autosave-banner a { color:#f0c95e; cursor:pointer; text-decoration:underline; margin-left:6px; }
#autosave-banner a:hover { color:#ffe08a; }
#autosave-banner #as-list { display:none; width:100%; padding:4px 0 2px; gap:4px 18px; flex-wrap:wrap; }
#autosave-banner.expanded #as-list { display:flex; }
#autosave-banner .as-item { white-space:nowrap; }
/* ── WAV import staging ── */
#import-staged-list { margin: 5px 0; max-height: 120px; overflow-y: auto; }
.staged-row { display:flex; align-items:center; gap:4px; padding:3px 2px; font-size:.75rem; border-bottom:1px solid #111; }
.staged-row:last-child { border-bottom:none; }
.staged-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#ccc; }
.staged-vel { width:36px; padding:2px 3px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.72rem; text-align:center; }
.staged-sep { font-size:.7rem; color:#666; flex-shrink:0; }
.staged-rr { background:#0c2040; color:#4a6898; font-size:.68rem; padding:1px 6px; border-radius:3px; flex-shrink:0; }
.import-grid { display:grid; grid-template-columns:auto 1fr; gap:4px 8px; align-items:center; margin-top:6px; font-size:.72rem; color:#778; }
.import-grid input, .import-grid select { padding:3px 5px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.78rem; }

/* ── Import WAV form ── */
#import-wav-form { display: none; background: #0d1520; border: 1px solid #1a3050; border-radius: 5px; padding: 8px 10px; margin-bottom: 6px; }
#import-wav-form label { font-size: .72rem; color: #778; display: block; margin-bottom: 3px; }
#import-wav-form input[type=text] { width: 100%; padding: 4px 6px; background: #0a1020; border: 1px solid #1a3060; color: #e8ebf2; border-radius: 3px; font-size: .78rem; margin-bottom: 5px; }
#import-file-input { display: none; }
#import-drop-zone { border: 1px dashed #2a4060; border-radius: 4px; padding: 10px; text-align: center; font-size: .75rem; color: #556; cursor: pointer; margin-bottom: 6px; transition: border-color .15s, color .15s; }
#import-drop-zone:hover, #import-drop-zone.drag-over { border-color: #4a80bb; color: #88aadd; }
#import-progress { font-size: .72rem; color: #88c090; margin-top: 4px; min-height: 1.2em; }

/* ── New kit form ── */
#new-kit-form { display: none; margin-bottom: 4px; }

button { padding: 7px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: .82rem;
         font-family: inherit; transition: background .12s, border-color .12s, color .12s, box-shadow .12s; }
.btn-primary { background: #f0b32e; color: #15120a; font-weight: 600; }
.btn-primary:hover { background: #ffc545; }
.btn-primary:disabled { background: #3a3f4b; color: #777e8c; cursor: not-allowed; }
.btn-secondary { background: #1b202b; border: 1px solid #2e3749; color: #c3cad6; }
.btn-secondary:hover { background: #232a38; border-color: #3a4458; }

/* ── Favorites / star button ── */
.star-btn { font-size:.78rem; padding:1px 4px; border-radius:3px; border:1px solid transparent; background:none; color:#444; cursor:pointer; flex-shrink:0; line-height:1.2; }
.star-btn:hover { color:#e8b820; }
.star-btn.starred { color:#e8b820; }
/* ── Section dividers in instrument browser (Starred / Recent) ── */
.sect-hdr { font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; color:#888; padding:4px 8px 2px; border-top:1px solid #222; margin-top:2px; display:flex; align-items:center; gap:5px; }
.sect-hdr:first-child { border-top:none; margin-top:0; }
/* ── Copy pad row ── */
.copy-pad-row { display:flex; gap:5px; align-items:center; margin-top:8px; padding-top:6px; border-top:1px solid #2a2a3e; }
.copy-pad-row label { font-size:.68rem; color:#556; white-space:nowrap; }
.copy-pad-row select { flex:1; padding:2px 4px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.72rem; }
/* ── Undo history dropdown ── */
.undo-hist-panel { position:absolute; top:34px; left:0; background:#181d28; border:1px solid #2e3749; border-radius:10px; min-width:220px; max-height:240px; overflow-y:auto; z-index:200; box-shadow:0 8px 28px #000000a0; }
.undo-hist-item { padding:5px 12px; font-size:.75rem; cursor:pointer; border-bottom:1px solid #0c1520; color:#aaa; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.undo-hist-item:hover { background:#242c3d; color:#ddd; }
.undo-hist-item:last-child { border-bottom:none; }
/* ── Drag-and-drop overlay (for .skt files) ── */
#drop-overlay { display:none; position:fixed; inset:0; background:#0d0f1599; border:3px dashed #f0b32e; border-radius:8px; z-index:999; pointer-events:none; align-items:center; justify-content:center; font-size:1.6rem; color:#88bbee; letter-spacing:.05em; }
#drop-overlay.active { display:flex; }
/* ── Kit name inline rename ── */
.center-hdr-kit[contenteditable=true] { cursor:text; border-bottom:1px dashed #f0b32e; outline:none; padding:0 2px; min-width:40px; display:inline-block; }
.center-hdr-kit[contenteditable=true]:empty::before { content:'(unnamed)'; color:#445; }
/* ── Instrument browser toolbar ── */
.browser-toolbar { display:flex; align-items:center; gap:6px; padding:3px 0 5px; flex-wrap:wrap; }
.browser-toolbar select { padding:2px 4px; background:#0b0e15; border:1px solid #313a4d; color:#e8ebf2; border-radius:3px; font-size:.72rem; }
.browser-toolbar label { font-size:.7rem; color:#778; display:flex; align-items:center; gap:3px; cursor:pointer; white-space:nowrap; }
.browser-toolbar label input[type=checkbox] { accent-color:#f0b32e; cursor:pointer; }
/* ── Duplicate kit popover ── */
.dup-form { position:absolute; top:calc(100% + 6px); left:0; background:#181d28; border:1px solid #2e3749; border-radius:10px; padding:8px; z-index:300; box-shadow:0 8px 28px #000000a0; display:flex; flex-direction:column; gap:6px; min-width:240px; }
.dup-form input { width:100%; padding:5px 7px; background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:4px; font-size:.8rem; }

/* ── Light theme ── */
body[data-theme=light] { background:#f2f4f8; color:#0d0f15; }
body[data-theme=light] header { background:#fff; border-bottom-color:#c8d4e0; }
body[data-theme=light] .main > section { border-right-color:#c8d4e0; }
body[data-theme=light] #center-panel { border-right-color:#c8d4e0; }
body[data-theme=light] #drum-svg-wrap { background:#dce6f0; }
body[data-theme=light] .det-card { background:#fff; }
body[data-theme=light] .det-zone { background:#f8fafc; }
body[data-theme=light] .det-layer .name { color:#223; }
body[data-theme=light] .det-layer .pill { background:#c8d8ee; color:#313a4d; }
body[data-theme=light] .param-lbl { color:#556; }
body[data-theme=light] .param-val { color:#446; }
body[data-theme=light] section h2, body[data-theme=light] .center-hdr { color:#556; }
body[data-theme=light] input[type=text], body[data-theme=light] input[type=number],
body[data-theme=light] select { background:#e8edf5 !important; border-color:#b0c0d4 !important; color:#0d0f15 !important; }
body[data-theme=light] .btn-secondary { background:#e0e8f2; border-color:#b0c0d4; color:#334; }
body[data-theme=light] .btn-secondary:hover { background:#d0dcea; }
body[data-theme=light] .kit-item:hover { background:#d8e4f0; }
body[data-theme=light] .kit-item.active { background:#c8d8ee; border-left-color:#f0b32e; }
body[data-theme=light] .inst-item:hover { background:#d8e4f0; }
body[data-theme=light] .cat-header { border-top-color:#c8d4e0; color:#667; }
body[data-theme=light] #patch-panel-wrap, body[data-theme=light] #loop-panel { background:#dce6f0; border-color:#c0d0e0; }
body[data-theme=light] #left-panel { border-right-color:#c8d4e0; }
body[data-theme=light] .loop-hdr, body[data-theme=light] .patch-hdr { border-bottom-color:#c0d0e0; }
body[data-theme=light] .loop-hdr-lbl, body[data-theme=light] .patch-hdr-lbl { color:#778; }
body[data-theme=light] .loop-step { background:#c8d8ea; border-color:#a8b8cc; }
body[data-theme=light] .loop-step.on { background:#f0b32e; border-color:#2a5090; }
body[data-theme=light] .loop-row-lbl { color:#667; }
body[data-theme=light] .jack-item:hover { background:#d0dcea; }
body[data-theme=light] .jack-lbl { color:#7a8a9a; }
body[data-theme=light] .jack-num { color:#8a9aa8; }
body[data-theme=light] .assign-target { background:#d8eaf8; border-color:#a8c0d8; color:#334488; }
body[data-theme=light] .assign-target.empty { background:none; color:#778; }
body[data-theme=light] .in-use-badge { background:#d0e0f0; color:#3a5878; border-color:#a0b8cc; }
body[data-theme=light] .in-use-badge.mine { background:#c8e4d0; color:#2a7040; border-color:#90c0a0; }
body[data-theme=light] #import-wav-form { background:#edf3fa; border-color:#b0c4d8; }
body[data-theme=light] #import-drop-zone { border-color:#90b0cc; color:#4a6a8a; }
body[data-theme=light] #autosave-banner { background:#fff8e8; border-color:#d0a020; color:#7a6010; }
body[data-theme=light] #autosave-banner a { color:#906010; }
body[data-theme=light] .det-zone-id { color:#778; }
body[data-theme=light] .det-zone-id .zlbl { color:#889; }
body[data-theme=light] .det-customize summary { color:#889; }
body[data-theme=light] .det-customize summary:hover { color:#667; }
body[data-theme=light] .cust-grid span { color:#667; }
body[data-theme=light] .undo-hist-panel { background:#fff; border-color:#c0d0e4; box-shadow:0 4px 12px #0002; }
body[data-theme=light] .undo-hist-item { color:#334; border-bottom-color:#e0e8f0; }
body[data-theme=light] .undo-hist-item:hover { background:#e0eaf6; color:#112; }
body[data-theme=light] .sect-hdr { border-top-color:#d0dce8; color:#667; }
body[data-theme=light] .copy-pad-row { border-top-color:#d0dce8; }
body[data-theme=light] .copy-pad-row label { color:#667; }
body[data-theme=light] .copy-pad-row select { background:#e8edf5 !important; border-color:#b0c0d4 !important; color:#0d0f15 !important; }
body[data-theme=light] .star-btn { color:#bbb; }
body[data-theme=light] .star-btn.starred { color:#c09010; }
body[data-theme=light] #drop-overlay { background:#f2f4f888; border-color:#f0b32e; color:#2a5a9a; }
body[data-theme=light] .layer-btn { border-color:#b0bec8; background:#e8edf5; color:#556; }
body[data-theme=light] .play-btn { border-color:#90c0a0; background:#e8f4ec; color:#3a8050; }
body[data-theme=light] .browser-toolbar select { background:#e8edf5 !important; border-color:#b0c0d4 !important; color:#0d0f15 !important; }
body[data-theme=light] .browser-toolbar label { color:#445; }
body[data-theme=light] .dup-form input { background:#e8edf5 !important; border-color:#b0c0d4 !important; color:#0d0f15 !important; }
body[data-theme=light] .center-hdr-kit[contenteditable=true] { border-bottom-color:#f0b32e; }
body[data-theme=light] .tb-popover { background:#fff; border-color:#b0c0d4; }
body[data-theme=light] .dup-form { background:#fff; border-color:#b0c0d4; }
/* ── Tools panel ── */
.tools-section { margin-top:4px; }
.tools-section summary { font-size:.72rem; color:#556; cursor:pointer; user-select:none; padding:4px 0; }
.tools-section summary:hover { color:#88aacc; }
.tool-item { display:flex; align-items:center; gap:5px; padding:3px 0; }
.tool-item span { font-size:.72rem; color:#aaa; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tool-output { background:#060a10; border:1px solid #1a3050; border-radius:4px; padding:8px; font-size:.7rem; font-family:monospace; color:#88c4a0; white-space:pre-wrap; max-height:200px; overflow-y:auto; margin-top:4px; display:none; }
.tool-output.visible { display:block; }
.sync-progress { margin-top:8px; font-size:.72rem; }
.sync-bar-wrap { background:#0a1520; border-radius:3px; height:6px; margin:4px 0; overflow:hidden; }
.sync-bar { background:#3a80cc; height:100%; border-radius:3px; transition:width .3s; }
.sync-detail { color:#556; font-size:.65rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* ── Hex inspector ── */
.hex-output { background:#060a10; border:1px solid #1a3050; border-radius:4px; padding:8px 10px; font-size:.62rem; font-family:monospace; color:#9ac; white-space:pre; overflow-x:auto; max-height:260px; overflow-y:auto; margin-top:6px; }
body[data-theme=light] .tool-output { background:#f0f4fa; border-color:#b0c0d4; color:#2a6040; }
body[data-theme=light] .hex-output   { background:#f0f4fa; border-color:#b0c0d4; color:#336; }
body[data-theme=light] .tools-section summary { color:#667; }
body[data-theme=light] .tool-item span { color:#667; }
/* ── Batch apply panel ── */
#batch-panel { background:#0b0e15; border-top:1px solid #20283a; padding:5px 10px; display:none; flex-shrink:0; }
#batch-panel.active { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.batch-info { font-size:.72rem; color:#88aacc; white-space:nowrap; }
.batch-param-row { display:flex; align-items:center; gap:5px; flex:1; min-width:200px; }
.batch-param-row label { font-size:.68rem; color:#556; white-space:nowrap; }
/* ── Kit diff modal ── */
#diff-modal { display:none; position:fixed; inset:0; z-index:200; background:#000a; align-items:center; justify-content:center; }
#diff-modal.open { display:flex; }
.diff-box { background:#171c26; border:1px solid #2e3749; border-radius:12px; padding:16px; width:min(760px,92vw); max-height:80vh; display:flex; flex-direction:column; gap:10px; box-shadow:0 12px 40px #000000b0; }
.diff-box h3 { margin:0; font-size:.9rem; color:#aac; }
.diff-table { overflow-y:auto; flex:1; font-size:.72rem; }
.diff-table table { width:100%; border-collapse:collapse; }
.diff-table th { text-align:left; color:#556; font-weight:600; padding:3px 6px; border-bottom:1px solid #2a2a3e; position:sticky; top:0; background:#161a23; }
.diff-table td { padding:3px 6px; border-bottom:1px solid #0d0f15; vertical-align:top; }
.diff-row-changed td { background:#1a2a3e; }
.diff-val-cur  { color:#88ccff; }
.diff-val-oth  { color:#cc8840; }
.diff-no-diff  { color:#445; font-style:italic; font-size:.68rem; }
.diff-kit-sel  { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.diff-kit-sel select { flex:1; padding:4px 6px; background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:4px; font-size:.8rem; }
/* ── Kit time machine ── */
#tm-modal { display:none; position:fixed; inset:0; z-index:200; background:#000a; align-items:center; justify-content:center; }
#tm-modal.open { display:flex; }
.tm-box { background:#171c26; border:1px solid #2e3749; border-radius:12px; padding:16px; width:min(820px,94vw); max-height:86vh; display:flex; flex-direction:column; gap:10px; box-shadow:0 12px 40px #000000b0; }
.tm-box h3 { margin:0; font-size:.9rem; color:#aac; display:flex; align-items:center; gap:8px; }
.tm-toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.tm-scrub { display:flex; align-items:center; gap:8px; }
.tm-scrub input[type=range] { flex:1; }
.tm-scrub-lbl { font-size:.68rem; color:#667; min-width:120px; text-align:right; }
.tm-cols { display:grid; grid-template-columns:minmax(220px,1fr) 1.3fr; gap:12px; min-height:0; flex:1; }
.tm-list { overflow-y:auto; display:flex; flex-direction:column; gap:3px; padding-right:2px; }
.tm-snap { padding:5px 7px; border-radius:5px; border:1px solid #242c3d; background:#0d1119; cursor:pointer; display:flex; flex-direction:column; gap:2px; }
.tm-snap:hover { border-color:#3a4358; }
.tm-snap.sel { border-color:#f0b32e; background:#161426; }
.tm-snap-top { display:flex; align-items:center; gap:6px; }
.tm-snap-lbl { font-size:.76rem; color:#dce2ee; font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tm-snap-time { font-size:.63rem; color:#667; }
.tm-snap-meta { font-size:.62rem; color:#556; display:flex; gap:8px; }
.tm-kind { font-size:.56rem; text-transform:uppercase; letter-spacing:.06em; padding:0 4px; border-radius:3px; border:1px solid #2a3346; color:#7a889c; }
.tm-kind.save { color:#5aa878; border-color:#1e4a30; background:#08160e; }
.tm-kind.load { color:#6a9ad0; border-color:#1a3a60; background:#08131f; }
.tm-kind.auto { color:#8878b0; border-color:#332a4a; background:#100c18; }
.tm-kind.manual { color:#c8a24a; border-color:#4a3a12; background:#1a1404; }
.tm-pin { cursor:pointer; font-size:.72rem; opacity:.35; border:none; background:none; color:#f0b32e; padding:0 2px; }
.tm-pin.on { opacity:1; }
.tm-snap-actions { display:flex; gap:4px; margin-top:3px; }
.tm-snap-actions button { font-size:.62rem; padding:2px 6px; border-radius:3px; border:1px solid #313a4d; background:#0b0e15; color:#aac; cursor:pointer; }
.tm-snap-actions button:hover { background:#1a2334; }
.tm-snap-actions button.tm-del:hover { background:#2a1414; border-color:#5a2020; color:#e08080; }
.tm-detail { display:flex; flex-direction:column; gap:8px; min-height:0; }
.tm-cmp { display:flex; gap:5px; align-items:center; flex-wrap:wrap; font-size:.7rem; color:#667; }
.tm-cmp select { flex:1; min-width:90px; padding:3px 5px; background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:4px; font-size:.72rem; }
.tm-diff { overflow-y:auto; flex:1; font-size:.72rem; }
.tm-diff table { width:100%; border-collapse:collapse; }
.tm-diff th { text-align:left; color:#556; font-weight:600; padding:3px 6px; border-bottom:1px solid #2a2a3e; position:sticky; top:0; background:#161a23; }
.tm-diff td { padding:3px 6px; border-bottom:1px solid #0d0f15; vertical-align:top; }
.tm-diff .chg td { background:#1a2a3e; }
.tm-empty { color:#445; font-style:italic; font-size:.68rem; padding:8px 2px; }
body[data-theme=light] .tm-box { background:#fff; border-color:#b0c0d4; }
#confirm-modal { display:none; position:fixed; inset:0; z-index:400; background:#000a; align-items:center; justify-content:center; }
#confirm-modal.open { display:flex; }
.confirm-box { background:#171c26; border:1px solid #2e3749; border-radius:12px; padding:18px; width:min(440px,92vw); display:flex; flex-direction:column; gap:14px; box-shadow:0 12px 40px #000000b0; }
.confirm-box p { margin:0; font-size:.82rem; color:#bcd; white-space:pre-wrap; line-height:1.45; }
.confirm-actions { display:flex; gap:8px; justify-content:flex-end; }
body[data-theme=light] .confirm-box { background:#fff; border-color:#b0c0d4; }
body[data-theme=light] .confirm-box p { color:#334; }
body[data-theme=light] .tm-snap { background:#f2f5fa; border-color:#d0dce8; }
body[data-theme=light] .tm-snap-lbl { color:#1a2230; }
body[data-theme=light] .tm-diff th { background:#fff; color:#667; }
body[data-theme=light] .tm-diff .chg td { background:#eef4ff; }
body[data-theme=light] #batch-panel { background:#e8edf5; border-top-color:#c0d0e4; }
body[data-theme=light] .batch-info { color:#3a6090; }
body[data-theme=light] .diff-box { background:#fff; border-color:#b0c0d4; }
#sin-modal, #relink-modal, #kitfx-modal, #trig-modal, #similar-modal { display:none; position:fixed; inset:0; z-index:200; background:#000a; align-items:center; justify-content:center; }
#sin-modal.open, #relink-modal.open, #kitfx-modal.open, #trig-modal.open, #similar-modal.open { display:flex; }
.sim-row { display:flex; align-items:center; gap:8px; padding:5px 6px; border-bottom:1px solid #222b3a; font-size:.76rem; }
.sim-row:hover { background:#101826; }
.sim-row .sim-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sim-row .sim-grp { color:#7288aa; font-size:.66rem; background:#101a28; border-radius:3px; padding:1px 5px; }
.sim-row .sim-dist { color:#89b; font-size:.66rem; font-variant-numeric:tabular-nums; min-width:44px; text-align:right; }
body[data-theme=light] .sim-row:hover { background:#eef2f8; }
.trig-hex { font-family:ui-monospace,Consolas,monospace; font-size:.68rem; line-height:1.5; color:#9ab; white-space:pre; overflow-x:auto; background:#0b0e15; border:1px solid #242c3d; border-radius:4px; padding:8px; }
.trig-hex .known { color:#e8b34b; font-weight:700; cursor:help; }
#relink-modal select { background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:3px; font-size:.72rem; padding:2px 4px; }
body[data-theme=light] #relink-modal select { background:#fff; color:#222; border-color:#b0c0d4; }
.sin-box { background:#171c26; border:1px solid #2e3749; border-radius:12px; padding:16px; width:min(920px,94vw); max-height:86vh; overflow-y:auto; display:flex; flex-direction:column; gap:6px; box-shadow:0 12px 40px #000000b0; }
.sin-sec-title { font-size:.7rem; color:#667; margin-top:8px; display:flex; align-items:center; gap:8px; }
.sin-curve-tab { font-size:.62rem; padding:1px 7px; border-radius:3px; border:1px solid #313a4d; background:none; color:#88a; cursor:pointer; }
.sin-curve-tab.active { background:#242c3d; color:#dde; }
#sin-lane { display:block; border:1px solid #223; border-radius:4px; background:#0b0e15; touch-action:none; }
#sin-curve { display:block; border:1px solid #223; border-radius:4px; background:#0b0e15; touch-action:none; cursor:ns-resize; }
body[data-theme=light] #sin-lane, body[data-theme=light] #sin-curve { background:#f4f7fb; border-color:#c4d0e0; }
.sin-box h3 { margin:0; font-size:.9rem; color:#aac; }
.sin-grid { display:grid; grid-template-columns:1fr 1fr; gap:2px 18px; }
.sin-row { display:flex; align-items:center; gap:8px; min-height:24px; }
.sin-row label { font-size:.7rem; color:#88a; width:86px; flex:none; }
.sin-row input[type=range] { flex:1; margin:0; }
.sin-row select { background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:3px; font-size:.72rem; padding:2px 4px; }
.sin-val { font-size:.7rem; width:28px; text-align:right; color:#cce; flex:none; }
.sin-maps table { width:100%; border-collapse:collapse; font-size:.7rem; }
.sin-maps th, .sin-maps td { padding:2px 4px; border-bottom:1px solid #223; text-align:left; }
.sin-maps input[type=number] { width:52px; background:#0b0e15; border:1px solid #242c3d; color:#e8ebf2; border-radius:3px; font-size:.7rem; padding:1px 3px; margin:0; }
.sin-ro-badge { font-size:.65rem; color:#c90; border:1px solid #c90; border-radius:3px; padding:1px 5px; }
body[data-theme=light] .sin-box { background:#fff; border-color:#b0c0d4; }
body[data-theme=light] .sin-maps input[type=number], body[data-theme=light] .sin-row select { background:#fff; color:#222; border-color:#b0c0d4; }
body[data-theme=light] .diff-table th { background:#fff; border-bottom-color:#d0dce8; color:#667; }
body[data-theme=light] .diff-table td { border-bottom-color:#e8edf5; }
body[data-theme=light] .diff-row-changed td { background:#eef4ff; }
body[data-theme=light] .diff-val-cur { color:#1a5090; }
body[data-theme=light] .diff-val-oth { color:#903010; }
body[data-theme=light] .diff-kit-sel select { background:#e8edf5 !important; border-color:#b0c0d4 !important; color:#0d0f15 !important; }
/* ── Mobile / narrow layout ── */
@media (max-width: 768px) {
  header { flex-wrap: wrap; padding: 4px 8px; gap: 4px; min-height: 0; height: auto; }
  header h1 { font-size: .9rem; }
  .tb-btn { padding: 4px 7px; font-size: .72rem; }
  #vol-status { display: none; }
  .main { grid-template-columns: 1fr !important; grid-template-rows: auto auto auto; height: auto; overflow: visible; }
  #left-panel   { grid-column: 1 !important; grid-row: 2; max-height: 60vh; border-right: none; border-bottom: 1px solid #242c3d; }
  #center-panel { grid-column: 1 !important; grid-row: 1; min-height: 380px; border-right: none; border-bottom: 1px solid #242c3d; }
  #inst-panel   { grid-column: 1 !important; grid-row: 3; max-height: 50vh; }
  #drum-svg-wrap { min-height: 220px; }
  body { overflow-y: auto; }
}
@media (max-width: 480px) {
  .center-hdr { flex-wrap: wrap; }
  #batch-toggle-btn, #reset-layout-btn { font-size: .62rem; padding: 2px 5px; }
  .det-params .param-row { flex-wrap: wrap; }
}
/* ── Tag chips + tag badges ── */
#tag-chips-row { display:flex; flex-wrap:wrap; gap:4px; padding:4px 8px 2px; min-height:0; }
#tag-chips-row:empty { display:none; }
.tag-chip { font-size:.65rem; padding:2px 7px; border-radius:10px; border:1px solid #313a4d; background:#0b0e15; color:#88aacc; cursor:pointer; white-space:nowrap; }
.tag-chip:hover { border-color:#4a80bb; color:#aaccff; }
.tag-chip.active { background:#1a3a60; border-color:#4a90dd; color:#cce0ff; }
.tag-chip.all-chip { border-color:#556; color:#778; }
.tag-chip.all-chip:hover { border-color:#888; color:#aaa; }
.inst-tag { font-size:.6rem; padding:1px 5px; border-radius:8px; background:#0d2a1a; border:1px solid #1a5030; color:#5a9a60; cursor:pointer; white-space:nowrap; }
.inst-tag:hover { background:#1a3a28; }
.inst-tag-edit { font-size:.65rem; width:120px; padding:1px 4px; background:#060e18; border:1px solid #3a6090; color:#cce; border-radius:3px; }
body[data-theme=light] .tag-chip { background:#e8f0fa; border-color:#b0c8e8; color:#3a6090; }
body[data-theme=light] .tag-chip.active { background:#c8ddf5; }
body[data-theme=light] .tag-chip.all-chip { border-color:#c0c8d0; color:#778; }
body[data-theme=light] .inst-tag { background:#e8f5e8; border-color:#80c080; color:#2a6030; }
body[data-theme=light] .inst-tag-edit { background:#f0f4fa; border-color:#90b0d0; color:#1a2a3e; }
</style>
</head>
<body>
<header>
  <h1>Strike Pro Remapper</h1>

  <!-- Kit picker -->
  <div class="tb-group">
    <button class="btn-secondary tb-btn" onclick="menuToggle('kit-menu')">&#128193; Kits &#9660;</button>
    <div id="kit-menu" class="tb-popover" style="display:none;width:290px;max-height:70vh;overflow-y:auto;">
      <div id="new-kit-form" style="display:none;margin-bottom:6px;">
        <input type="text" id="new-kit-name" placeholder="Kit name&#x2026;" autocomplete="off"
               style="width:100%;padding:6px 8px;background:#0b0e15;border:1px solid #242c3d;color:#e8ebf2;border-radius:4px;font-size:.85rem;margin-bottom:4px;"
               onkeydown="if(event.key==='Enter')confirmNewKit();if(event.key==='Escape')cancelNewKit()">
        <div style="display:flex;gap:5px;">
          <button class="btn-primary" style="flex:1;" onclick="confirmNewKit()">Create</button>
          <button class="btn-secondary" style="padding:7px 10px;" onclick="cancelNewKit()">&#x2715;</button>
        </div>
      </div>
      <div id="kit-list" class="kit-list" style="max-height:200px;overflow-y:auto;"></div>
      <div style="margin-top:6px;padding-top:6px;border-top:1px solid #20283a;display:flex;flex-direction:column;gap:4px;">
        <button class="btn-secondary" style="width:100%;font-size:.78rem;" onclick="showNewKitForm()">+ New kit from scratch</button>
        <select id="template-sel" style="width:100%;padding:5px 7px;background:#0b0e15;border:1px solid #242c3d;color:#aac;border-radius:4px;font-size:.78rem;" onchange="if(this.value)runTemplate(this.value);this.value=''">
          <option value="">New from template&#x2026;</option>
          <option value="make_metal_kit">Metal Baseline</option>
        </select>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="syncKitsFromCard()">&#x1F4BE; Sync kits from card</button>
        <button id="sync-lib-btn" class="btn-secondary" style="width:100%;font-size:.72rem;background:#0d2030;border-color:#1a5080;" onclick="syncLibrary()">&#x2B07; Sync full library from SD</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="exportKits()">&#x1F4E4; Export kits to JSON</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="printMidiMap()">&#x1F5A8; Print MIDI map</button>
        <label class="btn-secondary" style="width:100%;font-size:.72rem;display:block;text-align:center;cursor:pointer;box-sizing:border-box;">
          &#x1F4CB; Import assignment CSV
          <input type="file" accept=".csv,.txt" style="display:none;"
            onchange="if(this.files[0])importAssignCSV(this.files[0]);this.value=''">
        </label>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="showDiffModal()">&#x1F50D; Compare with kit&#x2026;</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="openTimeMachine()">&#x1F570;&#xFE0F; Kit time machine&#x2026;</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="showRelinkModal()">&#x1F527; Fix broken paths&#x2026;</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="showKitFxModal()">&#x1F39A; Kit FX editor&#x2026;</button>
        <button class="btn-secondary" style="width:100%;font-size:.72rem;" onclick="exportBundle()">&#x1F4E6; Export kit bundle (.zip)</button>
        <label class="btn-secondary" style="width:100%;font-size:.72rem;display:block;text-align:center;cursor:pointer;box-sizing:border-box;"
          title="Accepts strike_remap bundles, official Strike Editor exports, and commercial pack zips (eDrumWorkshop, drum-tec, …)">
          &#x1F4E6; Import bundle / editor .zip&#x2026;
          <input type="file" accept=".zip" style="display:none;"
            onchange="if(this.files[0])importBundle(this.files[0]);this.value=''">
        </label>
        <div id="sync-progress" class="sync-progress" style="display:none;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span id="sync-phase" style="color:#88aacc;font-weight:600;"></span>
            <span id="sync-counts" style="color:#556;"></span>
          </div>
          <div class="sync-bar-wrap"><div id="sync-bar" class="sync-bar" style="width:0%"></div></div>
          <div id="sync-detail" class="sync-detail"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Save split button -->
  <div class="tb-group">
    <div style="display:flex;gap:0;">
      <button class="btn-primary tb-btn" id="save-lib-btn" onclick="saveToLibrary()" disabled
              style="border-radius:4px 0 0 4px;">Save</button>
      <button class="btn-primary tb-btn" onclick="menuToggle('save-menu')"
              style="border-radius:0 4px 4px 0;padding:5px 7px;font-size:.7rem;border-left:1px solid #c03050;">&#9660;</button>
    </div>
    <div id="save-menu" class="tb-popover" style="display:none;min-width:220px;">
      <button id="save-sd-btn" class="btn-secondary" onclick="saveToSD()" disabled
              style="width:100%;margin-bottom:6px;">Save to SD card</button>
      <details>
        <summary style="font-size:.72rem;color:#666;cursor:pointer;">Custom path&#x2026;</summary>
        <div style="margin-top:5px;display:flex;flex-direction:column;gap:4px;">
          <input type="text" id="save-path" placeholder="Full path to .skt" autocomplete="off" spellcheck="false"
                 style="width:100%;padding:6px 8px;background:#0b0e15;border:1px solid #242c3d;color:#e8ebf2;border-radius:4px;font-size:.82rem;">
          <button class="btn-secondary" onclick="saveCustom()">Save to this path</button>
        </div>
      </details>
      <p id="save-hint" style="font-size:.7rem;color:#666;margin-top:6px;"></p>
    </div>
  </div>

  <!-- Duplicate -->
  <div class="tb-group">
    <button class="btn-secondary tb-btn" id="dup-btn" onclick="showDuplicateForm()" disabled>Duplicate&#x2026;</button>
    <div id="dup-form" class="dup-form" style="display:none;">
      <input type="text" id="dup-name" placeholder="Copy name&#x2026;" autocomplete="off"
             onkeydown="if(event.key==='Enter')confirmDuplicate();if(event.key==='Escape')cancelDuplicate()">
      <div style="display:flex;gap:4px;">
        <button class="btn-primary" style="flex:1;" onclick="confirmDuplicate()">Save copy</button>
        <button class="btn-secondary" onclick="cancelDuplicate()">&#x2715;</button>
      </div>
    </div>
  </div>

  <!-- Clear all pads -->
  <button class="btn-secondary tb-btn" id="clear-pads-btn" onclick="clearAllPads()" disabled style="color:#c06060;">Clear all pads</button>

  <div style="flex:1;"></div>

  <span id="msg"></span>
  <span id="kit-size-badge" style="display:none;font-size:.72rem;color:#668;flex-shrink:0;"></span>
  <span id="dirty-badge" style="display:none;">&#9679; Unsaved</span>
  <div style="position:relative;display:inline-flex;gap:2px;flex-shrink:0;">
    <button id="undo-btn" class="btn-secondary tb-btn" onclick="undoLast()" disabled title="Undo (Ctrl+Z)">&#x21A9; Undo</button>
    <button id="undo-hist-btn" class="btn-secondary tb-btn" style="padding:5px 7px;" onclick="toggleUndoHistory()" disabled title="Undo history">&#9660;</button>
    <div id="undo-hist-panel" class="undo-hist-panel" style="display:none;"></div>
  </div>

  <!-- Tools -->
  <div class="tb-group">
    <button class="btn-secondary tb-btn" onclick="menuToggle('tools-menu');loadTools()">&#x1F527; Tools &#9660;</button>
    <div id="tools-menu" class="tb-popover" style="display:none;right:0;left:auto;min-width:260px;max-height:60vh;overflow-y:auto;">
      <button class="btn-secondary" style="width:100%;font-size:.72rem;margin-bottom:6px;"
        title="Back up / restore the module's trigger settings (sensitivity, xTalk, scan time) via MIDI SysEx — Chrome/Edge only"
        onclick="showTrigModal()">&#x1F39B; Trigger settings backup&#x2026;</button>
      <div id="tools-list"></div>
      <div id="tool-output" class="tool-output"></div>
    </div>
  </div>

  <button id="vmod-btn" class="btn-secondary tb-btn" onclick="toggleVirtualModule()"
          title="Virtual module — play the kit being edited from the pads or number keys" style="flex-shrink:0;">Virtual</button>
  <span id="vm-vel-wrap" style="display:none;align-items:center;gap:3px;flex-shrink:0;font-size:.7rem;color:#888;">
    <input id="vm-vel" type="range" min="1" max="127" value="100" style="width:64px;vertical-align:middle;"
           title="Keyboard-hit velocity (number keys 1–0)"></span>
  <button id="midi-btn" class="btn-secondary tb-btn" onclick="toggleMidi()"
          title="Enable MIDI monitor — hit a pad to see it light up" style="flex-shrink:0;">MIDI</button>
  <span id="vol-status" style="font-size:.75rem;color:#888;flex-shrink:0;"></span>
  <button id="theme-btn" class="btn-secondary tb-btn" onclick="toggleTheme()" title="Toggle dark/light theme" style="font-size:.9rem;flex-shrink:0;">&#9790;</button>
</header>
<div class="main">

  <!-- Left: back panel jacks + pad editor -->
  <div id="left-panel">
    <div id="patch-panel-wrap">
      <div class="patch-hdr" onclick="togglePatchPanel()">
        <span class="patch-hdr-lbl">Back panel jacks</span>
        <span id="patch-toggle-arrow" style="font-size:.6rem;color:#445;margin-left:auto">&#9660;</span>
      </div>
      <div id="patch-panel"></div>
    </div>
    <div id="pad-detail">
      <div class="det-empty">Load a kit, then click a pad to edit it</div>
    </div>
  </div>

  <!-- Center: drum map + live loop -->
  <section id="center-panel">
    <div class="center-hdr">
      Drum Map&nbsp;<span id="kit-name" class="center-hdr-kit" contenteditable="false" spellcheck="false" title="Click to rename kit"></span>
      <span id="parse-warn" style="display:none;" title="This kit file has bytes the parser doesn't fully understand. It loaded fine, but saving may not reproduce the original exactly. Check the server console for details.">&#9888; parser</span>
      <button id="batch-toggle-btn" class="btn-secondary" style="margin-left:auto;font-size:.68rem;padding:2px 8px;"
        onclick="batchToggle()" title="Select multiple pads and apply a parameter to all at once">&#x2611; Batch edit</button>
      <button id="reset-layout-btn" class="btn-secondary" style="font-size:.68rem;padding:2px 8px;"
        onclick="resetAllOverrides()" title="Restore all pads to default positions and shapes.">Reset layout</button>
      <button class="btn-secondary" style="font-size:.68rem;padding:2px 8px;"
        onclick="exportLayout()" title="Save your customized kit layout (positions, sizes, rotation, finish) to a file.">&#x2913; Save layout</button>
      <button class="btn-secondary" style="font-size:.68rem;padding:2px 8px;"
        onclick="document.getElementById('layout-file').click()" title="Load a kit layout file saved earlier.">&#x2912; Load layout</button>
      <input type="file" id="layout-file" accept="application/json,.json" style="display:none"
        onchange="importLayout(this.files[0]); this.value=''">
    </div>
    <div id="batch-panel">
      <span class="batch-info" id="batch-count">0 pads selected</span>
      <button class="btn-secondary" style="font-size:.65rem;padding:2px 7px;" onclick="batchSelectAll()">All</button>
      <button class="btn-secondary" style="font-size:.65rem;padding:2px 7px;" onclick="batchClearSel()">None</button>
      <div class="batch-param-row">
        <label>Param:</label>
        <select id="batch-param" style="flex:1;padding:2px 4px;background:#0b0e15;border:1px solid #313a4d;color:#e8ebf2;border-radius:3px;font-size:.72rem;">
          <option value="la_level">Layer A level</option>
          <option value="la_pan">Layer A pan</option>
          <option value="la_pitch">Layer A pitch</option>
          <option value="la_fine">A fine pitch</option>
          <option value="la_loop">A loop (0=off,1=on)</option>
          <option value="la_vel_min">A vel range min</option>
          <option value="la_vel_max">A vel range max</option>
          <option value="la_decay">A decay</option>
          <option value="la_vel_vol">A vel→vol</option>
          <option value="la_vel_dec">A vel→dec</option>
          <option value="la_vel_pch">A vel→pch</option>
          <option value="la_vel_flt">A vel→flt</option>
          <option value="la_fcut">A filter cutoff</option>
          <option value="lb_level">B level</option>
          <option value="lb_pan">B pan</option>
          <option value="lb_pitch">B pitch</option>
          <option value="lb_fine">B fine pitch</option>
          <option value="lb_loop">B loop (0=off,1=on)</option>
          <option value="lb_decay">B decay</option>
          <option value="lb_vel_vol">B vel→vol</option>
          <option value="lb_vel_dec">B vel→dec</option>
          <option value="lb_vel_pch">B vel→pch</option>
          <option value="lb_vel_flt">B vel→flt</option>
          <option value="lb_fcut">B filter cutoff</option>
          <option value="xfade_vel">Vel. xfade</option>
          <option value="reverb">Reverb</option>
          <option value="fx1">FX1</option>
          <option value="fx2">FX2</option>
          <option value="priority">Priority</option>
          <option value="midi_note">MIDI note</option>
          <option value="midi_chan">MIDI channel</option>
          <option value="mute_grp">Mute group</option>
        </select>
        <label>Value:</label>
        <input id="batch-value" type="number" value="0" style="width:54px;padding:2px 4px;background:#0b0e15;border:1px solid #313a4d;color:#e8ebf2;border-radius:3px;font-size:.72rem;">
        <button class="btn-primary" style="font-size:.68rem;padding:3px 10px;" onclick="batchApply()">Apply</button>
      </div>
      <button class="btn-secondary" style="font-size:.65rem;padding:2px 7px;margin-left:auto;" onclick="batchToggle()">&#x2715; Done</button>
    </div>
    <div id="drum-svg-wrap" title="Scroll to zoom · Double-click empty area to reset">
      <svg id="drum-svg" viewBox="0 0 700 320" xmlns="http://www.w3.org/2000/svg"></svg>
    </div>
    <div id="loop-panel">
      <div class="loop-hdr" onclick="toggleLoopPanel()">
        <span class="loop-hdr-lbl">Live Loop</span>
        <span id="loop-toggle-arrow" style="font-size:.6rem;color:#445;margin-left:auto;">&#9654;</span>
      </div>
      <div id="loop-body" style="display:none;">
        <div class="loop-controls">
          <button id="loop-play-btn" class="btn-secondary" onclick="loopToggle()">&#9654; Play</button>
          <label>BPM</label>
          <input id="loop-bpm" type="number" min="40" max="240" value="100"
                 onchange="if(liveLoop)liveLoop.setBpm(+this.value)">
          <label>Pattern</label>
          <select id="loop-pattern" onchange="if(liveLoop)liveLoop.loadPattern(this.value)">
            <option value="simple44">Simple 4/4</option>
            <option value="metal">Metal</option>
            <option value="halftime">Half-time</option>
            <option value="blank">Blank</option>
          </select>
          <label>Vol</label>
          <input type="range" id="loop-vol" min="0" max="1" step="0.05" value="0.8"
                 style="width:60px;height:3px;accent-color:#f0b32e;cursor:pointer;"
                 oninput="if(liveLoop)liveLoop.setVolume(+this.value)">
        </div>
        <div class="loop-grid" id="loop-grid"></div>
      </div>
    </div>
  </section>

  <!-- Right: instrument browser -->
  <section id="inst-panel">
    <div style="padding:6px 12px 0;">
    <div id="assign-target" class="assign-target empty">Click a pad or jack to assign instruments</div>
    <!-- Import WAV form -->
    <div id="import-wav-form">
      <div id="import-drop-zone" onclick="document.getElementById('import-file-input').click()"
           ondragover="event.preventDefault();this.classList.add('drag-over')"
           ondragleave="this.classList.remove('drag-over')"
           ondrop="handleImportDrop(event)">
        &#128266; Drop WAV(s) here — 1 file or multiple for velocity layers
      </div>
      <input type="file" id="import-file-input" accept=".wav,audio/wav" multiple
             onchange="stageFiles([...this.files].filter(f=>f.name.toLowerCase().endsWith('.wav')))">
      <div id="import-staged-list"></div>
      <div class="import-grid">
        <span>Name</span>
        <input type="text" id="import-name" placeholder="Instrument name&#x2026;" autocomplete="off">
        <span>Category</span>
        <input type="text" id="import-category" value="Custom" placeholder="Custom">
        <span>Mode</span>
        <select id="import-mode" onchange="recalcVelBands();renderStagedFiles();">
          <option value="velocity">Velocity layers</option>
          <option value="roundrobin">Round-robin (same vel, cycles)</option>
        </select>
      </div>
      <label style="font-size:.72rem;color:#889;display:flex;align-items:center;gap:5px;margin-top:4px;">
        <input type="checkbox" id="import-normalize"> Normalize to -0.1 dBFS
      </label>
      <label style="font-size:.72rem;color:#889;display:flex;align-items:center;gap:5px;margin-top:4px;"
             title="Measure each WAV's peak, sort quiet to loud, and assign velocity ranges automatically (overrides per-file ranges)">
        <input type="checkbox" id="import-automap"> Auto-map velocity by loudness
      </label>
      <button id="import-create-btn" class="btn-primary" onclick="createInstrument()" disabled
              style="width:100%;margin-top:6px;font-size:.78rem;padding:6px;">Create instrument</button>
      <div id="import-progress" style="min-height:1.2em;font-size:.72rem;color:#88c090;margin-top:4px;"></div>
      <button class="btn-secondary" style="width:100%;font-size:.75rem;padding:4px;margin-top:4px;" onclick="hideImportForm()">Close</button>
    </div>
    <div id="tag-chips-row"></div>
    <div style="display:flex;gap:4px;margin-bottom:6px;">
      <input type="text" id="inst-search" placeholder="Search&#x2026;" oninput="renderInstruments()" style="flex:1;margin-bottom:0;">
      <button class="btn-secondary" style="font-size:.7rem;padding:4px 8px;flex-shrink:0;" onclick="toggleImportForm()" title="Import your own WAV files">&#43; WAV</button>
    </div>
    <div class="browser-toolbar">
      <select id="inst-sort" onchange="savePref('instSort',this.value);instSort=this.value;renderInstruments()">
        <option value="az">A–Z</option>
        <option value="used">Most used</option>
        <option value="recent">Recently added</option>
      </select>
      <label><input type="checkbox" id="hover-preview-chk" onchange="savePref('hoverPreview',this.checked);hoverPreview=this.checked"> Hover preview</label>
      <label><input type="checkbox" id="auto-preview-chk"  onchange="savePref('autoPreview',this.checked);autoPreview=this.checked"> Auto-preview on assign</label>
      <label>Vol <input type="range" id="preview-vol-slider" min="0" max="1" step="0.05" value="1"
        style="width:48px;vertical-align:middle;accent-color:#f0b32e;"
        oninput="previewVol=+this.value;if(previewAudio)previewAudio.volume=previewVol*previewVelGain;savePref('previewVol',previewVol)"></label>
      <label>Vel <input type="range" id="preview-vel-slider" min="1" max="127" step="1" value="127"
        style="width:48px;vertical-align:middle;accent-color:#9060cc;"
        oninput="previewVelGain=+this.value/127;if(previewAudio)previewAudio.volume=previewVol*previewVelGain;savePref('previewVel',+this.value)"></label>
    </div>
    <div id="inst-list"></div>
    </div><!-- /padding wrapper -->
  </section>

</div>
<script>
// ── Live loop constants ───────────────────────────────────────────────────────
const LOOP_ROWS = [
  {id:'K1H', label:'KICK'},
  {id:'S1H', label:'SNARE'},
  {id:'H1B', label:'HH'},
  {id:'H1E', label:'HH-O'},
  {id:'T1H', label:'TOM 1'},
  {id:'T2H', label:'TOM 2'},
  {id:'T3H', label:'TOM 3'},
  {id:'T4H', label:'TOM 4'},
  {id:'C1B', label:'CRASH'},
  {id:'R1B', label:'RIDE'},
];

const LOOP_PRESETS = {
  simple44: {
    K1H: [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],
    S1H: [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
    H1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  metal: {
    K1H: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
    S1H: [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
    R1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  halftime: {
    K1H: [1,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
    S1H: [0,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0],
    H1B: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  },
  blank: {},
};

// ── LiveLoop class ────────────────────────────────────────────────────────────
class LiveLoop {
  constructor() {
    this.ctx        = null;
    this.masterGain = null;
    this.bufCache   = {};  // sinRel → Promise<AudioBuffer|null>
    this.pattern    = {};  // padId → bool[16]
    this.muted      = new Set();
    this.bpm        = 100;
    this.curStep    = -1;
    this._step      = 0;
    this._nextTime  = 0;
    this._timer     = null;
    this.running    = false;

    // Restore persisted state
    try {
      const s = JSON.parse(localStorage.getItem('loop_state') || '{}');
      if (s.bpm)     this.bpm = s.bpm;
      if (s.pattern) this.pattern = s.pattern;
      if (s.muted)   this.muted = new Set(s.muted);
    } catch(e) {}

    // Fill any missing rows with blank arrays
    for (const row of LOOP_ROWS) {
      if (!this.pattern[row.id]) this.pattern[row.id] = Array(16).fill(0);
    }
  }

  _initCtx() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.value = parseFloat(document.getElementById('loop-vol').value || '0.8');
      this.masterGain.connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
  }

  setBpm(v) {
    this.bpm = Math.max(40, Math.min(240, v));
    this._saveState();
  }

  setVolume(v) {
    if (this.masterGain) this.masterGain.gain.value = v;
  }

  loadPattern(name, save = true) {
    const preset = LOOP_PRESETS[name] || {};
    for (const row of LOOP_ROWS) {
      this.pattern[row.id] = (preset[row.id] || Array(16).fill(0)).slice();
    }
    if (save) this._saveState();
    renderLoopGrid();
  }

  toggleStep(padId, step) {
    if (!this.pattern[padId]) this.pattern[padId] = Array(16).fill(0);
    this.pattern[padId][step] ^= 1;
    this._saveState();
    renderLoopGrid();
  }

  toggleMute(padId) {
    if (this.muted.has(padId)) this.muted.delete(padId);
    else this.muted.add(padId);
    this._saveState();
    renderLoopGrid();
  }

  start() {
    this._initCtx();
    this._step     = 0;
    this._nextTime = this.ctx.currentTime + 0.05;
    this.running   = true;
    this._schedule();
    this._timer = setInterval(() => this._schedule(), 25);
    document.getElementById('loop-play-btn').classList.add('playing');
    document.getElementById('loop-play-btn').innerHTML = '&#9632; Stop';
    if (pads.length) this.prefetchAll();
  }

  stop() {
    this.running = false;
    clearInterval(this._timer);
    this._timer  = null;
    this.curStep = -1;
    const btn = document.getElementById('loop-play-btn');
    if (btn) { btn.classList.remove('playing'); btn.innerHTML = '&#9654; Play'; }
    renderLoopGrid();
  }

  _schedule() {
    const LOOKAHEAD = 0.1;
    while (this.running && this._nextTime < this.ctx.currentTime + LOOKAHEAD) {
      this._fireStep(this._step, this._nextTime);
      this._nextTime += 60 / this.bpm / 4;
      this._step = (this._step + 1) % 16;
    }
  }

  _fireStep(step, when) {
    // Schedule visual indicator
    const delay = Math.max(0, (when - this.ctx.currentTime) * 1000 - 15);
    setTimeout(() => { this.curStep = step; renderLoopStepHighlight(); }, delay);

    for (const row of LOOP_ROWS) {
      if (!this.pattern[row.id]?.[step]) continue;
      if (this.muted.has(row.id)) continue;
      const p = pads.find(pd => pd.id === row.id);
      if (!p?.layer_a_path) continue;
      const gain = (p.la_level ?? 95) / 127;
      this._play(p.layer_a_path, when, gain);
    }
  }

  _play(sinRel, when, gain) {
    this._getBuffer(sinRel).then(buf => {
      if (!buf || !this.running) return;
      const src = this.ctx.createBufferSource();
      const gn  = this.ctx.createGain();
      src.buffer = buf;
      gn.gain.value = Math.min(1, Math.max(0, gain));
      src.connect(gn);
      gn.connect(this.masterGain);
      src.start(Math.max(when, this.ctx.currentTime));
    }).catch(() => {});
  }

  _getBuffer(sinRel) {
    if (!this.bufCache[sinRel]) {
      this.bufCache[sinRel] = fetch('/api/wav?sin=' + encodeURIComponent(sinRel))
        .then(r => r.ok ? r.arrayBuffer() : null)
        .then(ab => ab ? this.ctx.decodeAudioData(ab) : null)
        .catch(() => null);
    }
    return this.bufCache[sinRel];
  }

  invalidate(sinRel) { delete this.bufCache[sinRel]; }

  prefetchAll() {
    if (!this.ctx) return;
    for (const p of pads) {
      if (p.layer_a_path) this._getBuffer(p.layer_a_path);
      if (p.layer_b_path) this._getBuffer(p.layer_b_path);
    }
  }

  _saveState() {
    try {
      localStorage.setItem('loop_state', JSON.stringify({
        bpm:     this.bpm,
        pattern: this.pattern,
        muted:   [...this.muted],
      }));
    } catch(e) {}
  }
}

let liveLoop       = null;
let loopPanelOpen  = false;
try { loopPanelOpen = localStorage.getItem('loopPanelOpen') === '1'; } catch(e) {}

function toggleLoopPanel() {
  loopPanelOpen = !loopPanelOpen;
  document.getElementById('loop-body').style.display = loopPanelOpen ? '' : 'none';
  document.getElementById('loop-toggle-arrow').textContent = loopPanelOpen ? '▾' : '▸';
  if (loopPanelOpen && !liveLoop) {
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }
  try { localStorage.setItem('loopPanelOpen', loopPanelOpen ? '1' : '0'); } catch(e) {}
}

function loopToggle() {
  if (!liveLoop) {
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }
  if (liveLoop.running) liveLoop.stop();
  else liveLoop.start();
}

function renderLoopGrid() {
  const el = document.getElementById('loop-grid');
  if (!el) return;
  el.innerHTML = LOOP_ROWS.map(row => {
    const steps   = liveLoop?.pattern[row.id] || Array(16).fill(0);
    const isMuted = liveLoop?.muted.has(row.id);
    const lblCls  = 'loop-row-lbl' + (isMuted ? ' muted' : '');
    const cells   = [];
    for (let i = 0; i < 16; i++) {
      if (i > 0 && i % 4 === 0) cells.push('<span class="loop-beat-gap"></span>');
      const on  = steps[i];
      const cur = liveLoop?.curStep === i;
      let cls = 'loop-step' + (on ? ' on' : '') + (cur ? ' cur' : '');
      cells.push(`<button class="${cls}" data-step="${i}" onclick="liveLoop.toggleStep('${row.id}',${i})"></button>`);
    }
    return `<div class="loop-row">
      <span class="${lblCls}" onclick="liveLoop&&liveLoop.toggleMute('${row.id}')" title="Click to mute">${row.label}</span>
      <div class="loop-steps">${cells.join('')}</div>
    </div>`;
  }).join('');
}

function renderLoopStepHighlight() {
  const el = document.getElementById('loop-grid');
  if (!el) return;
  el.querySelectorAll('.loop-step.cur').forEach(b => b.classList.remove('cur'));
  const idx = liveLoop?.curStep ?? -1;
  if (idx >= 0) {
    el.querySelectorAll(`.loop-step[data-step="${idx}"]`).forEach(b => b.classList.add('cur'));
  }
}

// ── Theme ─────────────────────────────────────────────────────────────────────
let themeLight = false;
try { themeLight = localStorage.getItem('strike_theme') === 'light'; } catch(e) {}
function applyTheme() {
  document.body.dataset.theme = themeLight ? 'light' : 'dark';
  const btn = document.getElementById('theme-btn');
  if (btn) { btn.title = themeLight ? 'Switch to dark' : 'Switch to light'; btn.textContent = themeLight ? '☀' : '☾'; }
}
function toggleTheme() {
  themeLight = !themeLight;
  try { localStorage.setItem('strike_theme', themeLight ? 'light' : 'dark'); } catch(e) {}
  applyTheme();
}

// ── Favorites & recently used ─────────────────────────────────────────────────
let favorites  = new Set();
let recentInst = [];
try { favorites  = new Set(JSON.parse(localStorage.getItem('strike_favorites') || '[]')); } catch(e) {}
try { recentInst = JSON.parse(localStorage.getItem('strike_recent') || '[]');            } catch(e) {}

function toggleFavorite(rel) {
  if (favorites.has(rel)) favorites.delete(rel); else favorites.add(rel);
  try { localStorage.setItem('strike_favorites', JSON.stringify([...favorites])); } catch(e) {}
  renderInstruments();
}
function addToRecent(rel) {
  recentInst = [rel, ...recentInst.filter(r => r !== rel)].slice(0, 20);
  try { localStorage.setItem('strike_recent', JSON.stringify(recentInst)); } catch(e) {}
}
function clearRecent() {
  recentInst = [];
  try { localStorage.setItem('strike_recent', '[]'); } catch(e) {}
  renderInstruments();
}

// ── Undo history labels ───────────────────────────────────────────────────────
let undoLabels   = [];
let undoHistOpen = false;

function toggleUndoHistory() {
  undoHistOpen = !undoHistOpen;
  const panel = document.getElementById('undo-hist-panel');
  if (undoHistOpen) {
    renderUndoHistory();
    panel.style.display = '';
    setTimeout(() => document.addEventListener('click', _closeUndoHistOnce, {once:true, capture:true}), 0);
  } else {
    panel.style.display = 'none';
  }
}
function _closeUndoHistOnce(e) {
  if (document.getElementById('undo-hist-panel')?.contains(e.target)) return;
  undoHistOpen = false;
  const p = document.getElementById('undo-hist-panel');
  if (p) p.style.display = 'none';
}
function renderUndoHistory() {
  const panel = document.getElementById('undo-hist-panel');
  if (!panel) return;
  if (!undoLabels.length) {
    panel.innerHTML = '<div class="undo-hist-item" style="cursor:default;color:#666;">No history</div>';
    return;
  }
  panel.innerHTML = undoLabels.map((lbl, i) =>
    `<div class="undo-hist-item" onclick="undoToStep(${i})">&#x21A9;${i > 0 ? ` (${i+1}&times;)` : ''} ${escHtml(lbl || 'Change')}</div>`
  ).join('');
}
async function undoToStep(idx) {
  document.getElementById('undo-hist-panel').style.display = 'none';
  undoHistOpen = false;
  for (let i = 0; i <= idx && undoCount > 0; i++) await undoLast();
}

// ── Instrument browser prefs ──────────────────────────────────────────────────
let instSort    = 'az';
let instMtimes  = {};
let hoverPreview = false;
let autoPreview  = false;
try { instSort     = localStorage.getItem('strike_instSort') || 'az'; } catch(e) {}
try { hoverPreview = localStorage.getItem('strike_hoverPreview') === 'true'; } catch(e) {}
try { autoPreview  = localStorage.getItem('strike_autoPreview') === 'true'; } catch(e) {}

function savePref(key, value) {
  try { localStorage.setItem('strike_' + key, String(value)); } catch(e) {}
}

let selectedPad    = null;   // {id, layer} — active assignment target
let selectedMapPad = null;   // id string — pad shown in detail panel
let selectedGroup  = null;   // group key — controls patch panel highlight + detail view

let brokenPaths   = new Set(); // sin_rel paths not found in avail
let batchMode     = false;
let batchSelected = new Set(); // pad IDs selected for batch apply

// Tags
let instTags     = {};  // {sin_rel: [tag, ...]} loaded from /api/tags
let activeTagFilter = null;  // tag string currently filtering the browser

// Drum-map zoom state (viewBox in SVG units)
const SVG_DEF_W = 700, SVG_DEF_H = 320;
let svgView = {x: 0, y: 0, w: SVG_DEF_W, h: SVG_DEF_H};
function applySvgView() {
  const svg = document.getElementById('drum-svg');
  if (svg) svg.setAttribute('viewBox', `${svgView.x} ${svgView.y} ${svgView.w} ${svgView.h}`);
}

// Layer blend preview AudioContext (shared, lazy-created)
let _blendCtx = null;

let kits           = [];
let pads           = [];
let avail          = {};
let kitName        = '';
let libSavePath    = '';
let sdSavePath     = '';
let state_kitPath  = '';
let expandedCats   = new Set();
let undoCount      = 0;

// Audio preview state
let previewAudio   = null;
let previewRel     = null;
let previewVol     = 1;
let previewVelGain = 1;
try { previewVol     = parseFloat(localStorage.getItem('strike_previewVol') ?? '1') || 1; } catch(e) {}
try { previewVelGain = (parseFloat(localStorage.getItem('strike_previewVel') ?? '127') || 127) / 127; } catch(e) {}

// ── Waveform thumbnails ───────────────────────────────────────────────────────
const _waveObserver = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (!e.isIntersecting) return;
    const canvas = e.target;
    _waveObserver.unobserve(canvas);
    if (canvas.dataset.loaded) return;
    canvas.dataset.loaded = '1';
    fetch('/api/waveform?sin=' + encodeURIComponent(canvas.dataset.sin))
      .then(r => r.json())
      .then(d => { if (d.peaks) drawWaveform(canvas, d.peaks); })
      .catch(() => {});
  });
}, {rootMargin: '120px'});

function drawWaveform(canvas, peaks) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, mid = H / 2;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#4a8060';
  ctx.lineWidth = 1;
  ctx.beginPath();
  peaks.forEach((p, i) => {
    const x = (i / peaks.length) * W;
    const h = p * mid * 0.92;
    ctx.moveTo(x, mid - h);
    ctx.lineTo(x, mid + h);
  });
  ctx.stroke();
}

function attachWaveObservers() {
  document.querySelectorAll('.waveform-canvas:not([data-loaded])').forEach(c => _waveObserver.observe(c));
}

// ── MIDI monitor ──────────────────────────────────────────────────────────────
let midiAccess  = null;
let midiActive  = false;
const midiFlashTimers = {};  // {padId: timeoutId}

async function toggleMidi() {
  if (midiActive) {
    midiActive = false;
    updateMidiBtn();
    setMsg('MIDI monitor off');
    return;
  }
  if (!navigator.requestMIDIAccess) {
    setMsg('Web MIDI requires Chrome or Edge', true);
    return;
  }
  try {
    midiAccess = await navigator.requestMIDIAccess({ sysex: false });
    midiActive = true;
    for (const input of midiAccess.inputs.values()) input.onmidimessage = handleMidiMessage;
    midiAccess.onstatechange = e => {
      if (e.port.type === 'input' && e.port.state === 'connected')
        e.port.onmidimessage = handleMidiMessage;
    };
    updateMidiBtn();
    setMsg('MIDI active — hit a pad');
  } catch(e) {
    setMsg('MIDI access denied: ' + e.message, true);
  }
}

function handleMidiMessage(e) {
  if (!midiActive || e.data.length < 3) return;
  const [status, note, velocity] = e.data;
  if ((status & 0xf0) === 0x90 && velocity > 0) {
    // Build note → pad_id map on the fly (respects user-edited MIDI notes)
    let matched = false;
    for (const p of pads) {
      if (p.midi_note === note) {
        flashPad(p.id, velocity);
        const sinRel = p.layer_a_path || p.layer_b_path;
        if (sinRel) previewInstrument(sinRel);
        matched = true;
        break;
      }
    }
    setMsg(`MIDI note ${note} vel ${velocity}${matched ? '' : ' — no pad matched'}`);
  }
}

function flashPad(padId, velocity) {
  const g = document.querySelector(`#drum-svg [data-pid="${CSS.escape(padId)}"]`);
  if (!g) return;
  // Restart animation by removing + re-adding the class
  g.classList.remove('midi-hit');
  void g.getBoundingClientRect();  // force reflow
  g.classList.add('midi-hit');
  // Remove class after animation so it can fire again on the next hit
  if (midiFlashTimers[padId]) clearTimeout(midiFlashTimers[padId]);
  midiFlashTimers[padId] = setTimeout(() => {
    g.classList.remove('midi-hit');
    delete midiFlashTimers[padId];
  }, 500);
}

function updateMidiBtn() {
  const btn = document.getElementById('midi-btn');
  if (!btn) return;
  btn.textContent = midiActive ? '● MIDI' : 'MIDI';
  btn.style.color  = midiActive ? '#00ee77' : '';
  btn.title = midiActive ? 'MIDI active — click to stop' : 'Enable MIDI monitor (Chrome/Edge only)';
}

// ── Virtual module mode ───────────────────────────────────────────────────────
// Play the kit being edited straight from the drum pads (or number keys) with no
// SD write / module reload. MIDI note-on → match pad by midi_note → resolve Layer
// A/B by velocity → play the right samples via Web Audio, honoring velocity zones,
// round-robin/random cycling, xfade, per-layer level+pan, semitone+fine pitch,
// mute-group choke (open/closed hi-hat), and Mono/Poly. Decay is APPROXIMATED with
// a gain envelope and velocity→loudness is a fixed curve; module FX and the
// velocity→filter/pitch/decay response curves are NOT simulated (see button title).
// Buffers are pre-decoded so the hit path never fetches/decodes when warm.
const VM_PRELOAD_LIMIT = 100 * 1024 * 1024;  // decode everything up front under 100 MB
const VM_KEYS = '1234567890';                // keyboard fallback → first 10 manifest pads
let vmActive     = false;
let vmManifest   = null;
let vmCtx        = null;          // one persistent AudioContext
let vmBuffers    = new Map();     // wav_url → AudioBuffer | Promise<AudioBuffer>
let vmVoices     = [];            // live voices: {padId, layer, muteGrp, gain, src}
let vmRR         = new Map();     // "padId:layer:band" → next round-robin index
let vmHH         = 127;           // last hi-hat pedal value (CC#4); 127 = fully open
let vmRev        = -1;            // last manifest rev seen (for the /api/selected poll hook)
let vmDecodeDone = 0, vmDecodeTotal = 0;
let vmMidiWired  = false;

async function toggleVirtualModule() {
  if (vmActive) { vmStop(); return; }
  let m;
  try {
    m = await (await fetch('/api/kit_playback')).json();
  } catch(e) { setMsg('Virtual module: manifest fetch failed', true); return; }
  if (!m || m.error) { setMsg('Virtual module: ' + (m && m.error || 'no kit loaded'), true); return; }
  vmManifest = m; vmRev = m.rev;
  vmActive = true;
  try {
    if (!vmCtx) vmCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (vmCtx.state === 'suspended') await vmCtx.resume();
  } catch(e) { vmActive = false; setMsg('Virtual module: no Web Audio', true); return; }
  updateVmBtn();
  vmWireMidi();
  await vmPreload();
  updateVmBtn();
}

function vmStop() {
  vmActive = false;
  for (const v of vmVoices.slice()) { try { v.src.stop(); } catch(e){} }
  vmVoices = [];
  updateVmBtn();
  setMsg('Virtual module off');
}

function updateVmBtn() {
  const btn = document.getElementById('vmod-btn');
  const wrap = document.getElementById('vm-vel-wrap');
  if (!btn) return;
  if (!vmActive) {
    btn.textContent = 'Virtual'; btn.style.color = '';
    if (wrap) wrap.style.display = 'none';
  } else if (vmDecodeTotal && vmDecodeDone < vmDecodeTotal) {
    btn.textContent = `VM ${vmDecodeDone}/${vmDecodeTotal}`; btn.style.color = '#ffb020';
    if (wrap) wrap.style.display = 'none';
  } else {
    btn.textContent = '● VM'; btn.style.color = '#00ee77';
    if (wrap) wrap.style.display = 'inline-flex';
  }
  btn.title =
    'Virtual module — play the kit being edited from the pads or number keys (1–0).\n' +
    'Simulated: velocity zones, round-robin/random, A/B xfade, level, pan, pitch, mute-group choke, Mono/Poly.\n' +
    'Approximated: decay (gain envelope), velocity loudness curve, hi-hat pedal position.\n' +
    'NOT simulated: module FX (reverb/FX1/FX2/EQ), velocity→filter/pitch/decay curves, filter, loop, gate time.';
}

function vmAllUrls() {
  const urls = new Set();
  if (vmManifest) for (const p of vmManifest.pads)
    for (const key of ['a', 'b']) {
      const lyr = p.layers[key];
      if (lyr && lyr.mappings) for (const mp of lyr.mappings) if (mp.wav_url) urls.add(mp.wav_url);
    }
  return [...urls];
}

async function vmPreload() {
  const urls = vmAllUrls();
  vmDecodeTotal = urls.length; vmDecodeDone = 0;
  if (vmManifest.total_bytes > VM_PRELOAD_LIMIT) {
    // Large kit: decode lazily on first hit; don't block the toggle.
    vmDecodeTotal = 0;
    setMsg(`Virtual module ready — lazy decode (${(vmManifest.total_bytes / 1048576) | 0} MB kit)`);
    return;
  }
  for (const u of urls) {
    if (!vmActive) return;
    try { await vmGetBuffer(u); } catch(e){}
    vmDecodeDone++;
    if (vmDecodeDone % 4 === 0) updateVmBtn();
  }
  setMsg('Virtual module ready — hit a pad or press 1–0');
}

function vmGetBuffer(url) {
  const cached = vmBuffers.get(url);
  if (cached) return Promise.resolve(cached);   // AudioBuffer or in-flight Promise
  const pr = fetch(url)
    .then(r => { if (!r.ok) throw new Error('wav ' + r.status); return r.arrayBuffer(); })
    .then(ab => vmCtx.decodeAudioData(ab))
    .then(buf => { vmBuffers.set(url, buf); return buf; })
    .catch(err => { vmBuffers.delete(url); throw err; });
  vmBuffers.set(url, pr);
  return pr;
}

// Candidate mappings for a velocity, with hi-hat pedal filtering + pedal-function exclusion.
function vmCandidates(lyr, vel) {
  let cands = lyr.mappings.filter(m =>
    m.wav_url && vel >= m.vmin && vel <= m.vmax && m.rr !== 254);  // 254 = 0xFE pedal-function
  if (cands.length > 1) {
    const hh = cands.filter(m => vmHH >= m.hh_min && vmHH <= m.hh_max);
    if (hh.length) cands = hh;   // fall back to ignoring hh ranges when nothing matches
  }
  return cands;
}

function vmPick(padId, key, cands, cycleRandom) {
  if (cands.length === 1) return cands[0];
  const sorted = cands.slice().sort((a, b) => a.rr - b.rr);
  if (cycleRandom === 1) return sorted[Math.floor(Math.random() * sorted.length)];
  const band = `${padId}:${key}:${sorted[0].vmin}-${sorted[0].vmax}`;
  const n = vmRR.get(band) || 0;
  vmRR.set(band, (n + 1) % sorted.length);
  return sorted[n % sorted.length];
}

function vmChoke(v) {
  const now = vmCtx.currentTime;
  try {
    v.gain.gain.cancelScheduledValues(now);
    v.gain.gain.setValueAtTime(v.gain.gain.value, now);
    v.gain.gain.linearRampToValueAtTime(0, now + 0.01);   // ~10 ms fade, no click
    v.src.stop(now + 0.012);
  } catch(e){}
}

// Core hit path. `pad` is a manifest pad (has .layers); `velocity` 1–127.
function vmTrigger(pad, velocity) {
  if (!vmActive || !vmCtx || !pad) return;
  const vel = Math.max(1, Math.min(127, velocity | 0));
  const dbg = { padId: pad.id, vel, layers: [] };

  // Choke live voices: any same non-zero mute group, plus this pad's own voices in Mono.
  const choked = [];
  for (const v of vmVoices.slice()) {
    if ((pad.mute_grp && v.muteGrp === pad.mute_grp) ||
        (pad.play_mode === 0 && v.padId === pad.id)) {
      vmChoke(v);
      const i = vmVoices.indexOf(v); if (i >= 0) vmVoices.splice(i, 1);
      choked.push(v.padId + ':' + v.layer);
    }
  }

  for (const key of ['a', 'b']) {
    const lyr = pad.layers[key];
    if (!lyr || lyr.error || !lyr.skt) continue;
    if (vel < lyr.skt.vel_min || vel > lyr.skt.vel_max) continue;   // layer velocity window / xfade
    const cands = vmCandidates(lyr, vel);
    if (!cands.length) { dbg.layers.push({ layer: key, mappingIdx: null, reason: 'no zone' }); continue; }
    const m = vmPick(pad.id, key, cands, lyr.cycle_random);
    const gain = (lyr.skt.level / 127) * ((lyr.sin.level || 127) / 127) * Math.pow(vel / 127, 1.5);
    const pan  = Math.max(-50, Math.min(50, (lyr.skt.pan || 0) + (lyr.sin.pan || 0))) / 50;
    const rate = Math.pow(2, ((lyr.sin.semi + lyr.skt.pitch) + (lyr.sin.fine + lyr.skt.fine) / 100) / 12);
    const decay = Math.min(lyr.skt.decay, 99);
    dbg.layers.push({ layer: key, mappingIdx: m.idx, wavUrl: m.wav_url, gain, pan, rate, decay, choked });
    vmPlay(m.wav_url, { padId: pad.id, layer: key, muteGrp: pad.mute_grp, gain, pan, rate, decay });
  }
  flashPad(pad.id, vel);
  window.vmLastHit = dbg;
}

function vmPlay(url, opt) {
  const start = (buf) => {
    if (!vmActive || !buf) return;
    const src = vmCtx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = opt.rate;
    const gain = vmCtx.createGain();
    gain.gain.value = opt.gain;
    src.connect(gain);
    if (vmCtx.createStereoPanner) {
      const pan = vmCtx.createStereoPanner();
      pan.pan.value = opt.pan;
      gain.connect(pan); pan.connect(vmCtx.destination);
    } else {
      gain.connect(vmCtx.destination);
    }
    if (opt.decay < 99) {   // approximate decay: exponential-ish tail via time constant
      const tau = 0.04 + (opt.decay / 99) * 2.5;   // 0 → ~40 ms, ~99 → ~2.5 s
      gain.gain.setTargetAtTime(0.0001, vmCtx.currentTime + 0.005, tau);
    }
    const voice = { padId: opt.padId, layer: opt.layer, muteGrp: opt.muteGrp, gain, src };
    vmVoices.push(voice);
    src.onended = () => { const i = vmVoices.indexOf(voice); if (i >= 0) vmVoices.splice(i, 1); };
    src.start();
  };
  const cached = vmBuffers.get(url);
  if (cached && !(cached instanceof Promise)) start(cached);   // warm → zero-latency
  else vmGetBuffer(url).then(start).catch(() => {});           // cold (lazy kit) → decode then play
}

function vmWireMidi() {
  if (vmMidiWired || !navigator.requestMIDIAccess) return;   // keyboard fallback works regardless
  const wire = (access) => {
    for (const input of access.inputs.values()) input.addEventListener('midimessage', vmOnMidi);
    access.addEventListener('statechange', e => {
      if (e.port.type === 'input' && e.port.state === 'connected') {
        e.port.removeEventListener('midimessage', vmOnMidi);
        e.port.addEventListener('midimessage', vmOnMidi);
      }
    });
    vmMidiWired = true;
  };
  // Reuse the monitor's MIDIAccess if present (addEventListener stacks with its onmidimessage).
  if (midiAccess) wire(midiAccess);
  else navigator.requestMIDIAccess({ sysex: false })
        .then(a => { if (!midiAccess) midiAccess = a; wire(a); })
        .catch(() => {});
}

function vmOnMidi(e) {
  if (!vmActive || !e.data || e.data.length < 2) return;
  const cmd = e.data[0] & 0xf0, d1 = e.data[1], d2 = e.data[2] || 0;
  if (cmd === 0xB0 && d1 === 4) { vmHH = d2; return; }   // CC#4 = hi-hat pedal position
  if (cmd === 0x90 && d2 > 0) {
    const pad = vmManifest && vmManifest.pads.find(p => p.midi_note === d1);
    if (pad) vmTrigger(pad, d2);
  }
}

// Keyboard fallback: number keys 1–0 fire the first 10 manifest pads at the slider velocity.
document.addEventListener('keydown', e => {
  if (!vmActive || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
  const i = VM_KEYS.indexOf(e.key);
  if (i < 0 || !vmManifest || !vmManifest.pads[i]) return;
  const velEl = document.getElementById('vm-vel');
  vmTrigger(vmManifest.pads[i], parseInt(velEl && velEl.value || '100', 10));
});

async function vmRefreshManifest() {
  try {
    const m = await (await fetch('/api/kit_playback')).json();
    if (!m || m.error) return;
    vmManifest = m;
    if (m.total_bytes <= VM_PRELOAD_LIMIT)   // warm any newly-referenced samples
      for (const u of vmAllUrls()) if (!vmBuffers.has(u)) vmGetBuffer(u).catch(() => {});
  } catch(e){}
}

// ── Trigger settings backup (SysEx over Web MIDI) ─────────────────────────────
// The module's trigger config (per-input sensitivity, scan time, xTalk, MIDI
// mapping) lives in firmware, not on the SD card. Its Send function emits it as
// one 236-byte SysEx message (F0 00 00 0E …). We capture that dump, save/load it
// as .syx, and can replay it verbatim to restore. Byte 27 = xTalk RCV is the
// only mapped field so far.
const TRIG_ALESIS_HEADER = [0xF0, 0x00, 0x00, 0x0E];
const TRIG_KNOWN_BYTES = {27: 'xTalk RCV'};
let trigAccess = null;   // MIDIAccess with sysex permission (separate from the monitor's)
let trigDump = null;     // Uint8Array — last captured or loaded dump
let trigDumpSource = ''; // 'captured' | 'loaded: <filename>'
let trigOtherMsgs = 0;   // non-Alesis SysEx seen while listening

function showTrigModal() {
  closeAllPopovers();
  renderTrigModal();
  document.getElementById('trig-modal').classList.add('open');
}

async function trigConnect() {
  if (!navigator.requestMIDIAccess) {
    setMsg('Web MIDI requires Chrome or Edge', true);
    return;
  }
  try {
    trigAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch (e) {
    setMsg('SysEx access denied: ' + e.message, true);
    return;
  }
  // addEventListener (not onmidimessage=) so we coexist with the MIDI monitor
  for (const input of trigAccess.inputs.values()) input.addEventListener('midimessage', trigOnMsg);
  trigAccess.onstatechange = e => {
    if (e.port.type === 'input' && e.port.state === 'connected') {
      e.port.removeEventListener('midimessage', trigOnMsg);
      e.port.addEventListener('midimessage', trigOnMsg);
    }
    renderTrigModal();
  };
  renderTrigModal();
  setMsg('Listening for SysEx — press Send on the module');
}

function trigOnMsg(e) {
  if (!e.data || e.data[0] !== 0xF0) return;
  const isAlesis = TRIG_ALESIS_HEADER.every((b, i) => e.data[i] === b);
  if (isAlesis && e.data[e.data.length - 1] === 0xF7) {
    trigDump = new Uint8Array(e.data);
    trigDumpSource = 'captured';
    setMsg(`Captured trigger settings dump (${trigDump.length} bytes)`);
  } else {
    trigOtherMsgs++;
  }
  renderTrigModal();
}

function trigSave() {
  if (!trigDump) return;
  const d = new Date();
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([trigDump], {type: 'application/octet-stream'}));
  a.download = `strike-trigger-settings-${stamp}.syx`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function trigLoad(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes[0] !== 0xF0 || bytes[bytes.length - 1] !== 0xF7) {
    setMsg('Not a SysEx file (must start F0 and end F7)', true);
    return;
  }
  trigDump = bytes;
  trigDumpSource = 'loaded: ' + file.name;
  renderTrigModal();
  setMsg(`Loaded ${file.name} (${bytes.length} bytes)`);
}

async function trigRestore() {
  if (!trigDump || !trigAccess) return;
  const sel = document.getElementById('trig-out-sel');
  const out = sel && trigAccess.outputs.get(sel.value);
  if (!out) { setMsg('No MIDI output selected', true); return; }
  const isAlesis = TRIG_ALESIS_HEADER.every((b, i) => trigDump[i] === b);
  const warn = isAlesis ? '' : '\n\n⚠ This dump does NOT have the Alesis header — sending it to the module is untested.';
  if (!await appConfirm(`Send ${trigDump.length} bytes of SysEx to "${out.name}"?\nThis overwrites the module's current trigger settings with the ${trigDumpSource} dump.${warn}`, 'Send')) return;
  out.send(trigDump);
  setMsg(`Sent ${trigDump.length} bytes to ${out.name}`);
}

function trigHexView(bytes) {
  const rows = [];
  for (let off = 0; off < bytes.length; off += 16) {
    const cells = [];
    for (let i = off; i < Math.min(off + 16, bytes.length); i++) {
      const h = bytes[i].toString(16).padStart(2, '0');
      cells.push(TRIG_KNOWN_BYTES[i]
        ? `<span class="known" title="byte ${i}: ${TRIG_KNOWN_BYTES[i]} = ${bytes[i]}">${h}</span>` : h);
    }
    rows.push(off.toString().padStart(4, ' ') + '  ' + cells.join(' '));
  }
  return rows.join('\n');
}

function renderTrigModal() {
  const body = document.getElementById('trig-body');
  if (!body) return;
  const connected = !!trigAccess;
  const ins  = connected ? [...trigAccess.inputs.values()] : [];
  const outs = connected ? [...trigAccess.outputs.values()] : [];
  const strikeOut = outs.find(o => /strike/i.test(o.name)) || outs[0];
  const isAlesis = trigDump && TRIG_ALESIS_HEADER.every((b, i) => trigDump[i] === b);
  body.innerHTML = `
    <div style="font-size:.74rem;color:#9ab;line-height:1.5;">
      Trigger settings (sensitivity, scan time, xTalk, trigger→MIDI mapping) live in the module's
      firmware — not on the SD card. This backs them up via MIDI SysEx and can restore them later.
      <b>Chrome/Edge only; module connected via USB.</b>
      Capture and save are read-only and always safe. <b>Restore to module is experimental</b> —
      it replays a captured dump verbatim; capture a known-good .syx backup first and only
      restore dumps taken from your own module.
    </div>
    ${!connected ? `
      <button class="btn-primary" style="margin-top:10px;align-self:flex-start;" onclick="trigConnect()">Connect MIDI (SysEx)</button>`
    : `
      <div style="font-size:.72rem;color:#88a;margin-top:8px;">
        Inputs: ${ins.length ? ins.map(i => escHtml(i.name)).join(', ') : '<span style="color:#c66;">none — is the module connected?</span>'}
      </div>
      <div style="margin-top:8px;padding:8px;background:#0d2030;border:1px solid #1a5080;border-radius:4px;font-size:.74rem;color:#aac;">
        <b>To capture:</b> on the module press <b>SAVE</b> → <b>Send</b> (trigger settings send).
        The dump appears below automatically.${trigOtherMsgs ? ` <span style="color:#667;">(${trigOtherMsgs} non-Alesis SysEx message(s) ignored)</span>` : ''}
      </div>
      ${trigDump ? `
        <div style="margin-top:10px;font-size:.74rem;">
          <b style="color:${isAlesis ? '#7c6' : '#c96'};">${isAlesis ? '✓ Alesis trigger dump' : '⚠ SysEx (non-Alesis header)'}</b>
          — ${trigDump.length} bytes, ${escHtml(trigDumpSource)}${trigDump.length !== 236 && isAlesis ? ' <span style="color:#c96;">(expected 236)</span>' : ''}
          ${isAlesis && trigDump.length > 27 ? ` · <b>xTalk RCV = ${trigDump[27]}</b> <span style="color:#667;">(byte 27 — only mapped field so far)</span>` : ''}
        </div>
        <div class="trig-hex" style="margin-top:6px;max-height:180px;overflow-y:auto;">${trigHexView(trigDump)}</div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center;">
          <button class="btn-secondary" onclick="trigSave()">&#x1F4BE; Save .syx</button>
          <select id="trig-out-sel" class="midi-select" style="max-width:200px;">
            ${outs.map(o => `<option value="${escHtml(o.id)}"${strikeOut && o.id === strikeOut.id ? ' selected' : ''}>${escHtml(o.name)}</option>`).join('')}
          </select>
          <button class="btn-primary" onclick="trigRestore()" ${outs.length ? '' : 'disabled'}>&#x2B06; Restore to module</button>
        </div>`
      : '<div style="margin-top:10px;font-size:.74rem;color:#667;">No dump captured yet.</div>'}
      <label class="btn-secondary" style="margin-top:10px;align-self:flex-start;font-size:.72rem;cursor:pointer;">
        &#x1F4C2; Load .syx file&#x2026;
        <input type="file" accept=".syx,.bin" style="display:none;" onchange="if(this.files[0])trigLoad(this.files[0]);this.value=''">
      </label>`}
    <div style="font-size:.65rem;color:#667;margin-top:8px;">Restore replays the module's own bytes verbatim — no values are modified. Editing individual settings needs the remaining ~200 bytes mapped (see PLANNED.md).</div>`;
}

function updatePlayButtons() {
  // Update all play buttons in-place without re-rendering the list (preserves scroll)
  document.querySelectorAll('.play-btn[data-rel]').forEach(btn => {
    const r = btn.getAttribute('data-rel');
    const playing = r === previewRel;
    btn.className   = 'play-btn' + (playing ? ' playing' : '');
    btn.title       = playing ? 'Stop preview' : 'Preview sound';
    btn.innerHTML   = playing ? '&#9632;' : '&#9654;';
  });
}

function previewInstrument(rel) {
  // Toggle: clicking the currently-playing instrument stops it
  if (previewAudio) {
    previewAudio.pause();
    previewAudio.src = '';
    previewAudio = null;
    const wasRel = previewRel;
    previewRel = null;
    updatePlayButtons();
    if (wasRel === rel) return;  // same item → just stop
  }
  previewRel   = rel;
  previewAudio = new Audio('/api/preview?sin=' + encodeURIComponent(rel));
  previewAudio.volume = previewVol * previewVelGain;
  previewAudio.onended = () => {
    previewAudio = null; previewRel = null; updatePlayButtons();
  };
  previewAudio.onerror = () => {
    setMsg('Preview unavailable — mount the preset SD card to enable audio', true);
    previewAudio = null; previewRel = null; updatePlayButtons();
  };
  updatePlayButtons();  // flip button to ■ immediately
  previewAudio.play().catch(() => {});
}

function stopPreview() {
  if (previewAudio) { previewAudio.pause(); previewAudio.src = ''; previewAudio = null; }
  if (previewRel) { previewRel = null; updatePlayButtons(); }
}

// Patch panel collapse state (persisted in localStorage)
let patchCollapsed = false;
try { patchCollapsed = localStorage.getItem('patchCollapsed') === '1'; } catch(e) {}
function applyPatchPanelState() {
  const panel = document.getElementById('patch-panel');
  const arrow = document.getElementById('patch-toggle-arrow');
  if (panel) panel.style.display = patchCollapsed ? 'none' : '';
  if (arrow) arrow.textContent = patchCollapsed ? '▸' : '▾';
}
function togglePatchPanel() {
  patchCollapsed = !patchCollapsed;
  try { localStorage.setItem('patchCollapsed', patchCollapsed ? '1' : '0'); } catch(e) {}
  applyPatchPanelState();
}

// Pad layout overrides persisted in localStorage: {padId: {cx?,cy?,rx?,ry?,type?,lbl?}}
let padOverrides = {};
try { padOverrides = JSON.parse(localStorage.getItem('strike_pad_overrides') || '{}'); } catch(e) {}

// Drag state
let dragState = null;  // {id, origCx, origCy, startX, startY, moved}

// ── Pad layout: [id, type, cx, cy, rx, ry, label] ──────────────────────────
// Back-to-front order so rims/edges render behind head counterparts.
const PAD_DEFS = [
  ['K1H','kick',   362,272, 76,27,'KICK'],
  ['S1R','rim',    165,208, 58,21,''],
  ['S1H','snare',  165,208, 50,18,'SNR'],
  ['T1R','rim',    262,157, 48,18,''],
  ['T1H','tom',    262,157, 41,15,'T1'],
  ['T2R','rim',    365,140, 51,19,''],
  ['T2H','tom',    365,140, 44,16,'T2'],
  ['T3R','rim',    468,155, 48,18,''],
  ['T3H','tom',    468,155, 41,15,'T3'],
  ['T4R','rim',    567,198, 60,22,''],
  ['T4H','floor',  567,198, 52,19,'T4'],
  ['H1E','cym-e',   83, 92, 55,12,''],
  ['H1B','cymbal',  83, 92, 38, 8,'HH'],
  ['H1F','hfoot',   63,293, 22, 9,'HHF'],
  ['C1E','cym-e',  210, 58, 63,13,''],
  ['C1B','cymbal', 210, 58, 43, 9,'C1'],
  ['C2E','cym-e',  380, 42, 70,14,''],
  ['C2B','cymbal', 380, 42, 47,10,'C2'],
  ['C3E','cym-e',  530, 55, 60,13,''],
  ['C3B','cymbal', 530, 55, 40, 9,'C3'],
  ['R1E','cym-e',  630, 88, 70,14,''],
  ['R1B','cymbal', 630, 88, 48,10,'RD'],
  ['R1D','bell',   630, 88, 18, 5,''],
];

// Default rx,ry per type — applied when user changes a pad's shape type
const PAD_TYPE_SIZES = {
  'kick':  [76,27], 'snare': [50,18], 'rim':   [52,20],
  'tom':   [41,15], 'floor': [52,19], 'cymbal':[45,10],
  'cym-e': [62,14], 'bell':  [18, 5], 'hfoot': [22, 9],
};

// Companion zones that must move together (share same physical position)
const PAD_COMPANIONS = {
  'S1H':['S1R'],         'S1R':['S1H'],
  'T1H':['T1R'],         'T1R':['T1H'],
  'T2H':['T2R'],         'T2R':['T2H'],
  'T3H':['T3R'],         'T3R':['T3H'],
  'T4H':['T4R'],         'T4R':['T4H'],
  'H1B':['H1E'],         'H1E':['H1B'],
  'C1B':['C1E'],         'C1E':['C1B'],
  'C2B':['C2E'],         'C2E':['C2B'],
  'C3B':['C3E'],         'C3E':['C3B'],
  'R1B':['R1E','R1D'],   'R1E':['R1B','R1D'],   'R1D':['R1E','R1B'],
};

// When you change a pad's shape type, what should each companion become?
// null = leave the companion alone (bell/hfoot never auto-change).
function companionTypeFor(mainType, compOrigType) {
  if (compOrigType === 'bell' || compOrigType === 'hfoot') return null;
  const drums = new Set(['kick','snare','tom','floor','rim']);
  if (drums.has(mainType))   return 'rim';
  if (mainType === 'cymbal') return 'cym-e';
  if (mainType === 'cym-e')  return 'cymbal';
  return null;
}

// Drum shell finishes and cymbal tones — applied as a CSS filter on the sprite <use>,
// so one drum recolors without touching the shared sprite defs. `swatch` = a representative
// colour for the picker UI. Chrome/mesh are desaturated so hue-rotate leaves them alone.
const DRUM_FINISHES = {
  'red':     {name:'Red Sparkle',    swatch:'#c22a3a', filter:''},
  'black':   {name:'Black',          swatch:'#26282e', filter:'saturate(.12) brightness(.55)'},
  'white':   {name:'White',          swatch:'#e9ebef', filter:'saturate(.16) brightness(1.75)'},
  'silver':  {name:'Silver Sparkle', swatch:'#aeb3bd', filter:'saturate(.28) brightness(1.4)'},
  'blue':    {name:'Blue Sparkle',   swatch:'#2f6fcf', filter:'hue-rotate(210deg) saturate(1.05)'},
  'green':   {name:'Emerald',        swatch:'#2b9d4c', filter:'hue-rotate(120deg) saturate(.95)'},
  'purple':  {name:'Purple',         swatch:'#7a3fcf', filter:'hue-rotate(275deg) saturate(1.05)'},
  'amber':   {name:'Amber',          swatch:'#d98a2b', filter:'hue-rotate(-28deg) saturate(1.1) brightness(1.05)'},
  'natural': {name:'Natural Wood',   swatch:'#a5713f', filter:'hue-rotate(-18deg) saturate(.55) brightness(1.15)'},
};
const CYM_FINISHES = {
  'brass':     {name:'Brass',       swatch:'#d8a932', filter:''},
  'bronze':    {name:'Dark Bronze', swatch:'#9c7526', filter:'hue-rotate(-8deg) saturate(.9) brightness(.8)'},
  'brilliant': {name:'Brilliant',   swatch:'#f0d878', filter:'saturate(.8) brightness(1.25)'},
  'black':     {name:'Black',       swatch:'#2a2c30', filter:'saturate(.15) brightness(.5)'},
};
// Which finish set applies to a pad type (hfoot = chrome, no finish).
function finishSetFor(type) {
  if (['kick','snare','tom','floor','rim'].includes(type)) return DRUM_FINISHES;
  if (['cymbal','cym-e','bell'].includes(type))            return CYM_FINISHES;
  return null;
}

const PAD_COLORS = {
  'kick':   {fill:'#16191f', stroke:'#5a6373'},
  'snare':  {fill:'#16191f', stroke:'#5f6878'},
  'rim':    {fill:'#12151c', stroke:'#49536a'},
  'tom':    {fill:'#15181f', stroke:'#525c6e'},
  'floor':  {fill:'#14171d', stroke:'#4c5566'},
  'cymbal': {fill:'#221c02', stroke:'#caa030'},
  'cym-e':  {fill:'#1a1400', stroke:'#a8841c'},
  'bell':   {fill:'#2a2002', stroke:'#ecc045'},
  'hfoot':  {fill:'#1a1408', stroke:'#8a6c1c'},
};

// GM drum note labels for the MIDI note picker
const GM_DRUMS_JS = {
  35:'Ac. Bass Dr.', 36:'Bass Drum 1', 37:'Side Stick', 38:'Ac. Snare', 39:'Hand Clap',
  40:'Elec. Snare', 41:'Lo Floor Tom', 42:'Closed HH', 43:'Hi Floor Tom', 44:'Pedal HH',
  45:'Lo Tom', 46:'Open HH', 47:'Lo-Mid Tom', 48:'Hi-Mid Tom', 49:'Crash Cym. 1',
  50:'Hi Tom', 51:'Ride Cym. 1', 52:'Chinese Cym.', 53:'Ride Bell', 54:'Tambourine',
  55:'Splash Cym.', 56:'Cowbell', 57:'Crash Cym. 2', 58:'Vibraslap',
  59:'Ride Cym. 2', 60:'Hi Bongo', 61:'Lo Bongo',
};

// Category accent colors for instrument browser folders
const CAT_COLORS = {
  'Kicks':'#c04030', 'Kick':'#c04030',
  'Snares':'#3878c8', 'Snare':'#3878c8',
  'Toms':'#289850', 'Tom':'#289850',
  'HiHats':'#b09020', 'Hi-Hat':'#b09020', 'HiHat':'#b09020', 'Hi Hats':'#b09020',
  'Cymbals':'#b06820', 'Cymbal':'#b06820', 'Crashes':'#b06820', 'Crash':'#b06820',
  'Rides':'#986030', 'Ride':'#986030',
  'Percussion':'#7060a8', 'Perc':'#7060a8',
  'Claps':'#909840', 'Clap':'#909840',
  'Sticks':'#506878', 'Fills':'#507888',
};
function catColor(cat) {
  if (CAT_COLORS[cat]) return CAT_COLORS[cat];
  const key = Object.keys(CAT_COLORS).find(k => cat.toLowerCase().includes(k.toLowerCase()));
  return key ? CAT_COLORS[key] : '#3a4a5a';
}

// Build map of sin_rel → [{id, layer}] for all currently assigned pads in the loaded kit
function buildInUseMap() {
  const m = {};
  for (const p of pads) {
    if (p.layer_a_path) { (m[p.layer_a_path] = m[p.layer_a_path] || []).push({id:p.id, layer:'A'}); }
    if (p.layer_b_path) { (m[p.layer_b_path] = m[p.layer_b_path] || []).push({id:p.id, layer:'B'}); }
  }
  return m;
}

// Physical jack groups — each group key maps to a label, jack label, and list of pad IDs
const PAD_GROUPS = {
  'KICK':    {label:'Kick',    jackLabel:'01 KICK',    pads:['K1H','K2H']},
  'SNARE':   {label:'Snare',   jackLabel:'02 SNARE',   pads:['S1H','S1R']},
  'TOM 1':   {label:'Tom 1',   jackLabel:'03 TOM 1',   pads:['T1H','T1R']},
  'TOM 2':   {label:'Tom 2',   jackLabel:'04 TOM 2',   pads:['T2H','T2R']},
  'TOM 3':   {label:'Tom 3',   jackLabel:'05 TOM 3',   pads:['T3H','T3R']},
  'TOM 4':   {label:'Tom 4',   jackLabel:'06 TOM 4',   pads:['T4H','T4R']},
  'HI-HAT':  {label:'Hi-Hat',  jackLabel:'07 HI-HAT',  pads:['H1B','H1E','H1F']},
  'CRASH 1': {label:'Crash 1', jackLabel:'08 CRASH 1', pads:['C1B','C1E']},
  'RIDE 1':  {label:'Ride 1',  jackLabel:'09 RIDE 1',  pads:['R1B','R1E']},
  'RIDE 2':  {label:'Ride 2',  jackLabel:'10 RIDE 2',  pads:['R1D']},
  'CRASH 2': {label:'Crash 2', jackLabel:'11 CRASH 2', pads:['C2B','C2E']},
  'CRASH 3': {label:'Crash 3', jackLabel:'12 CRASH 3', pads:['C3B','C3E']},
};
// Reverse lookup: padId → group key
const PAD_TO_GROUP = {};
for (const [k, g] of Object.entries(PAD_GROUPS)) for (const pid of g.pads) PAD_TO_GROUP[pid] = k;

// Patch panel rows: each entry is [groupKey, displayNumber, label]
// Top row = cymbal inputs (07-12); bottom row = drum inputs (01-06) + HH control
const JACK_ROWS = [
  [['HI-HAT', '07','HH'],      ['CRASH 1','08','CRASH 1'], ['RIDE 1','09','RIDE 1'],
   ['RIDE 2',  '10','RIDE 2'],  ['CRASH 2','11','CRASH 2'], ['CRASH 3','12','CRASH 3']],
  [['KICK',   '01','KICK'],    ['SNARE',  '02','SNARE'],    ['TOM 1', '03','TOM 1'],
   ['TOM 2',  '04','TOM 2'],   ['TOM 3',  '05','TOM 3'],    ['TOM 4', '06','TOM 4'],
   ['HI-HAT', '',  'HH CTRL']],
];

// Return [id, type, cx, cy, rx, ry, lbl] with any user overrides applied
function effectivePadDef(id) {
  const base = PAD_DEFS.find(d => d[0] === id);
  if (!base) return null;
  const [, bt, bcx, bcy, brx, bry, blbl] = base;
  const ov = padOverrides[id] || {};
  return [id,
    ov.type !== undefined ? ov.type : bt,
    ov.cx   !== undefined ? ov.cx   : bcx,
    ov.cy   !== undefined ? ov.cy   : bcy,
    ov.rx   !== undefined ? ov.rx   : brx,
    ov.ry   !== undefined ? ov.ry   : bry,
    ov.lbl  !== undefined ? ov.lbl  : blbl];
}

function savePadOverrides() {
  try { localStorage.setItem('strike_pad_overrides', JSON.stringify(padOverrides)); } catch(e) {}
  updateLayoutBadge();
}

function updateLayoutBadge() {
  const count = Object.keys(padOverrides).length;
  const btn   = document.getElementById('reset-layout-btn');
  if (!btn) return;
  if (count) {
    btn.textContent   = 'Reset layout ●';
    btn.style.color   = '#e0b060';
    btn.style.borderColor = '#604020';
    btn.title = count + ' pad(s) customized — positions & shapes are auto-saved in this browser. Click to restore defaults.';
  } else {
    btn.textContent   = 'Reset layout';
    btn.style.color   = '';
    btn.style.borderColor = '';
    btn.title = 'Restore all pads to default positions and shapes.';
  }
}

// Live setter for rotation / finish from the panel sliders + swatches. redrawPanel=false
// keeps a slider from being torn out mid-drag; the swatch picker passes true to restyle.
function setPadShape(id, key, value, redrawPanel) {
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id][key] = value;
  savePadOverrides();
  renderDrumMap();
  if (redrawPanel) renderPadDetail();
}

// Resize by scale relative to the pad type's default footprint (keeps the perspective ratio).
function setPadSize(id, scale) {
  const d = effectivePadDef(id);
  if (!d) return;
  const def = PAD_TYPE_SIZES[d[1]] || [d[4], d[5]];
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id].rx = Math.max(10, Math.round(def[0] * scale));
  padOverrides[id].ry = Math.max(4,  Math.round(def[1] * scale));
  savePadOverrides();
  renderDrumMap();
}

function setPadOverride(id, key, value) {
  if (!padOverrides[id]) padOverrides[id] = {};
  padOverrides[id][key] = value;
  if (key === 'type') {
    // Resize this pad to match its new type
    const sz = PAD_TYPE_SIZES[value];
    if (sz) { padOverrides[id].rx = sz[0]; padOverrides[id].ry = sz[1]; }
    // Sync every companion: rim becomes cym-e when turned into a cymbal, and vice versa
    for (const cid of (PAD_COMPANIONS[id] || [])) {
      const cBase    = PAD_DEFS.find(d => d[0] === cid);
      if (!cBase) continue;
      const newCType = companionTypeFor(value, cBase[1]);
      if (newCType) {
        if (!padOverrides[cid]) padOverrides[cid] = {};
        padOverrides[cid].type = newCType;
        const sz2 = PAD_TYPE_SIZES[newCType];
        if (sz2) { padOverrides[cid].rx = sz2[0]; padOverrides[cid].ry = sz2[1]; }
      }
    }
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function toggleMirrorPad(id) {
  if (!padOverrides[id]) padOverrides[id] = {};
  if (padOverrides[id].mirror) {
    delete padOverrides[id].mirror;
    if (!Object.keys(padOverrides[id]).length) delete padOverrides[id];
    setMsg('Mirror pad removed');
  } else {
    padOverrides[id].mirror = {dx: 150, dy: 0};
    setMsg('Mirror pad added — drag it anywhere; it is the same zone (shared settings)');
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function resetPadOverride(id) {
  delete padOverrides[id];
  // Reset companion cx/cy so they don't stay misaligned
  for (const cid of (PAD_COMPANIONS[id] || [])) {
    if (padOverrides[cid]) {
      delete padOverrides[cid].cx;
      delete padOverrides[cid].cy;
      if (!Object.keys(padOverrides[cid]).length) delete padOverrides[cid];
    }
  }
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

function resetAllOverrides() {
  padOverrides = {};
  savePadOverrides();
  renderDrumMap();
  renderPadDetail();
}

// ── Save / load kit layout (positions, sizes, rotation, finish, mirrors) ────────
const VALID_PAD_IDS = new Set(PAD_DEFS.map(d => d[0]));
function exportLayout() {
  const payload = {
    format: 'strike-remap-layout', version: 1,
    saved: new Date().toISOString(), overrides: padOverrides,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url; a.download = `strike-kit-layout-${stamp}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  const n = Object.keys(padOverrides).length;
  setMsg(`Saved layout (${n} customized pad${n === 1 ? '' : 's'})`);
}

async function importLayout(file) {
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const ov = (data && data.overrides && typeof data.overrides === 'object') ? data.overrides
             : (data && typeof data === 'object' && !data.format) ? data : null;  // tolerate a bare overrides object
    if (!ov) { setMsg('Not a valid layout file', true); return; }
    // Keep only recognized pad IDs; ignore anything else.
    const clean = {};
    for (const [id, o] of Object.entries(ov)) {
      if (VALID_PAD_IDS.has(id) && o && typeof o === 'object') clean[id] = o;
    }
    padOverrides = clean;
    savePadOverrides();
    renderDrumMap();
    renderPadDetail();
    const n = Object.keys(clean).length;
    setMsg(`Loaded layout (${n} customized pad${n === 1 ? '' : 's'})`);
  } catch (err) {
    setMsg('Could not read layout file: ' + err.message, true);
  }
}

// ── Patch panel ───────────────────────────────────────────────────────────────
function renderPatchPanel() {
  const el = document.getElementById('patch-panel');
  if (!el) return;
  el.innerHTML = JACK_ROWS.map(row =>
    `<div class="jack-row">${row.map(([grp, num, lbl]) => {
      const hot = selectedGroup === grp ? ' jack-hot' : '';
      return `<div class="jack-item${hot}" onclick="selectGroupFromPanel('${grp}')">`
        + `<div class="jack-plug"></div>`
        + (num ? `<div class="jack-num">${escHtml(num)}</div>` : '<div class="jack-num">&nbsp;</div>')
        + `<div class="jack-lbl">${escHtml(lbl)}</div></div>`;
    }).join('')}</div>`
  ).join('');
}

function selectGroupFromPanel(grpKey) {
  selectedGroup = grpKey;
  const g = PAD_GROUPS[grpKey];
  if (g && g.pads.length) {
    // Keep selectedPad if it's already in this group, otherwise default to first pad / layer A
    const keepPad = selectedPad && g.pads.includes(selectedPad.id);
    const pid = keepPad ? selectedPad.id : g.pads[0];
    selectedMapPad = pid;
    if (!keepPad) selectedPad = {id: pid, layer: 'a'};
  }
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
}

// ── Drag support ──────────────────────────────────────────────────────────────
function svgPt(svgEl, clientX, clientY) {
  const pt = svgEl.createSVGPoint();
  pt.x = clientX; pt.y = clientY;
  return pt.matrixTransform(svgEl.getScreenCTM().inverse());
}

function startDrag(e, id, isMirror) {
  e.preventDefault();
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);
  const def   = effectivePadDef(id);
  if (!def) return;
  const mir = isMirror ? ((padOverrides[id] || {}).mirror || {dx: 0, dy: 0}) : null;
  dragState = {id, isMirror: !!isMirror,
               origCx: def[2] + (mir ? mir.dx : 0), origCy: def[3] + (mir ? mir.dy : 0),
               baseCx: def[2], baseCy: def[3],
               startX: pt.x, startY: pt.y, moved: false};
}

// Resize / rotate handle drag — edits the pad's rx/ry or rot in padOverrides live.
function startHandle(e, id, kind) {
  e.preventDefault();
  e.stopPropagation();
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);
  const def   = effectivePadDef(id);
  if (!def) return;
  const cx = def[2], cy = def[3];
  dragState = {
    id, handle: kind, cx, cy,
    origRx: def[4], origRy: def[5], origRot: +((padOverrides[id] || {}).rot) || 0,
    startDist: Math.max(2, Math.hypot(pt.x - cx, pt.y - cy)),
    startAng:  Math.atan2(pt.y - cy, pt.x - cx) * 180 / Math.PI,
    moved: false,
  };
}

function svgMouseMove(e) {
  if (!dragState) return;
  const svgEl = document.getElementById('drum-svg');
  const pt    = svgPt(svgEl, e.clientX, e.clientY);

  // Handle drags (resize / rotate) operate on the base pad only.
  if (dragState.handle) {
    const dx0 = pt.x - dragState.cx, dy0 = pt.y - dragState.cy;
    if (!padOverrides[dragState.id]) padOverrides[dragState.id] = {};
    if (dragState.handle === 'resize') {
      const factor = Math.hypot(dx0, dy0) / dragState.startDist;
      padOverrides[dragState.id].rx = Math.max(10, Math.min(320, Math.round(dragState.origRx * factor)));
      padOverrides[dragState.id].ry = Math.max(4,  Math.min(220, Math.round(dragState.origRy * factor)));
    } else {
      // rotate grip sits above centre (−90°), so offset the pointer angle by +90°
      let rot = Math.round(Math.atan2(dy0, dx0) * 180 / Math.PI + 90);
      if (e.shiftKey) rot = Math.round(rot / 15) * 15;     // Shift = snap to 15°
      while (rot > 180) rot -= 360;  while (rot < -180) rot += 360;
      padOverrides[dragState.id].rot = rot;
    }
    dragState.moved = true;
    renderDrumMap();
    if (selectedMapPad && editTargetOf(selectedMapPad) === dragState.id) renderPadDetail();
    return;
  }

  const dx    = pt.x - dragState.startX;
  const dy    = pt.y - dragState.startY;
  if (Math.abs(dx) > 4 || Math.abs(dy) > 4) dragState.moved = true;
  if (!dragState.moved) return;
  const cx = Math.max(20, Math.min(680, Math.round(dragState.origCx + dx)));
  const cy = Math.max(10, Math.min(310, Math.round(dragState.origCy + dy)));
  if (dragState.isMirror) {
    if (!padOverrides[dragState.id]) padOverrides[dragState.id] = {};
    padOverrides[dragState.id].mirror = {dx: cx - dragState.baseCx, dy: cy - dragState.baseCy};
    renderDrumMap();
    return;
  }
  // Move this pad and all companions together
  const all = [dragState.id, ...(PAD_COMPANIONS[dragState.id] || [])];
  for (const pid of all) {
    if (!padOverrides[pid]) padOverrides[pid] = {};
    padOverrides[pid].cx = cx;
    padOverrides[pid].cy = cy;
  }
  renderDrumMap();
}

function svgMouseUp(e) {
  if (!dragState) return;
  const wasMoved = dragState.moved;
  const isHandle = !!dragState.handle;
  const id = dragState.id;
  dragState = null;
  if (isHandle) {
    if (wasMoved) { savePadOverrides(); renderPadDetail(); }
    return;  // handle clicks never select/deselect
  }
  if (wasMoved) {
    savePadOverrides();
    setMsg('Layout saved in browser (drag again to reposition; Reset layout to undo)');
  } else {
    clickPad(id);  // short click = select
  }
}

async function api(path, body) {
  const opts = body
    ? { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }
    : {};
  const r = await fetch('/api' + path, opts);
  return r.json();
}

// In-app async replacement for window.confirm(): themed, and automatable —
// native confirm() blocks the event loop and is auto-dismissed as "cancel"
// by headless browsers, which made restore/delete undriveable in tests.
let _confirmResolve = null;
function appConfirm(message, okLabel = 'OK') {
  let m = document.getElementById('confirm-modal');
  if (!m) {
    m = document.createElement('div');
    m.id = 'confirm-modal';
    m.innerHTML = '<div class="confirm-box"><p id="confirm-msg"></p>'
      + '<div class="confirm-actions">'
      + '<button id="confirm-cancel">Cancel</button>'
      + '<button id="confirm-ok" class="btn-primary"></button>'
      + '</div></div>';
    document.body.appendChild(m);
    m.addEventListener('click', e => { if (e.target === m) _confirmDone(false); });
    document.getElementById('confirm-cancel').onclick = () => _confirmDone(false);
    document.getElementById('confirm-ok').onclick     = () => _confirmDone(true);
    // Capture phase so Escape/Enter don't fall through to the global shortcuts
    document.addEventListener('keydown', e => {
      if (!m.classList.contains('open')) return;
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); _confirmDone(false); }
      if (e.key === 'Enter')  { e.preventDefault(); e.stopPropagation(); _confirmDone(true); }
    }, true);
  }
  document.getElementById('confirm-msg').textContent = message;
  document.getElementById('confirm-ok').textContent  = okLabel;
  m.classList.add('open');
  document.getElementById('confirm-ok').focus();
  return new Promise(res => { _confirmResolve = res; });
}
function _confirmDone(ok) {
  document.getElementById('confirm-modal').classList.remove('open');
  const r = _confirmResolve; _confirmResolve = null;
  if (r) r(ok);
}

// ── External controller bridge (Loupedeck) ──────────────────────────────────
// Mirror the selected pad to the server; poll for param edits made on dials.
let _extSel = null, _extRev = -1;

function postSelect() {
  const id = selectedMapPad || null;
  if (id === _extSel) return;
  _extSel = id;
  fetch('/api/select', {method:'POST', headers:{'Content-Type':'application/json'},
                        body: JSON.stringify({pad_id: id})}).catch(() => {});
}

setInterval(async () => {
  try {
    const s = await (await fetch('/api/selected')).json();
    if (vmActive && s.rev !== vmRev) { vmRev = s.rev; vmRefreshManifest(); }
    if (s.rev === _extRev) return;
    const first = _extRev === -1;
    _extRev = s.rev;
    if (first || !s.pad_id || !s.params) return;
    const p = pads.find(p => p.id === s.pad_id);
    if (!p) return;
    let changed = false;
    for (const k in s.params) if (p[k] !== s.params[k]) { p[k] = s.params[k]; changed = true; }
    if (changed) {
      if (selectedMapPad === s.pad_id) renderPadDetail();
      setDirtyState(true);
    }
  } catch {}
}, 1500);

function setMsg(txt, err=false) {
  const el = document.getElementById('msg');
  el.textContent = txt;
  el.className = err ? 'err' : '';
}

function setDirtyState(dirty, cnt, labels) {
  undoCount = cnt != null ? cnt : undoCount;
  if (labels !== undefined) undoLabels = labels;
  const badge = document.getElementById('dirty-badge');
  if (badge) badge.style.display = dirty ? '' : 'none';
  const undoBtn = document.getElementById('undo-btn');
  if (undoBtn) undoBtn.disabled = undoCount <= 0;
  const histBtn = document.getElementById('undo-hist-btn');
  if (histBtn) histBtn.disabled = undoCount <= 0;
  if (dirty) scheduleAutoSnapshot();  // leave a trail during an editing session (server dedupes)
}

async function undoLast() {
  const data = await api('/undo', {});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  const kfxModal = document.getElementById('kitfx-modal');
  if (kfxModal && kfxModal.classList.contains('open')) showKitFxModal();  // undo restores kit_raw too
  setMsg('Undo');
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Toolbar popover helpers ───────────────────────────────────────────────────
const POPOVERS = ['kit-menu', 'save-menu', 'tools-menu', 'dup-form'];

function closeAllPopovers() {
  POPOVERS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function menuToggle(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const isOpen = el.style.display !== 'none';
  closeAllPopovers();
  if (!isOpen) el.style.display = '';
}

document.addEventListener('click', e => {
  if (!e.target.closest('.tb-group')) {
    closeAllPopovers();
  }
});

// ── Kit list ──────────────────────────────────────────────────────────────────
const SOURCE_BADGE = {'library':'&#x1F4C1;', 'user SD':'&#x1F4BE;', 'preset SD':'&#x1F4BF;'};

function renderKitList() {
  const el = document.getElementById('kit-list');
  if (!kits.length) {
    el.innerHTML = '<div style="padding:8px;font-size:.78rem;opacity:.75;line-height:1.5;">'
      + 'No kits yet. Insert your Strike SD card (kits appear here automatically), '
      + 'or use <b>Tools &rarr; Sync full library from SD</b> once to edit without the card. '
      + 'Your factory preset card is read-only to this app &mdash; it is never written.</div>';
    return;
  }
  el.innerHTML = kits.map((k,i) => {
    const badge  = SOURCE_BADGE[k.source] || '';
    const active = state_kitPath && k.path === state_kitPath ? ' active' : '';
    return `<div class="kit-item${active}" onclick="openKit(${i})" title="${escHtml(k.path)}">`
      + `<span class="kit-src">${badge}</span>${escHtml(k.name)}</div>`;
  }).join('');
}

async function loadKitList() {
  const data = await api('/kits');
  kits = data.kits;
  renderKitList();
}

// Shared post-load state application: used by openKit, drag-drop .skt loading,
// and boot-time rehydration from /api/session.
function applyKitData(data, path, opts) {
  const {dirty = false, undoCount = 0, historyLabels = []} = opts || {};
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = path;
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kitNameEl = document.getElementById('kit-name');
  kitNameEl.textContent = '— ' + kitName;
  kitNameEl.contentEditable = 'true';
  document.getElementById('parse-warn').style.display = data.skt_lossless === false ? '' : 'none';
  document.getElementById('save-lib-btn').disabled    = !libSavePath;
  document.getElementById('save-sd-btn').disabled     = !sdSavePath;
  document.getElementById('dup-btn').disabled         = false;
  document.getElementById('clear-pads-btn').disabled  = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(dirty, undoCount, historyLabels);
  renderKitList();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  if (liveLoop?.ctx) liveLoop.prefetchAll();
  refreshKitSize();
  checkPaths();
}

async function openKit(idx) {
  stopPreview();
  const path = typeof idx === 'number' ? kits[idx].path : idx;
  const data = await api('/load', {path});
  if (data.error) { setMsg(data.error, true); return; }
  applyKitData(data, path);
  closeAllPopovers();
  setMsg(data.message);
}

// ── Drum map ──────────────────────────────────────────────────────────────────
// Strike Pro signature look: dark mesh heads on red-sparkle shells, brass cymbals
// Realistic drum sprites (ported from the drum-realism design mockup). Each sprite is
// modelled at native radius ~100 centred on 0,0; renderDrumMap() places one per pad via
// <use> with translate()+scale(). Rim = hoop-only overlay (transparent centre) that
// registers on its drum; bell = gold dome that sits at the ride's centre.
const DRUM_MAP_DEFS = `<defs>
  <radialGradient id="gShadow" cx="50%" cy="50%" r="50%">
    <stop offset=".55" stop-color="rgba(0,0,0,.42)"/><stop offset="1" stop-color="rgba(0,0,0,0)"/>
  </radialGradient>
  <radialGradient id="gMesh" cx="40%" cy="36%" r="70%">
    <stop offset="0" stop-color="#31343b"/><stop offset=".5" stop-color="#232529"/><stop offset="1" stop-color="#121316"/>
  </radialGradient>
  <pattern id="pMesh" width="5" height="5" patternUnits="userSpaceOnUse">
    <path d="M0 2.5H5M2.5 0V5" stroke="rgba(255,255,255,.06)" stroke-width="1"/>
  </pattern>
  <radialGradient id="gSpec" cx="50%" cy="50%" r="50%">
    <stop offset="0" stop-color="rgba(255,255,255,.12)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/>
  </radialGradient>
  <radialGradient id="gShellRed" cx="38%" cy="34%" r="78%">
    <stop offset="0" stop-color="#cf2a3d"/><stop offset=".5" stop-color="#941a29"/><stop offset="1" stop-color="#520d17"/>
  </radialGradient>
  <pattern id="pSparkle" width="9" height="9" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="3" r=".7" fill="rgba(255,214,220,.55)"/><circle cx="6.5" cy="7" r=".55" fill="rgba(255,170,180,.5)"/>
    <circle cx="7.5" cy="1.5" r=".5" fill="rgba(255,255,255,.45)"/><circle cx="4" cy="6" r=".45" fill="rgba(255,190,190,.4)"/>
  </pattern>
  <linearGradient id="gChrome" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f4f6f9"/><stop offset=".28" stop-color="#c3c9d1"/><stop offset=".52" stop-color="#6b7077"/>
    <stop offset=".72" stop-color="#b6bcc4"/><stop offset="1" stop-color="#4c4f55"/>
  </linearGradient>
  <linearGradient id="gChromeV" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#e9ecf0"/><stop offset=".5" stop-color="#82878e"/><stop offset=".78" stop-color="#d4d9df"/><stop offset="1" stop-color="#54575c"/>
  </linearGradient>
  <linearGradient id="gTube" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#9ba0a8"/><stop offset=".45" stop-color="#e2e6eb"/><stop offset="1" stop-color="#3f4247"/>
  </linearGradient>
  <radialGradient id="gCym" cx="40%" cy="35%" r="74%">
    <stop offset="0" stop-color="#f2d78a"/><stop offset=".35" stop-color="#dab55b"/><stop offset=".75" stop-color="#a67e30"/><stop offset="1" stop-color="#6d5017"/>
  </radialGradient>
  <radialGradient id="gBell" cx="42%" cy="38%" r="65%">
    <stop offset="0" stop-color="#f9e6a8"/><stop offset=".55" stop-color="#c99b42"/><stop offset="1" stop-color="#7c5d1e"/>
  </radialGradient>
  <radialGradient id="gCymE" cx="40%" cy="35%" r="74%">
    <stop offset="0" stop-color="#484c55"/><stop offset=".5" stop-color="#31343b"/><stop offset="1" stop-color="#191b1f"/>
  </radialGradient>

  <g id="lug">
    <rect x="-4.5" y="-104" width="9" height="15" rx="3.2" fill="url(#gChromeV)" stroke="rgba(0,0,0,.55)" stroke-width=".8"/>
    <circle cx="0" cy="-96.5" r="1.7" fill="#26282c"/>
  </g>
  <g id="drumcore">
    <ellipse cx="7" cy="11" rx="106" ry="101" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gShellRed)"/><circle r="100" fill="url(#pSparkle)"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.45)" stroke-width="1.4"/>
    <circle r="91" fill="none" stroke="url(#gChrome)" stroke-width="10"/>
    <circle r="86" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.4"/>
    <circle r="85" fill="url(#gMesh)"/><circle r="85" fill="url(#pMesh)"/>
    <ellipse cx="-27" cy="-30" rx="52" ry="40" fill="url(#gSpec)"/>
    <circle r="85" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="2"/>
  </g>
  <g id="s-snare">
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(36)"/><use href="#lug" transform="rotate(72)"/>
    <use href="#lug" transform="rotate(108)"/><use href="#lug" transform="rotate(144)"/><use href="#lug" transform="rotate(180)"/>
    <use href="#lug" transform="rotate(216)"/><use href="#lug" transform="rotate(252)"/><use href="#lug" transform="rotate(288)"/>
    <use href="#lug" transform="rotate(324)"/>
    <circle r="8" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="1.5"/>
  </g>
  <g id="s-tom">
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(60)"/><use href="#lug" transform="rotate(120)"/>
    <use href="#lug" transform="rotate(180)"/><use href="#lug" transform="rotate(240)"/><use href="#lug" transform="rotate(300)"/>
  </g>
  <g id="s-floor">
    <g transform="rotate(28)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <g transform="rotate(148)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <g transform="rotate(268)"><rect x="-5" y="-116" width="10" height="18" rx="3" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/></g>
    <use href="#drumcore"/>
    <use href="#lug"/><use href="#lug" transform="rotate(45)"/><use href="#lug" transform="rotate(90)"/>
    <use href="#lug" transform="rotate(135)"/><use href="#lug" transform="rotate(180)"/><use href="#lug" transform="rotate(225)"/>
    <use href="#lug" transform="rotate(270)"/><use href="#lug" transform="rotate(315)"/>
  </g>
  <g id="s-rim">
    <circle r="98" fill="none" stroke="url(#gShellRed)" stroke-width="4"/>
    <circle r="98" fill="none" stroke="url(#pSparkle)" stroke-width="4"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.45)" stroke-width="1.4"/>
    <circle r="91" fill="none" stroke="url(#gChrome)" stroke-width="10"/>
    <circle r="86" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.4"/>
    <use href="#lug"/><use href="#lug" transform="rotate(36)"/><use href="#lug" transform="rotate(72)"/>
    <use href="#lug" transform="rotate(108)"/><use href="#lug" transform="rotate(144)"/><use href="#lug" transform="rotate(180)"/>
    <use href="#lug" transform="rotate(216)"/><use href="#lug" transform="rotate(252)"/><use href="#lug" transform="rotate(288)"/>
    <use href="#lug" transform="rotate(324)"/>
  </g>
  <g id="s-kick">
    <ellipse cx="8" cy="13" rx="108" ry="103" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gShellRed)"/><circle r="100" fill="url(#pSparkle)"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="1.6"/>
    <circle r="94" fill="none" stroke="url(#gChrome)" stroke-width="7"/>
    <circle r="90" fill="none" stroke="rgba(0,0,0,.55)" stroke-width="1.2"/>
    <circle r="66" fill="url(#gMesh)"/><circle r="66" fill="url(#pMesh)"/>
    <circle r="66" fill="none" stroke="rgba(0,0,0,.6)" stroke-width="2.5"/>
    <ellipse cx="-20" cy="-24" rx="40" ry="32" fill="url(#gSpec)"/>
    <text y="40" text-anchor="middle" font-family="system-ui,sans-serif" font-size="13" font-weight="800" letter-spacing="4" fill="rgba(232,228,216,.5)">STRIKE</text>
  </g>
  <g id="s-cymbal">
    <ellipse cx="7" cy="10" rx="105" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gCym)"/>
    <g fill="none">
      <circle r="94" stroke="rgba(0,0,0,.13)" stroke-width="1.2"/><circle r="86" stroke="rgba(255,246,214,.14)" stroke-width="1.2"/>
      <circle r="78" stroke="rgba(0,0,0,.12)" stroke-width="1.2"/><circle r="70" stroke="rgba(255,246,214,.12)" stroke-width="1.2"/>
      <circle r="62" stroke="rgba(0,0,0,.12)" stroke-width="1.2"/><circle r="54" stroke="rgba(255,246,214,.11)" stroke-width="1.2"/>
      <circle r="46" stroke="rgba(0,0,0,.11)" stroke-width="1.2"/><circle r="38" stroke="rgba(255,246,214,.1)" stroke-width="1.2"/>
      <circle r="31" stroke="rgba(0,0,0,.1)" stroke-width="1.2"/>
    </g>
    <path d="M0 0 L97 -24 A100 100 0 0 0 55 -83 Z" fill="rgba(255,255,255,.12)"/>
    <path d="M0 0 L-97 24 A100 100 0 0 0 -55 83 Z" fill="rgba(255,255,255,.07)"/>
    <path d="M0 0 L24 97 A100 100 0 0 0 83 55 Z" fill="rgba(0,0,0,.08)"/>
    <circle r="26" fill="url(#gBell)"/><circle r="26" fill="none" stroke="rgba(0,0,0,.3)" stroke-width="1.6"/>
    <circle r="6.5" fill="#1a1a1c"/>
    <path d="M0 -5.4 L4.7 -2.7 L4.7 2.7 L0 5.4 L-4.7 2.7 L-4.7 -2.7 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".7"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.4)" stroke-width="1.4"/>
  </g>
  <g id="s-cym-e">
    <ellipse cx="7" cy="10" rx="105" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gCymE)"/>
    <g fill="none">
      <circle r="90" stroke="rgba(255,255,255,.05)" stroke-width="1.2"/><circle r="76" stroke="rgba(0,0,0,.2)" stroke-width="1.2"/>
      <circle r="62" stroke="rgba(255,255,255,.05)" stroke-width="1.2"/><circle r="48" stroke="rgba(0,0,0,.2)" stroke-width="1.2"/>
      <circle r="36" stroke="rgba(255,255,255,.045)" stroke-width="1.2"/>
    </g>
    <circle r="96" fill="none" stroke="rgba(212,175,55,.5)" stroke-width="2"/>
    <path d="M0 0 L97 -24 A100 100 0 0 0 55 -83 Z" fill="rgba(255,255,255,.07)"/>
    <circle r="26" fill="url(#gCymE)"/><circle r="26" fill="none" stroke="rgba(212,175,55,.55)" stroke-width="1.6"/>
    <ellipse cx="-8" cy="-9" rx="13" ry="10" fill="url(#gSpec)"/>
    <circle r="6.5" fill="#101113"/>
    <path d="M0 -5.4 L4.7 -2.7 L4.7 2.7 L0 5.4 L-4.7 2.7 L-4.7 -2.7 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".7"/>
    <circle r="100" fill="none" stroke="rgba(0,0,0,.5)" stroke-width="1.4"/>
  </g>
  <g id="s-bell">
    <ellipse cx="6" cy="9" rx="104" ry="100" fill="url(#gShadow)"/>
    <circle r="100" fill="url(#gBell)"/><circle r="100" fill="none" stroke="rgba(0,0,0,.35)" stroke-width="2.5"/>
    <circle r="72" fill="none" stroke="rgba(0,0,0,.14)" stroke-width="2"/>
    <circle r="46" fill="none" stroke="rgba(255,248,220,.2)" stroke-width="2"/>
    <ellipse cx="-30" cy="-34" rx="42" ry="34" fill="url(#gSpec)"/><ellipse cx="-30" cy="-34" rx="20" ry="15" fill="rgba(255,255,255,.16)"/>
    <circle r="10" fill="#1a1a1c"/>
    <path d="M0 -8 L7 -4 L7 4 L0 8 L-7 4 L-7 -4 Z" fill="url(#gChromeV)" stroke="rgba(0,0,0,.5)" stroke-width=".8"/>
  </g>
  <g id="s-hfoot">
    <ellipse cx="6" cy="10" rx="66" ry="104" fill="url(#gShadow)"/>
    <rect x="-52" y="-96" width="104" height="192" rx="18" fill="#212329" stroke="rgba(0,0,0,.6)" stroke-width="1.5"/>
    <rect x="-52" y="-96" width="104" height="192" rx="18" fill="url(#pMesh)" opacity=".4"/>
    <rect x="-52" y="-92" width="9" height="150" rx="4.5" fill="url(#gChromeV)" opacity=".85"/>
    <rect x="43" y="-92" width="9" height="150" rx="4.5" fill="url(#gChromeV)" opacity=".85"/>
    <path d="M-30 -78 L30 -78 L38 62 L-38 62 Z" fill="url(#gTube)" stroke="rgba(0,0,0,.55)" stroke-width="1.5"/>
    <path d="M-30 -78 L30 -78 L33 -20 L-33 -20 Z" fill="rgba(255,255,255,.14)"/>
    <g stroke="rgba(0,0,0,.4)" stroke-width="2">
      <line x1="-31" y1="-52" x2="31" y2="-52"/><line x1="-32" y1="-26" x2="32" y2="-26"/><line x1="-34" y1="0" x2="34" y2="0"/>
      <line x1="-35" y1="26" x2="35" y2="26"/><line x1="-37" y1="50" x2="37" y2="50"/>
    </g>
    <path d="M-38 62 L38 62 L34 92 L-34 92 Z" fill="#2b2d33" stroke="rgba(0,0,0,.6)" stroke-width="1.5"/>
    <line x1="-38" y1="62" x2="38" y2="62" stroke="rgba(255,255,255,.18)" stroke-width="2"/>
    <rect x="-14" y="-96" width="28" height="14" rx="5" fill="url(#gChromeV)" stroke="rgba(0,0,0,.55)" stroke-width="1"/>
    <circle cy="-89" r="3.2" fill="#26282c"/>
  </g>
</defs>`;

function renderDrumMap() {
  const svgEl = document.getElementById('drum-svg');
  if (!svgEl) return;

  const padMap = {};
  for (const p of pads) padMap[p.id] = p;

  // Which pad IDs are in the currently selected group?
  const groupMembers = new Set();
  if (selectedGroup && PAD_GROUPS[selectedGroup]) {
    for (const pid of PAD_GROUPS[selectedGroup].pads) groupMembers.add(pid);
  }

  const parts = [];
  const overlays = [];   // rim/bell drawn after everything so they sit on top of their drum/ride
  for (const baseDef of PAD_DEFS) {
    const [id, type, cx, cy, rx, ry, lbl] = effectivePadDef(baseDef[0]);
    const p        = padMap[id];
    const hasInstA = p && p.layer_a_path;
    const hasInstB = p && p.layer_b_path;
    const hasInst  = hasInstA || hasInstB;
    const isSel    = selectedMapPad === id;
    const isAssT   = selectedPad && selectedPad.id === id;
    const inGroup  = groupMembers.has(id);

    const isBroken   = p && (brokenPaths.has(p.layer_a_path) || brokenPaths.has(p.layer_b_path));
    const isBatchSel = batchMode && batchSelected.has(id);
    const isOverlay  = (type === 'rim' || type === 'bell');

    const opacity = !pads.length ? 0.5 : (hasInst ? 1.0 : (isOverlay ? 0.62 : 0.34));

    // Sprite placement. Rim/bell register on their parent so the hoop lands on the drum
    // and the bell dome sits at the ride's centre; they also inherit the parent's rotation
    // and finish so a drum + rim (or ride + bell) read as one piece.
    const par = isOverlay ? drumParentOf(id) : null;
    let scx = cx, scy = cy, srx = rx, sry = ry;
    if (par) {
      scx = par[2]; scy = par[3];
      if (type === 'rim') { srx = par[4]; sry = par[5]; }   // hoop matches the drum exactly
    }
    // Rotation + finish live on the base pad (the drum/ride for an overlay).
    const baseOv  = padOverrides[par ? par[0] : id] || {};
    const srot    = +baseOv.rot || 0;
    const finSet  = finishSetFor(type);
    const finFilt = (finSet && baseOv.finish && finSet[baseOv.finish]) ? finSet[baseOv.finish].filter : '';

    const rotTf = srot ? ` rotate(${srot})` : '';
    const tf = (type === 'hfoot')
      ? `translate(${scx},${scy})${rotTf} scale(${(rx/56).toFixed(3)})`
      : `translate(${scx},${scy})${rotTf} scale(${(srx/100).toFixed(3)},${(sry/100).toFixed(3)})`;
    const sprite = `<use href="#s-${type}" transform="${tf}"${finFilt ? ` style="filter:${finFilt}"` : ''}/>`;

    // Selection / assignment-target use a CSS glow (below); group + batch add a footprint ring.
    let ring = '';
    const rrx = (srx + 4).toFixed(1), rry = (sry + 4).toFixed(1);
    const ringRot = srot ? ` transform="rotate(${srot} ${scx} ${scy})"` : '';
    if (isBatchSel) {
      ring = `<ellipse cx="${scx}" cy="${scy}" rx="${rrx}" ry="${rry}" fill="none" stroke="#e0a030" stroke-width="2.4" stroke-dasharray="4,2" pointer-events="none"${ringRot}/>`;
    } else if (inGroup && !isSel && !isAssT) {
      ring = `<ellipse cx="${scx}" cy="${scy}" rx="${rrx}" ry="${rry}" fill="none" stroke="#4a7fd0" stroke-width="1.6" opacity="0.75" pointer-events="none"${ringRot}/>`;
    }

    let glow = '';
    if (isSel)           glow = 'filter:drop-shadow(0 0 6px #f0b32e) drop-shadow(0 0 13px #f0b32e70);';
    else if (isAssT)     glow = 'filter:drop-shadow(0 0 6px #44aaff) drop-shadow(0 0 12px #44aaff70);';
    else if (isBatchSel) glow = 'filter:drop-shadow(0 0 6px #e0a030a0);';

    // Label (base pads only — rim/bell labels are empty in PAD_DEFS)
    let textEl = '';
    if (lbl) {
      const fs = Math.max(7, Math.min(13, ry * 1.2));
      const lblFill = isSel ? '#ffd86a' : (isBatchSel ? '#e0c060' : (inGroup ? '#dde8ff' : '#eef1f6'));
      textEl = `<text x="${cx}" y="${cy + fs * 0.35}" text-anchor="middle" `
        + `font-size="${fs}" fill="${lblFill}" font-family="system-ui,sans-serif" font-weight="700" `
        + `paint-order="stroke" stroke="#000000cc" stroke-width="2.4" stroke-linejoin="round" `
        + `pointer-events="none">${escHtml(lbl)}</text>`;
      // Show assigned instrument name on wider pads
      if (hasInst && rx >= 36) {
        const instrName = p.layer_a_name || p.layer_b_name || '';
        if (instrName) {
          const maxChars = Math.max(4, Math.floor(rx / 5.2));
          const short = instrName.length > maxChars ? instrName.slice(0, maxChars) + '…' : instrName;
          const ifs = Math.max(4.5, Math.min(6.5, ry * 0.6));
          textEl += `<text x="${cx}" y="${cy + fs * 0.35 + ifs * 1.9}" text-anchor="middle" `
            + `font-size="${ifs}" fill="#cdd6e2" paint-order="stroke" stroke="#000000cc" stroke-width="1.8" stroke-linejoin="round" `
            + `font-family="system-ui,sans-serif" pointer-events="none">${escHtml(short)}</text>`;
        }
      }
    }
    // Broken-path warning badge
    const warnEl = isBroken
      ? `<text x="${(scx + srx - 4).toFixed(1)}" y="${(scy - sry + 7).toFixed(1)}" font-size="9" fill="#ff9a3c" `
        + `font-family="system-ui,sans-serif" text-anchor="middle" pointer-events="none">⚠</text>`
      : '';

    // SVG <title> for browser tooltip on hover
    const tipLines = [padMap[id]?.label || id];
    if (p && p.layer_a_name) tipLines.push('A: ' + p.layer_a_name);
    if (p && p.layer_b_name) tipLines.push('B: ' + p.layer_b_name);
    if (isBroken)             tipLines.push('⚠ instrument file not found on this machine');
    if (pads.length && !hasInst) tipLines.push('(empty — click to assign)');
    const titleEl = `<title>${escHtml(tipLines.join('\n'))}</title>`;

    const inner = titleEl + sprite + ring + textEl + warnEl;
    (isOverlay ? overlays : parts).push(
      `<g class="map-pad" data-pid="${id}" style="opacity:${opacity};${glow}" onmousedown="startDrag(event,'${id}')">`
      + inner + `</g>`);

    // Mirror pad: same zone drawn a second time (e.g. dual hi-hats on a Y-splitter)
    const mir = (padOverrides[id] || {}).mirror;
    if (mir) {
      const link = `<text x="${(scx + srx - 6).toFixed(1)}" y="${(scy - sry + 8).toFixed(1)}" font-size="9" `
        + `fill="#7f8a9c" pointer-events="none" font-family="system-ui,sans-serif">&#x29C9;</text>`;
      (isOverlay ? overlays : parts).push(
        `<g class="map-pad" data-pid="${id}" transform="translate(${mir.dx},${mir.dy})" `
        + `style="opacity:${opacity};${glow}" onmousedown="startDrag(event,'${id}',true)">`
        + `<title>${escHtml((padMap[id]?.label || id) + ' (mirror — same zone, shared settings)')}</title>`
        + sprite + ring + textEl + warnEl + link + `</g>`);
    }
  }

  // Direct-manipulation handles on the selected pad (resize + rotate). Edits target the
  // base pad, so grabbing a rim/bell handle actually resizes/rotates its drum/ride.
  let handles = '';
  if (selectedMapPad && !batchMode) {
    const et = editTargetOf(selectedMapPad);
    const d  = effectivePadDef(et);
    if (d) {
      const [, , hcx, hcy, hrx, hry] = d;
      const rot  = +((padOverrides[et] || {}).rot) || 0;
      const rad  = rot * Math.PI / 180;
      // resize grip on the pad's right edge (follows rotation); rotate grip above centre
      const rex = hcx + (hrx + 7) * Math.cos(rad), rey = hcy + (hrx + 7) * Math.sin(rad);
      const rotHandleX = hcx + (hry + 22) * Math.sin(rad), rotHandleY = hcy - (hry + 22) * Math.cos(rad);
      handles =
        `<g class="pad-handle" data-h="rotate" onmousedown="startHandle(event,'${et}','rotate')">`
        + `<line x1="${hcx.toFixed(1)}" y1="${hcy.toFixed(1)}" x2="${rotHandleX.toFixed(1)}" y2="${rotHandleY.toFixed(1)}" stroke="#f0b32e" stroke-width="1.2" opacity=".8"/>`
        + `<circle cx="${rotHandleX.toFixed(1)}" cy="${rotHandleY.toFixed(1)}" r="5" fill="#141519" stroke="#f0b32e" stroke-width="1.6"/>`
        + `<path d="M ${(rotHandleX-2.4).toFixed(1)} ${rotHandleY.toFixed(1)} a 2.4 2.4 0 1 1 1.4 2.1" fill="none" stroke="#f0b32e" stroke-width="1"/>`
        + `</g>`
        + `<g class="pad-handle" data-h="resize" onmousedown="startHandle(event,'${et}','resize')">`
        + `<circle cx="${rex.toFixed(1)}" cy="${rey.toFixed(1)}" r="5" fill="#f0b32e" stroke="#141519" stroke-width="1.4"/>`
        + `<path d="M ${(rex-2.2).toFixed(1)} ${(rey-2.2).toFixed(1)} L ${(rex+2.2).toFixed(1)} ${(rey+2.2).toFixed(1)} M ${(rex+2.2).toFixed(1)} ${(rey-2.2).toFixed(1)} L ${(rex-2.2).toFixed(1)} ${(rey+2.2).toFixed(1)}" stroke="#141519" stroke-width="1.1"/>`
        + `</g>`;
    }
  }

  svgEl.innerHTML = DRUM_MAP_DEFS + parts.join('') + overlays.join('') + handles;
}

// The drum/ride an overlay pad (rim or bell) sits on — its first companion of a base type.
// Used so the rim hoop scales to its drum and the bell dome centres on its ride.
function drumParentOf(id) {
  const drums = new Set(['kick','snare','tom','floor']);
  for (const cid of (PAD_COMPANIONS[id] || [])) {
    const d = effectivePadDef(cid);
    if (!d) continue;
    if (drums.has(d[1]) || d[1] === 'cymbal' || d[1] === 'cym-e') return d;
  }
  return null;
}

// The pad an edit (resize/rotate/finish) should apply to: overlays redirect to their parent.
function editTargetOf(id) {
  const d = effectivePadDef(id);
  if (d && (d[1] === 'rim' || d[1] === 'bell')) {
    const par = drumParentOf(id);
    if (par) return par[0];
  }
  return id;
}

function clickPad(id) {
  if (batchMode) {
    if (batchSelected.has(id)) batchSelected.delete(id);
    else batchSelected.add(id);
    document.getElementById('batch-count').textContent = batchSelected.size + ' pad' + (batchSelected.size !== 1 ? 's' : '') + ' selected';
    renderDrumMap();
    return;
  }
  selectedMapPad = id;
  selectedGroup  = PAD_TO_GROUP[id] || null;
  // Auto-target this pad for assignment (keep current layer if re-clicking same pad)
  if (!selectedPad || selectedPad.id !== id) {
    selectedPad = {id, layer: 'a'};
  }
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  renderInstruments();  // refresh "current" highlight in browser
}

// ── Velocity xfade interactive control ───────────────────────────────────────
let _velDrag = null;

function velXfadeControl(padId, xfade, laLevel, lbLevel) {
  const W = 176, H = 48, pad = 4;
  const aCol = '#4a90d9', bCol = '#e06040';
  const xPx  = v => pad + (v / 127) * (W - pad * 2);
  const splitX = xfade === 0 ? W - pad : xPx(xfade);
  const maxH = H - 16;
  const aH = Math.max(3, (laLevel / 127) * maxH);
  const bH = Math.max(3, (lbLevel / 127) * maxH);
  const aY = H - 14 - aH, bY = H - 14 - bH;
  const bW = Math.max(0, W - pad - splitX);
  const eid = 'vx_' + padId.replace(/\W/g,'_');

  const splitViz = xfade > 0 ? `
    <line id="${eid}_spl" x1="${splitX}" y1="0" x2="${splitX}" y2="${H-14}" stroke="#aaa" stroke-width="1.5" stroke-dasharray="3,2"/>
    <rect id="${eid}_hdl" x="${splitX-5}" y="0" width="10" height="${H-14}" fill="transparent" style="cursor:ew-resize"/>
    <text id="${eid}_lbl" x="${splitX}" y="${H-3}" text-anchor="middle" font-size="8" fill="#aaa">${xfade}</text>` : `
    <text id="${eid}_lbl" x="${W/2}" y="${H-3}" text-anchor="middle" font-size="8" fill="#445">A only (drag to enable B)</text>`;

  return `<svg id="${eid}" class="vel-xfade-svg" width="${W}" height="${H}"
      data-pid="${escHtml(padId)}" onmousedown="startVelDrag(event)"
      style="display:block;flex-shrink:0;cursor:ew-resize;user-select:none;" xmlns="http://www.w3.org/2000/svg">
    <rect x="${pad}" y="0" width="${W - pad*2}" height="${H-14}" fill="#0a1520" rx="2"/>
    <rect id="${eid}_abar" x="${pad}" y="${aY}" width="${Math.max(0, splitX - pad)}" height="${aH}" fill="${aCol}" opacity="0.75" rx="1"/>
    <rect id="${eid}_bbar" x="${splitX}" y="${bY}" width="${bW}" height="${bH}" fill="${bCol}" opacity="${xfade===0?'0':'0.75'}" rx="1"/>
    ${splitViz}
    <text x="${pad+3}" y="${H-3}" font-size="8" fill="${aCol}">A</text>
    <text x="${W-pad-2}" y="${H-3}" text-anchor="end" font-size="8" fill="${xfade===0?'#334':bCol}">B</text>
  </svg>`;
}

function startVelDrag(e) {
  e.preventDefault();
  const svg = e.currentTarget;
  _velDrag = {padId: svg.dataset.pid, svg, rect: svg.getBoundingClientRect(), lastVel: null};
  _applyVelDrag(e.clientX);
}

function _applyVelDrag(clientX) {
  if (!_velDrag) return;
  const {svg, rect, padId} = _velDrag;
  const W = svg.viewBox?.baseVal?.width || svg.getBoundingClientRect().width;
  const pad = 4;
  const x = Math.max(pad, Math.min(W - pad, clientX - rect.left));
  const vel = Math.round((x - pad) / (W - pad * 2) * 127);
  const eid = 'vx_' + padId.replace(/\W/g,'_');
  const aCol = '#4a90d9', bCol = '#e06040';
  const aBar = document.getElementById(eid + '_abar');
  const bBar = document.getElementById(eid + '_bbar');
  const spl  = document.getElementById(eid + '_spl');
  const hdl  = document.getElementById(eid + '_hdl');
  const lbl  = document.getElementById(eid + '_lbl');
  if (aBar) aBar.setAttribute('width', Math.max(0, x - pad));
  if (bBar) { bBar.setAttribute('x', x); bBar.setAttribute('width', Math.max(0, W - pad - x)); bBar.setAttribute('opacity', vel === 0 ? '0' : '0.75'); }
  if (spl)  { spl.setAttribute('x1', x); spl.setAttribute('x2', x); }
  if (hdl)  hdl.setAttribute('x', x - 5);
  if (lbl)  { lbl.setAttribute('x', x); lbl.textContent = vel === 0 ? 'A only' : vel; }
  _velDrag.lastVel = vel;
}

// ── Pad detail helpers ────────────────────────────────────────────────────────
function midiNoteSelect(pid, val) {
  let opts = '';
  for (let i = 0; i <= 127; i++) {
    const lbl = GM_DRUMS_JS[i] ? `${i} – ${GM_DRUMS_JS[i]}` : String(i);
    opts += `<option value="${i}"${i===val?' selected':''}>${escHtml(lbl)}</option>`;
  }
  return `<select class="midi-select" onchange="setParam('${pid}','midi_note',+this.value)">${opts}</select>`;
}
function paramSlider(pid, param, val, lo, hi, disabled) {
  const dis = disabled ? ' disabled style="opacity:0.35;"' : '';
  return `<div class="param-slider-wrap">`
    + `<input type="range" min="${lo}" max="${hi}" value="${Math.min(hi,Math.max(lo,val))}"${dis} `
    + `oninput="this.nextElementSibling.textContent=this.value" `
    + `onchange="setParam('${pid}','${param}',+this.value)">`
    + `<span class="param-val"${dis}>${val}</span>`
    + `</div>`;
}

// ── Pad detail panel ──────────────────────────────────────────────────────────
function renderPadDetail() {
  const el = document.getElementById('pad-detail');
  if (!el) return;

  if (!selectedGroup || !pads.length) {
    el.innerHTML = '<div class="det-empty">Click a pad or jack to view and edit</div>';
    return;
  }

  const group = PAD_GROUPS[selectedGroup];
  if (!group) { el.innerHTML = ''; return; }

  const groupPads = group.pads.map(id => pads.find(p => p.id === id)).filter(Boolean);
  if (!groupPads.length) { el.innerHTML = ''; return; }

  // Primary pad = active assignment target (or first in group)
  const primary = groupPads.find(p => selectedPad && p.id === selectedPad.id) || groupPads[0];

  // Zone rows (one per pad in the group)
  const zoneHtml = groupPads.map(p => {
    const isSel    = selectedPad && selectedPad.id === p.id;
    const curLayer = isSel ? selectedPad.layer : null;
    const btnA     = `layer-btn${curLayer==='a' ? ' active-layer' : ''}`;
    const btnB     = `layer-btn${curLayer==='b' ? ' active-layer' : ''}`;
    const warnA    = p.layer_a_path && brokenPaths.has(p.layer_a_path) ? ' <span title="File not found on this machine" style="color:#e08020;font-size:.7rem;">⚠</span>' : '';
    const warnB    = p.layer_b_path && brokenPaths.has(p.layer_b_path) ? ' <span title="File not found on this machine" style="color:#e08020;font-size:.7rem;">⚠</span>' : '';
    return `<div class="det-zone${isSel ? ' zone-sel' : ''}">
      <div class="det-zone-id">${escHtml(p.id)}<span class="zlbl">${escHtml(p.label)}</span></div>
      <div class="det-layer">
        <span class="pill">A</span>
        <span class="name" title="${escHtml(p.layer_a_path||'')}">${escHtml(p.layer_a_name||'—')}${warnA}</span>
        <button class="${btnA}" onclick="selectPadLayer('${p.id}','a')">assign</button>
        ${p.layer_a_path ? `<button class="layer-btn" title="Edit instrument parameters" onclick="openSinEditor('${p.layer_a_path}')">&#9881;</button>` : ''}
        ${p.layer_a_path ? `<button class="layer-btn" title="Find similar-sounding instruments" onclick="openSimilar('${p.layer_a_path}')">&#8776;</button>` : ''}
        ${p.layer_a_path ? `<button class="layer-btn clear" onclick="clearLayer('${p.id}','a')">&#x2715;</button>` : ''}
      </div>
      <div class="det-layer">
        <span class="pill">B</span>
        <span class="name" title="${escHtml(p.layer_b_path||'')}">${escHtml(p.layer_b_name||'—')}${warnB}</span>
        <button class="${btnB}" onclick="selectPadLayer('${p.id}','b')">assign</button>
        ${p.layer_b_path ? `<button class="layer-btn" title="Edit instrument parameters" onclick="openSinEditor('${p.layer_b_path}')">&#9881;</button>` : ''}
        ${p.layer_b_path ? `<button class="layer-btn" title="Find similar-sounding instruments" onclick="openSimilar('${p.layer_b_path}')">&#8776;</button>` : ''}
        ${p.layer_b_path ? `<button class="layer-btn clear" onclick="clearLayer('${p.id}','b')">&#x2715;</button>` : ''}
      </div>
    </div>`;
  }).join('');

  // Params section — for the primary (active) zone
  const hasBLayer = !!primary.layer_b_path;
  const paramsHtml = `<div class="det-params">
    <div class="param-row">
      <span class="param-lbl" title="MIDI note sent when pad is hit">MIDI note</span>
      ${midiNoteSelect(primary.id, primary.midi_note)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer A level</span>
      ${paramSlider(primary.id, 'la_level', primary.la_level, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer A pan</span>
      ${paramSlider(primary.id, 'la_pan', primary.la_pan, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A pitch shift in semitones (-12 to +12)">Layer A pitch</span>
      ${paramSlider(primary.id, 'la_pitch', primary.la_pitch, -12, 12)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A fine pitch -50 to +50 cents">A fine pitch</span>
      ${paramSlider(primary.id, 'la_fine', primary.la_fine, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A decay (0=short, 99=long natural tail)">Layer A decay</span>
      ${paramSlider(primary.id, 'la_decay', primary.la_decay, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Volume sensitivity for Layer A">A vel→vol</span>
      ${paramSlider(primary.id, 'la_vel_vol', primary.la_vel_vol, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Decay for Layer A">A vel→dec</span>
      ${paramSlider(primary.id, 'la_vel_dec', primary.la_vel_dec, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Pitch for Layer A">A vel→pch</span>
      ${paramSlider(primary.id, 'la_vel_pch', primary.la_vel_pch, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Filter for Layer A">A vel→flt</span>
      ${paramSlider(primary.id, 'la_vel_flt', primary.la_vel_flt, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A filter: enable and cutoff frequency">Layer A filter</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:52px;" onchange="setParam('${primary.id}','la_fflag',+this.value)">
          <option value="0"${primary.la_fflag===0?' selected':''}>Off</option>
          <option value="1"${primary.la_fflag===1?' selected':''}>On</option>
        </select>
        ${paramSlider(primary.id, 'la_fcut', primary.la_fcut, 0, 99, !primary.la_fflag)}
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A loop mode — plays sample continuously while held">A loop</span>
      <select class="midi-select" style="width:72px;" onchange="setParam('${primary.id}','la_loop',+this.value)">
        <option value="0"${primary.la_loop===0?' selected':''}>Off</option>
        <option value="1"${primary.la_loop===1?' selected':''}>Loop On</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A velocity range minimum — layer plays at or above this velocity">A vel min</span>
      ${paramSlider(primary.id, 'la_vel_min', primary.la_vel_min, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer A velocity range maximum — layer plays at or below this velocity">A vel max</span>
      ${paramSlider(primary.id, 'la_vel_max', primary.la_vel_max, 0, 127)}
    </div>
    ${hasBLayer ? `
    <div class="param-row">
      <span class="param-lbl">Layer B level</span>
      ${paramSlider(primary.id, 'lb_level', primary.lb_level, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl">Layer B pan</span>
      ${paramSlider(primary.id, 'lb_pan', primary.lb_pan, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B pitch shift in semitones (-12 to +12)">Layer B pitch</span>
      ${paramSlider(primary.id, 'lb_pitch', primary.lb_pitch, -12, 12)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B fine pitch -50 to +50 cents">B fine pitch</span>
      ${paramSlider(primary.id, 'lb_fine', primary.lb_fine, -50, 50)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B decay (0=short, 99=long natural tail)">Layer B decay</span>
      ${paramSlider(primary.id, 'lb_decay', primary.lb_decay, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Volume sensitivity for Layer B">B vel→vol</span>
      ${paramSlider(primary.id, 'lb_vel_vol', primary.lb_vel_vol, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Decay for Layer B">B vel→dec</span>
      ${paramSlider(primary.id, 'lb_vel_dec', primary.lb_vel_dec, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Pitch for Layer B">B vel→pch</span>
      ${paramSlider(primary.id, 'lb_vel_pch', primary.lb_vel_pch, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Velocity → Filter for Layer B">B vel→flt</span>
      ${paramSlider(primary.id, 'lb_vel_flt', primary.lb_vel_flt, 0, 127)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B filter: enable and cutoff frequency">Layer B filter</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:52px;" onchange="setParam('${primary.id}','lb_fflag',+this.value)">
          <option value="0"${primary.lb_fflag===0?' selected':''}>Off</option>
          <option value="1"${primary.lb_fflag===1?' selected':''}>On</option>
        </select>
        ${paramSlider(primary.id, 'lb_fcut', primary.lb_fcut, 0, 99, !primary.lb_fflag)}
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Layer B loop mode — plays sample continuously while held">B loop</span>
      <select class="midi-select" style="width:72px;" onchange="setParam('${primary.id}','lb_loop',+this.value)">
        <option value="0"${primary.lb_loop===0?' selected':''}>Off</option>
        <option value="1"${primary.lb_loop===1?' selected':''}>Loop On</option>
      </select>
    </div>
    <div class="param-row" style="align-items:flex-start;">
      <span class="param-lbl" style="padding-top:3px;" title="Velocity at which Layer B starts playing (0 = both layers always active)">Vel. xfade</span>
      ${velXfadeControl(primary.id, primary.xfade_vel, primary.la_level, primary.lb_level)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Play Layer A and B simultaneously at their current levels">Blend preview</span>
      <button class="btn-secondary" style="font-size:.68rem;padding:3px 9px;"
        onclick="previewBlend('${primary.id}')">&#9654; A+B</button>
    </div>` : ''}
    <div class="param-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2a3e;">
      <span class="param-lbl" style="font-weight:600;color:#7ab3ef;font-size:.7rem;">FX / Zone</span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Reverb send level (0=dry, 99=max)">Reverb</span>
      ${paramSlider(primary.id, 'reverb', primary.reverb, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="FX1 send level (0–99)">FX1</span>
      ${paramSlider(primary.id, 'fx1', primary.fx1, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="FX2 send level (0–99)">FX2</span>
      ${paramSlider(primary.id, 'fx2', primary.fx2, 0, 99)}
    </div>
    <div class="param-row">
      <span class="param-lbl" title="EQ/Comp enable">EQ/Comp</span>
      <select class="midi-select" onchange="setParam('${primary.id}','eq_comp',+this.value)">
        <option value="0"${primary.eq_comp===0?' selected':''}>Off</option>
        <option value="1"${primary.eq_comp===1?' selected':''}>On</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Playback mode: Poly allows multiple simultaneous hits, Mono stops previous">Play mode</span>
      <select class="midi-select" onchange="setParam('${primary.id}','play_mode',+this.value)">
        <option value="1"${primary.play_mode===1?' selected':''}>Poly</option>
        <option value="0"${primary.play_mode===0?' selected':''}>Mono</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Playback priority when voices are stolen">Priority</span>
      <select class="midi-select" onchange="setParam('${primary.id}','priority',+this.value)">
        <option value="0"${primary.priority===0?' selected':''}>Low</option>
        <option value="1"${primary.priority===1?' selected':''}>Med</option>
        <option value="2"${primary.priority===2?' selected':''}>High</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Note Off behaviour">Note Off</span>
      <select class="midi-select" onchange="setParam('${primary.id}','note_off',+this.value)">
        <option value="0"${primary.note_off===0?' selected':''}>Sent</option>
        <option value="1"${primary.note_off===1?' selected':''}>None</option>
        <option value="2"${primary.note_off===2?' selected':''}>Alt</option>
      </select>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="Duration of the MIDI note sent when struck: Free = fixed length in ms, Sync = tempo-synced, OFF = no gate">Gate time</span>
      <span style="display:flex;align-items:center;gap:6px;flex:1;">
        <select class="midi-select" style="width:96px;" onchange="setGateMode('${primary.id}',this.value)">
          <option value="free"${primary.gate_time<=99?' selected':''}>Free</option>
          ${GATE_SYNC.map((n,i)=>`<option value="${100+i}"${primary.gate_time===100+i?' selected':''}>${n}</option>`).join('')}
          <option value="255"${primary.gate_time===255?' selected':''}>OFF</option>
        </select>
        <input type="number" min="0" max="99" value="${primary.gate_time<=99?primary.gate_time:0}"
          ${primary.gate_time<=99?'':'disabled style="opacity:0.35;"'}
          class="midi-select" style="width:52px;" title="Gate length in ms (Free mode)"
          onchange="setParam('${primary.id}','gate_time',Math.min(99,Math.max(0,+this.value)))"> ms
      </span>
    </div>
    <div class="param-row">
      <span class="param-lbl" title="MIDI output channel (1–16)">MIDI chan</span>
      <select class="midi-select" onchange="setParam('${primary.id}','midi_chan',+this.value)">
        ${Array.from({length:16},(_,i)=>`<option value="${i+1}"${primary.midi_chan===i+1?' selected':''}>${i+1}</option>`).join('')}
      </select>
    </div>
    <div class="param-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2a3e;">
      <span class="param-lbl" title="Mute Group: pads in the same group silence each other (e.g. open/closed hi-hat)">Mute group</span>
      <select class="midi-select" onchange="setParam('${primary.id}','mute_grp',+this.value)">
        <option value="0"${primary.mute_grp===0?' selected':''}>Off</option>
        ${[1,2,3,4,5,6,7,8,9].map(n=>`<option value="${n}"${primary.mute_grp===n?' selected':''}>${n}</option>`).join('')}
      </select>
    </div>
  </div>`;

  // Customize section — shape/label edit the zone; size/rotation/finish edit the base pad
  // (an overlay rim/bell redirects to its drum/ride so they stay a single piece).
  const effDef   = effectivePadDef(primary.id);
  const effType  = effDef ? effDef[1] : 'tom';
  const effLbl   = effDef ? effDef[6] : '';
  const hasOv    = padOverrides[primary.id] && Object.keys(padOverrides[primary.id]).length > 0;
  const typeOpts = ['kick','snare','rim','tom','floor','cymbal','cym-e','bell','hfoot']
    .map(t => `<option value="${t}"${t===effType?' selected':''}>${t}</option>`).join('');

  const editId   = editTargetOf(primary.id);
  const editDef  = effectivePadDef(editId);
  const editType = editDef ? editDef[1] : effType;
  const defSize  = PAD_TYPE_SIZES[editType] || [editDef ? editDef[4] : 40, editDef ? editDef[5] : 15];
  const curScale = editDef ? (editDef[4] / defSize[0]) : 1;
  const curRot   = +((padOverrides[editId] || {}).rot) || 0;
  const finSet   = finishSetFor(editType);
  const curFin   = (padOverrides[editId] || {}).finish || (finSet ? Object.keys(finSet)[0] : '');
  const finishRow = finSet ? `<div class="finish-row">${Object.entries(finSet).map(([k, f]) =>
    `<button class="fin-sw${k === curFin ? ' on' : ''}" title="${f.name}" style="background:${f.swatch}" `
    + `onclick="setPadShape('${editId}','finish','${k}',true)"></button>`).join('')}</div>` : '';

  const custHtml = `<details class="det-customize">
    <summary>&#9654; Customize on map (${escHtml(primary.id)})</summary>
    <div class="cust-grid">
      <span>Label</span>
      <input type="text" maxlength="6" value="${escHtml(effLbl)}"
        onchange="setPadOverride('${primary.id}','lbl',this.value.trim())">
      <span>Shape</span>
      <select onchange="setPadOverride('${primary.id}','type',this.value)">${typeOpts}</select>
      <span>Size</span>
      <span class="cust-slider">
        <input type="range" min="0.4" max="2.2" step="0.05" value="${curScale.toFixed(2)}"
          oninput="setPadSize('${editId}',+this.value);document.getElementById('cust-size-val').textContent=Math.round(this.value*100)+'%'">
        <span id="cust-size-val">${Math.round(curScale * 100)}%</span>
      </span>
      <span>Rotation</span>
      <span class="cust-slider">
        <input type="range" min="-180" max="180" step="1" value="${curRot}"
          oninput="setPadShape('${editId}','rot',+this.value);document.getElementById('cust-rot-val').textContent=this.value+'°'">
        <span id="cust-rot-val">${curRot}°</span>
      </span>
    </div>
    ${finSet ? `<div class="cust-fin-lbl">Finish</div>${finishRow}` : ''}
    <button class="btn-secondary" style="margin-top:8px;width:100%;font-size:.72rem;padding:4px;"
      title="Draw this zone a second time on the map — for Y-splitters / doubled triggers (same settings, same sounds)"
      onclick="toggleMirrorPad('${primary.id}')">${(padOverrides[primary.id]||{}).mirror ? '&#x2715; Remove mirror pad' : '&#x29C9; Add mirror pad'}</button>
    ${hasOv ? `<button class="btn-secondary" style="margin-top:6px;width:100%;font-size:.72rem;padding:4px;"
        onclick="resetPadOverride('${primary.id}')">&#x21BA; Reset to default</button>` : ''}
    <div class="cust-hint">Tip: select a pad on the map to drag it, or use the gold handles to resize &amp; rotate.</div>
  </details>`;

  const otherPads = pads.filter(p => p.id !== primary.id);
  const copyHtml  = otherPads.length ? `<div class="copy-pad-row">
    <label>Copy to:</label>
    <select id="copy-pad-target">${otherPads.map(p =>
      `<option value="${p.id}">${escHtml(p.id)} — ${escHtml(p.label)}</option>`).join('')}</select>
    <button class="btn-secondary" style="font-size:.7rem;padding:3px 8px;white-space:nowrap;"
      onclick="copyPad('${primary.id}', document.getElementById('copy-pad-target').value)">Copy</button>
  </div>
  <div class="copy-pad-row">
    <label>Swap with:</label>
    <select id="swap-pad-target">${otherPads.map(p =>
      `<option value="${p.id}">${escHtml(p.id)} — ${escHtml(p.label)}</option>`).join('')}</select>
    <button class="btn-secondary" style="font-size:.7rem;padding:3px 8px;white-space:nowrap;"
      onclick="swapPad('${primary.id}', document.getElementById('swap-pad-target').value)">Swap</button>
  </div>` : '';

  const hexHtml = `<div style="margin-top:8px;padding-top:6px;border-top:1px solid #2a2a3e;">
    <button class="btn-secondary" style="font-size:.68rem;padding:3px 8px;"
      onclick="hexInspect('${primary.id}')">&#x1F50D; Inspect bytes</button>
    <pre id="hex-output-${primary.id}" class="hex-output" style="display:none;"></pre>
  </div>`;

  el.innerHTML = `<div class="det-card">
    <div class="det-hdr">
      <span class="det-id">${escHtml(group.label)}</span>
      <span class="det-input" title="Physical input">${escHtml(group.jackLabel)}</span>
    </div>
    ${zoneHtml}${paramsHtml}${custHtml}${copyHtml}${hexHtml}
  </div>`;
}

// ── Assignment flow ───────────────────────────────────────────────────────────
function selectPadLayer(padId, layer) {
  selectedPad    = {id: padId, layer};
  selectedMapPad = padId;
  selectedGroup  = PAD_TO_GROUP[padId] || selectedGroup;
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  renderInstruments();  // refresh "current" highlight in browser
  setMsg(`Click an instrument to assign to ${padId} Layer ${layer.toUpperCase()}`);
}

function clearSelection() {
  selectedPad    = null;
  selectedGroup  = null;
  selectedMapPad = null;
  updateAssignBanner();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
}

function updateAssignBanner() {
  postSelect();
  const el = document.getElementById('assign-target');
  if (!el) return;
  if (selectedPad) {
    const p     = pads.find(p => p.id === selectedPad.id);
    const label = p ? p.label : selectedPad.id;
    el.className = 'assign-target';
    el.innerHTML = `<strong>${escHtml(selectedPad.id)}</strong> ${escHtml(label)}`
      + ` &ndash; Layer ${selectedPad.layer.toUpperCase()}`
      + ` <span class="clr" onclick="clearSelection()" title="Cancel">&#xD7;</span>`;
  } else {
    el.className = 'assign-target empty';
    el.textContent = 'Click a pad or jack above to assign instruments';
  }
}

async function clearLayer(padId, layer) {
  const data = await api('/clear', {pad_id: padId, layer});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// Gate time (off 53): 0–99 = Free ms, 100–109 = sync divisions, 255 = OFF
const GATE_SYNC = ['Sync:1/32','Sync:1/32T','Sync:1/16','Sync:1/16T',
                   'Sync:1/8','Sync:1/8T','Sync:1/4','Sync:1/4T','Sync:1/2','Sync:1/2T'];

function setGateMode(padId, v) {
  // 'free' → keep/restore a ms value; numeric strings are sync LUT values or 255
  setParam(padId, 'gate_time', v === 'free' ? 0 : +v);
}

async function setParam(padId, param, value) {
  if (isNaN(value)) return;
  const data = await api('/set_param', {pad_id: padId, param, value});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPadDetail();
  setMsg(data.message);
}

// ── Tags ──────────────────────────────────────────────────────────────────────
async function loadTags() {
  const data = await fetch('/api/tags').then(r => r.json()).catch(() => ({tags:{}}));
  instTags = data.tags || {};
  renderTagChips();
}

function renderTagChips() {
  const row = document.getElementById('tag-chips-row');
  if (!row) return;
  const allTags = new Set();
  for (const tags of Object.values(instTags)) tags.forEach(t => allTags.add(t));
  if (!allTags.size) { row.innerHTML = ''; return; }
  const sorted = [...allTags].sort();
  row.innerHTML = `<span class="tag-chip all-chip${!activeTagFilter ? ' active' : ''}" onclick="setTagFilter(null)">All</span>`
    + sorted.map(t => `<span class="tag-chip${activeTagFilter===t?' active':''}" onclick="setTagFilter('${escHtml(t)}')">${escHtml(t)}</span>`).join('');
}

function setTagFilter(tag) {
  activeTagFilter = (activeTagFilter === tag) ? null : tag;
  renderTagChips();
  renderInstruments();
}

async function saveInstrumentTags(sinRel, tags) {
  const data = await api('/set_tags', {sin_rel: sinRel, tags});
  if (data.error) { setMsg(data.error, true); return; }
  instTags = data.tags || {};
  renderTagChips();
  renderInstruments();
}

function editTagsInline(sinRel, triggerEl) {
  const current = (instTags[sinRel] || []).join(', ');
  const inp = document.createElement('input');
  inp.type = 'text'; inp.className = 'inst-tag-edit'; inp.value = current;
  inp.placeholder = 'tag1, tag2…'; inp.title = 'Comma-separated tags. Enter to save, Esc to cancel.';
  const finish = (save) => {
    if (save) {
      const tags = inp.value.split(',').map(t => t.trim()).filter(Boolean);
      saveInstrumentTags(sinRel, tags);
    } else {
      renderInstruments();
    }
  };
  inp.onkeydown = e => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    e.stopPropagation();
  };
  inp.onblur = () => finish(true);
  triggerEl.parentNode.replaceChild(inp, triggerEl);
  inp.focus(); inp.select();
}

// ── Instrument browser ────────────────────────────────────────────────────────
async function loadInstruments() {
  const data = await api('/instruments');
  avail       = data.instruments;
  instMtimes  = data.mtimes || {};
  renderInstruments();
}

function toggleCat(cat) {
  if (expandedCats.has(cat)) expandedCats.delete(cat);
  else expandedCats.add(cat);
  renderInstruments();
}

function renderInstItem(rel, inUse, currentPath) {
  const name      = rel.split('/').slice(1).join('/').replace(/\.sin$/i, '');
  const users     = inUse[rel] || [];
  const isCurr    = rel === currentPath;
  const isPlaying = previewRel === rel;
  const isStar    = favorites.has(rel);
  const tags      = instTags[rel] || [];

  let badge = '';
  if (users.length) {
    const isMine = users.some(u => selectedPad && u.id === selectedPad.id);
    const tip    = 'Used by: ' + users.map(u => `${u.id} Lyr ${u.layer}`).join(', ');
    const cls    = isMine ? 'in-use-badge mine' : 'in-use-badge';
    const lbl    = users.length === 1 ? users[0].id : `\xD7${users.length}`;
    badge = `<span class="${cls}" title="${escHtml(tip)}">${escHtml(lbl)}</span>`;
  }
  const waveId  = 'wv-' + rel.replace(/[^a-zA-Z0-9]/g, '_');
  const waveCanvas = `<canvas class="waveform-canvas" id="${escHtml(waveId)}" width="60" height="18"
    data-sin="${escHtml(rel)}" title="Waveform"></canvas>`;
  const playBtn = `<button class="play-btn${isPlaying ? ' playing' : ''}" `
    + `data-rel="${escHtml(rel)}" `
    + `onclick="event.stopPropagation();previewInstrument('${rel}')" `
    + `title="${isPlaying ? 'Stop' : 'Preview'}">${isPlaying ? '&#9632;' : '&#9654;'}</button>`;
  const starBtn = `<button class="star-btn${isStar ? ' starred' : ''}" `
    + `onclick="event.stopPropagation();toggleFavorite('${rel}')" `
    + `title="${isStar ? 'Unstar' : 'Star'}">&#9733;</button>`;
  const abBtns = `<span class="ab-btns">
    <button class="ab-btn" onclick="event.stopPropagation();directAssign('${rel}','a')" title="Layer A">A</button>
    <button class="ab-btn" onclick="event.stopPropagation();directAssign('${rel}','b')" title="Layer B">B</button>
  </span>`;
  const tagHtml = tags.length
    ? tags.map(t => `<span class="inst-tag" onclick="event.stopPropagation();setTagFilter('${escHtml(t)}')" title="Filter by: ${escHtml(t)}">${escHtml(t)}</span>`).join('')
    : '';
  const editTagBtn = `<span class="inst-tag" style="opacity:.4;" title="Edit tags" onclick="event.stopPropagation();editTagsInline('${rel}',this)">&#9998;</span>`;
  const sinEditBtn = `<span class="inst-tag" style="opacity:.4;" title="Edit instrument parameters" onclick="event.stopPropagation();openSinEditor('${rel}')">&#9881;</span>`;
  const simBtn = `<span class="inst-tag" style="opacity:.4;" title="Find similar-sounding instruments" onclick="event.stopPropagation();openSimilar('${rel}')">&#8776;</span>`;
  const currStyle = isCurr ? ' style="background:#0a2218;border-left:2px solid #3a9060;"' : '';
  const hoverEvt  = hoverPreview
    ? ` onmouseenter="previewInstrument('${rel}')" onmouseleave="if(previewRel==='${rel}')stopPreview()"` : '';
  return `<div class="inst-item" onclick="assignInstrument('${rel}')" title="${escHtml(rel)}"${currStyle}${hoverEvt}>
    ${playBtn}${starBtn}<span class="iname">${escHtml(name)}</span>${badge}${waveCanvas}${tagHtml}${editTagBtn}${sinEditBtn}${simBtn}${abBtns}
  </div>`;
}

function renderInstruments() {
  const query     = document.getElementById('inst-search').value.toLowerCase();
  const el        = document.getElementById('inst-list');
  const searching = query.length > 0;
  const inUse     = buildInUseMap();

  let currentPath = null;
  if (selectedPad) {
    const sp = pads.find(p => p.id === selectedPad.id);
    if (sp) currentPath = selectedPad.layer === 'a' ? sp.layer_a_path : sp.layer_b_path;
  }

  const matchesFilters = r => {
    if (query && !r.toLowerCase().includes(query) && !(instTags[r] || []).some(t => t.toLowerCase().includes(query))) return false;
    if (activeTagFilter && !(instTags[r] || []).includes(activeTagFilter)) return false;
    return true;
  };

  // Starred section (filtered by search + tag when active)
  const starredRels = [...favorites].filter(r => avail[r] && matchesFilters(r));
  let starredHtml = '';
  if (starredRels.length) {
    starredHtml = `<div class="sect-hdr" style="border-left:2px solid #e8b820;">&#9733; Starred</div>`
      + starredRels.map(r => renderInstItem(r, inUse, currentPath)).join('');
  }

  // Recent section (hidden while searching/filtering)
  const recentRels = recentInst.filter(r => avail[r] && matchesFilters(r)).slice(0, 10);
  let recentHtml = '';
  if (recentRels.length && !searching) {
    recentHtml = `<div class="sect-hdr" style="border-left:2px solid #5a9aaa;">&#x23F0; Recent`
      + `<button class="layer-btn" style="margin-left:auto;font-size:.6rem;padding:1px 5px;" onclick="clearRecent()">Clear</button></div>`
      + recentRels.map(r => renderInstItem(r, inUse, currentPath)).join('');
  }

  // Categories
  const cats = {};
  for (const rel of Object.keys(avail)) {
    if (!matchesFilters(rel)) continue;
    const cat = rel.split('/')[0];
    if (!cats[cat]) cats[cat] = [];
    cats[cat].push(rel);
  }

  if (!Object.keys(cats).length && !starredRels.length) {
    el.innerHTML = '<p style="color:#666;font-size:.8rem;padding:8px">No instruments found.</p>';
    return;
  }

  // Use-count map for "most used" sort
  const useCount = {};
  for (const p of pads) {
    if (p.layer_a_path) useCount[p.layer_a_path] = (useCount[p.layer_a_path] || 0) + 1;
    if (p.layer_b_path) useCount[p.layer_b_path] = (useCount[p.layer_b_path] || 0) + 1;
  }

  const catsHtml = Object.keys(cats).sort().map(cat => {
    let items = cats[cat].slice();
    if (instSort === 'used') {
      items.sort((a, b) => (useCount[b] || 0) - (useCount[a] || 0) || a.localeCompare(b));
    } else if (instSort === 'recent') {
      items.sort((a, b) => (instMtimes[b] || 0) - (instMtimes[a] || 0));
    } else {
      items.sort((a, b) => a.localeCompare(b));
    }
    const collapsed = !searching && !expandedCats.has(cat);
    const arrow     = collapsed ? '&#9654;' : '&#9660;';
    const color     = catColor(cat);
    return `<div class="cat-header" style="border-left:2px solid ${color}" onclick="toggleCat('${escHtml(cat)}')">
        <span class="cat-arrow">${arrow}</span>${escHtml(cat)}
        <span class="cat-count">${items.length}</span>
      </div>
      <div class="cat-items" style="display:${collapsed?'none':'block'}">${items.map(r => renderInstItem(r, inUse, currentPath)).join('')}</div>`;
  }).join('');

  el.innerHTML = starredHtml + recentHtml + catsHtml;
  attachWaveObservers();
}

async function directAssign(sinRel, layer) {
  if (!selectedPad) {
    setMsg('Click a pad on the map first to target it.', true);
    return;
  }
  await assignInstrument(sinRel, selectedPad.id, layer);
}

async function assignInstrument(sinRel, forcePadId, forceLayer) {
  const target = (forcePadId && forceLayer) ? {id: forcePadId, layer: forceLayer} : selectedPad;
  if (!target) {
    setMsg('Click a pad on the map first, then pick an instrument.', true);
    return;
  }
  const data = await api('/assign', {pad_id: target.id, layer: target.layer, sin_rel: sinRel});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  addToRecent(sinRel);
  if (autoPreview) previewInstrument(sinRel);
  // Advance to Layer B if A was just filled and B is empty
  if (!forcePadId && target.layer === 'a') {
    const updated = pads.find(p => p.id === target.id);
    if (updated && !updated.layer_b_path) {
      selectedPad = {id: target.id, layer: 'b'};
      updateAssignBanner();
    }
  }
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// ── Copy pad ──────────────────────────────────────────────────────────────────
async function copyPad(fromId, toId) {
  if (fromId === toId) { setMsg('Cannot copy pad to itself', true); return; }
  const data = await api('/copy_pad', {from_id: fromId, to_id: toId});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Swap pads ─────────────────────────────────────────────────────────────────
async function swapPad(fromId, toId) {
  if (fromId === toId) { setMsg('Cannot swap pad with itself', true); return; }
  const data = await api('/swap_pads', {pad_id_a: fromId, pad_id_b: toId});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Batch apply ───────────────────────────────────────────────────────────────
function batchToggle() {
  batchMode = !batchMode;
  batchSelected.clear();
  const btn = document.getElementById('batch-toggle-btn');
  const panel = document.getElementById('batch-panel');
  if (batchMode) {
    btn.style.background = '#1a3a0a';
    btn.style.borderColor = '#4a8020';
    btn.style.color = '#a0d060';
    panel.classList.add('active');
    document.getElementById('batch-count').textContent = '0 pads selected';
    setMsg('Click pads to select, then choose a parameter and value to apply');
  } else {
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color = '';
    panel.classList.remove('active');
  }
  renderDrumMap();
}

function batchSelectAll() {
  pads.forEach(p => batchSelected.add(p.id));
  document.getElementById('batch-count').textContent = batchSelected.size + ' pads selected';
  renderDrumMap();
}

function batchClearSel() {
  batchSelected.clear();
  document.getElementById('batch-count').textContent = '0 pads selected';
  renderDrumMap();
}

async function batchApply() {
  if (!batchSelected.size) { setMsg('No pads selected', true); return; }
  const param = document.getElementById('batch-param').value;
  const value = parseInt(document.getElementById('batch-value').value, 10);
  if (isNaN(value)) { setMsg('Enter a numeric value', true); return; }
  const data = await api('/batch_set_param', {pad_ids: [...batchSelected], param, value});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
}

// ── Check broken paths ────────────────────────────────────────────────────────
async function checkPaths() {
  const data = await fetch('/api/check_paths').then(r => r.json()).catch(() => ({broken: []}));
  brokenPaths = new Set(data.broken || []);
  if (brokenPaths.size) {
    setMsg(`⚠ ${brokenPaths.size} instrument(s) not found on this machine — use 🔧 Fix broken paths in the Kits menu`, true);
  }
  renderDrumMap();
  renderPadDetail();
}

// ── Sample relink wizard ──────────────────────────────────────────────────────
async function showRelinkModal() {
  closeAllPopovers();
  const data = await fetch('/api/relink_suggest').then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  const box = document.getElementById('relink-body');
  if (!data.suggestions.length) {
    box.innerHTML = '<p style="color:#5a9a6a;font-size:.8rem;">✓ No broken instrument paths in this kit.</p>';
  } else {
    const rows = data.suggestions.map((s, i) => {
      const opts = s.candidates.map(c =>
        `<option value="${escHtml(c.rel)}">${escHtml(c.rel)}${c.score < 1 ? ` (${Math.round(c.score*100)}%)` : ''}</option>`
      ).join('');
      return `<tr>
        <td style="color:#e08020;" title="${escHtml(s.broken)}">⚠ ${escHtml(s.broken)}</td>
        <td>${s.candidates.length
          ? `<select id="rl-${i}" data-broken="${escHtml(s.broken)}" style="max-width:280px;">
               <option value="">— leave broken —</option>${opts}</select>`
          : '<span style="color:#667;">no match found in library/SD</span>'}</td>
      </tr>`;
    }).join('');
    box.innerHTML = `<div style="font-size:.7rem;color:#667;margin-bottom:6px;">
        ${data.suggestions.length} broken path(s). Best matches are pre-selected; relinking
        updates every pad that references the old path (one undo step).</div>
      <table style="width:100%;border-collapse:collapse;font-size:.72rem;">
        <thead><tr><th style="text-align:left;">Missing instrument</th><th style="text-align:left;">Replace with</th></tr></thead>
        <tbody>${rows}</tbody></table>`;
    // Pre-select the top candidate for each row
    data.suggestions.forEach((s, i) => {
      const sel = document.getElementById(`rl-${i}`);
      if (sel && s.candidates.length) sel.selectedIndex = 1;
    });
  }
  document.getElementById('relink-apply-btn').style.display = data.suggestions.length ? '' : 'none';
  document.getElementById('relink-modal').classList.add('open');
}

function closeRelinkModal() {
  document.getElementById('relink-modal').classList.remove('open');
}

async function applyRelink() {
  const mapping = {};
  document.querySelectorAll('#relink-body select[data-broken]').forEach(sel => {
    if (sel.value) mapping[sel.dataset.broken] = sel.value;
  });
  if (!Object.keys(mapping).length) { setMsg('Pick at least one replacement', true); return; }
  const data = await api('/relink_apply', {mapping});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  closeRelinkModal();
  await checkPaths();
  setMsg(data.message);
}

// ── Kit FX editor ─────────────────────────────────────────────────────────────
async function showKitFxModal() {
  closeAllPopovers();
  const d = await fetch('/api/kit_fx').then(r => r.json());
  if (d.error) { setMsg(d.error, true); return; }
  renderKitFx(d);
  document.getElementById('kitfx-modal').classList.add('open');
}

async function kitFxSet(param, value) {
  if (isNaN(value)) return;
  const data = await api('/kit_fx_set', {param, value});
  if (data.error) { setMsg(data.error, true); return; }
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderKitFx(data.fx);
  setMsg(data.message);
}

function kfxSlider(param, val, lo=0, hi=99) {
  return `<div class="param-slider-wrap">`
    + `<input type="range" min="${lo}" max="${hi}" value="${Math.min(hi,Math.max(lo,val))}" `
    + `oninput="this.nextElementSibling.textContent=this.value" `
    + `onchange="kitFxSet('${param}',+this.value)">`
    + `<span class="param-val">${val}</span></div>`;
}

function kfxNum(param, val, lo, hi, suffix='') {
  return `<span style="display:flex;align-items:center;gap:4px;">
    <input type="number" min="${lo}" max="${hi}" value="${val}" class="midi-select" style="width:60px;"
      onchange="kitFxSet('${param}',Math.min(${hi},Math.max(${lo},+this.value)))">${suffix}</span>`;
}

function kfxRow(label, control, title='') {
  return `<div class="param-row"><span class="param-lbl"${title?` title="${title}"`:''}>${label}</span>${control}</div>`;
}

function kfxSection(label) {
  return `<div class="param-row" style="margin-top:8px;padding-top:6px;border-top:1px solid #2a2a3e;">
    <span class="param-lbl" style="font-weight:600;color:#7ab3ef;font-size:.7rem;">${label}</span></div>`;
}

function renderKitFx(d) {
  const rvOpts = [];
  const rvMax = Math.max(d.reverb_max_seen, d.reverb.type);
  for (let i = 0; i <= rvMax; i++) {
    const nm = d.reverb_names[i] || `Type ${i}`;
    rvOpts.push(`<option value="${i}"${d.reverb.type===i?' selected':''}>${nm}</option>`);
  }
  const fxSel = (param, f) => `<select class="midi-select" style="width:130px;"
      onchange="kitFxSet('${param}',+this.value)">
      <option value="255"${f.type===255?' selected':''}>Off</option>
      ${d.fx_types.map((n,i)=>`<option value="${i}"${f.type===i?' selected':''}>${n}</option>`).join('')}
    </select>`;
  const fxBlock = (label, key, f) => {
    const isDelay = f.type >= 9 && f.type <= 16;
    return kfxSection(label)
      + kfxRow('Type', fxSel(`${key}_type`, f))
      + kfxRow('Level',    kfxSlider(`${key}_level`,    f.level))
      + kfxRow('Feedback', kfxSlider(`${key}_feedback`, f.feedback))
      + kfxRow('Depth',    kfxSlider(`${key}_depth`,    f.depth))
      + kfxRow('Rate',     kfxSlider(`${key}_rate`,     f.rate))
      + (isDelay ? kfxRow('Delay', kfxNum(`${key}_delay_ms`, f.delay_ms, 0, 3000, 'ms'),
                          'Delay time in ms (delay-family effects)') : '');
  };
  const eq = d.eq_comp;
  const freqHint = idx => d.known_freqs[idx] ? ` <span style="color:#667;font-size:.65rem;">${d.known_freqs[idx]}</span>` : '';
  document.getElementById('kitfx-body').innerHTML = `
    <span class="sin-ro-badge" style="align-self:flex-start;">offsets hardware-confirmed &mdash; reverb/FX type names beyond the hex-diff anchors are inferred from the manual</span>
    <div style="max-height:60vh;overflow-y:auto;padding-right:4px;">
    ${kfxSection('Reverb')}
    ${kfxRow('Type', `<select class="midi-select" style="width:130px;" onchange="kitFxSet('reverb_type',+this.value)">${rvOpts.join('')}</select>`,
             'Only Big Gate (2) and Close Mic (3) are hardware-confirmed names')}
    ${kfxRow('Level', kfxSlider('reverb_level', d.reverb.level))}
    ${kfxRow('Size',  kfxSlider('reverb_size',  d.reverb.size))}
    ${kfxRow('Color', kfxSlider('reverb_color', d.reverb.color), 'High-frequency damping — higher = brighter')}
    ${fxBlock('FX1', 'fx1', d.fx1)}
    ${fxBlock('FX2', 'fx2', d.fx2)}
    ${kfxSection('EQ')}
    ${kfxRow('LF Gain', kfxNum('eq_lf_gain', eq.lf_gain_db, -60, 12, 'dB'))}
    ${kfxRow('LF Freq', kfxNum('eq_lf_freq', eq.lf_freq_idx, 0, 127, `idx${freqHint(eq.lf_freq_idx)}`),
             'Sequential frequency-table index (10=58 Hz, 11=66 Hz); full table not yet enumerated')}
    ${kfxRow('HF Gain', kfxNum('eq_hf_gain', eq.hf_gain_db, -60, 12, 'dB'))}
    ${kfxRow('HF Freq', kfxNum('eq_hf_freq', eq.hf_freq_idx, 0, 127, `idx${freqHint(eq.hf_freq_idx)}`),
             'Sequential frequency-table index (77=8.7 kHz, 78=9.1 kHz); full table not yet enumerated')}
    ${kfxSection('Compressor')}
    ${kfxRow('Preset', `<select class="midi-select" style="width:130px;" onchange="kitFxSet('comp_preset',+this.value)">
      ${d.comp_presets.map((n,i)=>`<option value="${i}"${eq.comp_preset===i?' selected':''}>${n}</option>`).join('')}
    </select>`, '0=Master 1 and 1=Radio 1 hardware-confirmed; remaining order from the official editor guide')}
    ${kfxRow('Threshold', kfxNum('comp_threshold', eq.threshold_db, -90, 0, 'dB'))}
    ${kfxRow('Output',    kfxNum('comp_output',    eq.output_db,   -24, 24, 'dB'))}
    </div>
    <div style="font-size:.65rem;color:#667;margin-top:6px;">Edits write to the loaded kit's KIT header — save the kit to persist. Per-pad send levels live in each pad's FX/Zone section.</div>`;
}

// ── Kit bundles ───────────────────────────────────────────────────────────────
function exportBundle() {
  closeAllPopovers();
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  setMsg('Building bundle… (kit + instruments + samples)');
  window.location = '/api/export_bundle';
}

async function importBundle(file) {
  closeAllPopovers();
  setMsg(`Importing ${file.name}…`);
  const buf = await file.arrayBuffer();
  let bin = '';
  const bytes = new Uint8Array(buf);
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  const data = await api('/import_bundle', {data_b64: btoa(bin)});
  if (data.error) { setMsg(data.error, true); return; }
  kits = data.kits;
  avail = data.instruments;
  renderKitList();
  renderInstruments();
  await checkPaths();
  setMsg(data.message);
}

// ── Kit diff ──────────────────────────────────────────────────────────────────
function showDiffModal() {
  closeAllPopovers();
  const sel = document.getElementById('diff-kit-select');
  sel.innerHTML = '<option value="">— select a kit —</option>'
    + kits.map(k => `<option value="${escHtml(k.path)}">${escHtml(k.name)}</option>`).join('');
  document.getElementById('diff-result').innerHTML = '';
  document.getElementById('diff-modal').classList.add('open');
}

function closeDiffModal() {
  document.getElementById('diff-modal').classList.remove('open');
}

async function runDiff() {
  const path = document.getElementById('diff-kit-select').value;
  if (!path) { setMsg('Select a kit to compare', true); return; }
  const data = await api('/diff_kit', {path});
  if (data.error) { setMsg(data.error, true); return; }
  const box = document.getElementById('diff-result');
  if (!data.diff.length) {
    box.innerHTML = `<div class="diff-no-diff">No differences found between current kit and ${escHtml(data.other_name)}.</div>`;
    return;
  }
  const LABELS = {
    layer_a: 'Layer A', layer_b: 'Layer B', midi_note: 'MIDI note',
    la_level: 'A level', la_pan: 'A pan', la_pitch: 'A pitch', la_fine: 'A fine pitch', la_loop: 'A loop',
    la_decay: 'A decay', la_vel_vol: 'A vel→vol',
    lb_level: 'B level', lb_pan: 'B pan', lb_pitch: 'B pitch', lb_fine: 'B fine pitch', lb_loop: 'B loop',
    lb_decay: 'B decay', lb_vel_vol: 'B vel→vol',
  };
  const rows = data.diff.map(d => {
    if (d.only_in) {
      const where = d.only_in === 'current' ? 'only in current kit' : `only in ${escHtml(data.other_name)}`;
      return `<tr class="diff-row-changed"><td>${escHtml(d.id)}</td><td colspan="3" style="color:#889;">${where}</td></tr>`;
    }
    const fields = Object.entries(d.changed).map(([k, v]) => {
      const lbl = LABELS[k] || k;
      const cur = v.current === null ? '—' : String(v.current);
      const oth = v.other   === null ? '—' : String(v.other);
      return `<tr class="diff-row-changed"><td>${escHtml(d.id)}</td><td>${escHtml(lbl)}</td>`
        + `<td class="diff-val-cur">${escHtml(cur)}</td>`
        + `<td class="diff-val-oth">${escHtml(oth)}</td></tr>`;
    }).join('');
    return fields;
  }).join('');
  box.innerHTML = `<div style="font-size:.68rem;color:#556;margin-bottom:4px;">`
    + `${data.diff.length} pad(s) differ · comparing current kit vs ${escHtml(data.other_name)}</div>`
    + `<table><thead><tr><th>Pad</th><th>Param</th>`
    + `<th>Current</th><th>${escHtml(data.other_name)}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>`;
}

// ── Kit time machine ──────────────────────────────────────────────────────────
let tmSnaps = [];   // snapshots for the current kit (newest first)
let tmSel   = null; // focused snapshot id

const TM_DIFF_LABELS = {
  layer_a: 'Layer A', layer_b: 'Layer B', midi_note: 'MIDI note',
  la_level: 'A level', la_pan: 'A pan', la_pitch: 'A pitch',
  la_fine: 'A fine pitch', la_decay: 'A decay',
};

function tmFmtTime(iso, ts) {
  const d = iso ? new Date(iso) : new Date((ts || 0) * 1000);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  return sameDay ? time : d.toLocaleDateString([], {month: 'short', day: 'numeric'}) + ' ' + time;
}

function tmFmtSize(n) {
  return n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';
}

function openTimeMachine() {
  closeAllPopovers();
  document.getElementById('tm-modal').classList.add('open');
  loadTimeMachine();
}
function closeTimeMachine() {
  document.getElementById('tm-modal').classList.remove('open');
}

async function loadTimeMachine() {
  const all = document.getElementById('tm-all-kits').checked;
  const data = await fetch('/api/snapshots' + (all ? '?all=1' : '')).then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  document.getElementById('tm-kit-name').textContent =
    tmSnaps.length ? `· ${data.kit} · ${tmSnaps.length} snapshot(s)` : `· ${data.kit} · no snapshots yet`;
  if (!tmSnaps.some(s => s.id === tmSel)) tmSel = tmSnaps.length ? tmSnaps[0].id : null;
  renderTimeMachine();
}

function renderTimeMachine() {
  const list = document.getElementById('tm-list');
  const slider = document.getElementById('tm-slider');
  if (!tmSnaps.length) {
    list.innerHTML = `<div class="tm-empty">No snapshots for this kit yet. They appear automatically on load and save, or hit “Snapshot now”.</div>`;
    slider.max = 0; slider.value = 0;
    document.getElementById('tm-scrub-lbl').textContent = '';
    tmFillCompareSelects();
    return;
  }
  slider.max = tmSnaps.length - 1;
  const selIdx = Math.max(0, tmSnaps.findIndex(s => s.id === tmSel));
  slider.value = selIdx;
  const cur = tmSnaps[selIdx];
  document.getElementById('tm-scrub-lbl').textContent =
    `${selIdx + 1} / ${tmSnaps.length} · ${tmFmtTime(cur.iso, cur.ts)}`;

  list.innerHTML = tmSnaps.map(s => {
    const kind = (s.kind || 'manual');
    return `<div class="tm-snap${s.id === tmSel ? ' sel' : ''}" onclick="tmSelect('${s.id}')">
      <div class="tm-snap-top">
        <span class="tm-kind ${kind}">${escHtml(kind)}</span>
        <span class="tm-snap-lbl">${escHtml(s.label || '')}</span>
        <button class="tm-pin${s.pinned ? ' on' : ''}" title="${s.pinned ? 'Unpin' : 'Pin (survives cleanup)'}"
          onclick="event.stopPropagation();tmPin('${s.id}',${s.pinned ? 'false' : 'true'})">&#x1F4CC;</button>
        <span class="tm-snap-time">${tmFmtTime(s.iso, s.ts)}</span>
      </div>
      <div class="tm-snap-meta">
        <span>${s.assigned ?? '?'} pads assigned</span><span>${tmFmtSize(s.size || 0)}</span>
        ${document.getElementById('tm-all-kits').checked ? `<span>${escHtml(s.kit || '')}</span>` : ''}
      </div>
      <div class="tm-snap-actions">
        <button onclick="event.stopPropagation();tmRestore('${s.id}')">&#x21BA; Restore</button>
        <button onclick="event.stopPropagation();tmDiffVsCurrent('${s.id}')">&#x1F50D; vs current</button>
        <button class="tm-del" onclick="event.stopPropagation();tmDelete('${s.id}')">&#x2715;</button>
      </div>
    </div>`;
  }).join('');
  tmFillCompareSelects();
}

function tmFillCompareSelects() {
  const opts = `<option value="current">Current working state</option>`
    + tmSnaps.map(s => `<option value="${s.id}">${escHtml(s.label || s.id)} · ${tmFmtTime(s.iso, s.ts)}</option>`).join('');
  const a = document.getElementById('tm-cmp-a'), b = document.getElementById('tm-cmp-b');
  const av = a.value, bv = b.value;
  a.innerHTML = opts; b.innerHTML = opts;
  a.value = (tmSel && tmSnaps.some(s => s.id === av)) ? av : (tmSel || 'current');
  b.value = bv && (bv === 'current' || tmSnaps.some(s => s.id === bv)) ? bv : 'current';
}

function tmScrub(idx) {
  if (!tmSnaps[idx]) return;
  tmSel = tmSnaps[idx].id;
  renderTimeMachine();
  tmDiffVsCurrent(tmSel);
}

function tmSelect(id) {
  tmSel = id;
  renderTimeMachine();
  tmDiffVsCurrent(id);
}

async function tmSnapshotNow() {
  const data = await api('/snapshot', {kind: 'manual'});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.snapshot?.deduped) setMsg('No changes since the last snapshot');
  else setMsg('Snapshot saved');
  tmSnaps = data.snapshots || [];
  if (data.snapshot && !data.snapshot.deduped) tmSel = data.snapshot.id;
  document.getElementById('tm-kit-name').textContent = `· ${data.kit} · ${tmSnaps.length} snapshot(s)`;
  renderTimeMachine();
}

// Debounced auto-snapshot so an editing session leaves a trail (server dedupes).
let _autoSnapTimer = null;
function scheduleAutoSnapshot() {
  if (_autoSnapTimer) clearTimeout(_autoSnapTimer);
  _autoSnapTimer = setTimeout(() => {
    _autoSnapTimer = null;
    api('/snapshot', {kind: 'auto'}).then(() => {
      if (document.getElementById('tm-modal').classList.contains('open')) loadTimeMachine();
    }).catch(() => {});
  }, 20000);
}

function _tmRenderDiff(data, aLabel, bLabel) {
  const box = document.getElementById('tm-diff');
  if (data.error) { box.innerHTML = `<div class="tm-empty">${escHtml(data.error)}</div>`; return; }
  if (!data.diff.length) {
    box.innerHTML = `<div class="tm-empty">No differences between <b>${escHtml(aLabel)}</b> and <b>${escHtml(bLabel)}</b>.</div>`;
    return;
  }
  const rows = data.diff.map(d => {
    if (d.only_in) {
      const where = d.only_in === 'current' ? `only in ${escHtml(aLabel)}` : `only in ${escHtml(bLabel)}`;
      return `<tr class="chg"><td>${escHtml(d.id)}</td><td colspan="3" style="color:#889;">${where}</td></tr>`;
    }
    return Object.entries(d.changed).map(([k, v]) => {
      const lbl = TM_DIFF_LABELS[k] || k;
      const a = v.current === null ? '—' : String(v.current);
      const b = v.other   === null ? '—' : String(v.other);
      return `<tr class="chg"><td>${escHtml(d.id)}</td><td>${escHtml(lbl)}</td>`
        + `<td class="diff-val-cur">${escHtml(a)}</td><td class="diff-val-oth">${escHtml(b)}</td></tr>`;
    }).join('');
  }).join('');
  box.innerHTML = `<div style="font-size:.66rem;color:#556;margin-bottom:4px;">`
    + `${data.changed_count} pad(s) differ · <b>${escHtml(aLabel)}</b> vs <b>${escHtml(bLabel)}</b></div>`
    + `<table><thead><tr><th>Pad</th><th>Param</th><th>${escHtml(aLabel)}</th><th>${escHtml(bLabel)}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>`;
}

function _tmSourceLabel(id) {
  if (id === 'current') return 'Current';
  const s = tmSnaps.find(s => s.id === id);
  return s ? `${s.label} · ${tmFmtTime(s.iso, s.ts)}` : id;
}

async function tmDiffVsCurrent(id) {
  const data = await api('/snapshot_diff', {a: id, b: 'current'});
  _tmRenderDiff(data, _tmSourceLabel(id), 'Current');
}

async function tmCompare() {
  const a = document.getElementById('tm-cmp-a').value;
  const b = document.getElementById('tm-cmp-b').value;
  const data = await api('/snapshot_diff', {a, b});
  _tmRenderDiff(data, _tmSourceLabel(a), _tmSourceLabel(b));
}

async function tmRestore(id) {
  const s = tmSnaps.find(s => s.id === id);
  if (!await appConfirm(`Restore "${s ? s.label : id}"? This replaces the working kit (undoable with Ctrl+Z).`, 'Restore')) return;
  const data = await api('/snapshot_restore', {id});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  refreshKitSize();
  checkPaths();
  const kfxModal = document.getElementById('kitfx-modal');
  if (kfxModal && kfxModal.classList.contains('open')) showKitFxModal();
  setMsg(data.message || 'Snapshot restored');
}

async function tmDelete(id) {
  const s = tmSnaps.find(s => s.id === id);
  if (!await appConfirm(`Delete snapshot "${s ? s.label : id}"? This cannot be undone.`, 'Delete')) return;
  const data = await api('/snapshot_delete', {id});
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  if (tmSel === id) tmSel = tmSnaps.length ? tmSnaps[0].id : null;
  document.getElementById('tm-kit-name').textContent = `· ${data.kit} · ${tmSnaps.length} snapshot(s)`;
  renderTimeMachine();
  setMsg('Snapshot deleted');
}

async function tmPin(id, pinned) {
  const data = await api('/snapshot_pin', {id, pinned});
  if (data.error) { setMsg(data.error, true); return; }
  tmSnaps = data.snapshots || [];
  renderTimeMachine();
}

// ── Instrument (.sin) editor ──────────────────────────────────────────────────
let sinEd = null;  // current /api/sin_detail payload while the editor modal is open

async function openSinEditor(rel) {
  const data = await fetch('/api/sin_detail?sin=' + encodeURIComponent(rel)).then(r => r.json());
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  document.getElementById('sin-modal').classList.add('open');  // before render: lane needs real width
  renderSinEditor();
}

function closeSinEditor() {
  document.getElementById('sin-modal').classList.remove('open');
  sinEd = null;
}

function _sinSlider(id, label, val, min, max) {
  return `<div class="sin-row"><label>${label}</label>
    <input type="range" id="sin-${id}" min="${min}" max="${max}" value="${val}"
      oninput="document.getElementById('sin-${id}-v').textContent=this.value;if(this.id.includes('vel_'))renderVelCurve()">
    <span class="sin-val" id="sin-${id}-v">${val}</span></div>`;
}

function renderSinEditor() {
  const d = sinEd, p = d.params;
  const name = d.sin_rel.replace(/\.sin$/i, '');
  const ro = !d.editable;
  const dis = ro ? ' style="opacity:.55;pointer-events:none;"' : '';
  const groupOpts = Object.entries(d.groups)
    .map(([n, g]) => `<option value="${n}"${+n === p.group ? ' selected' : ''}>${escHtml(g)}</option>`).join('');
  const mapRows = d.mappings.map((m, i) => {
    const rr = m.rr > 127 ? m.rr - 256 : m.rr;
    return `<tr>
      <td title="${escHtml(m.sample)}">${escHtml(m.sample.split('/').pop())}</td>
      <td><input type="number" id="sm-${i}-vmin" min="0" max="127" value="${m.vmin}" oninput="renderZoneLane()"></td>
      <td><input type="number" id="sm-${i}-vmax" min="0" max="127" value="${m.vmax}" oninput="renderZoneLane()"></td>
      <td><input type="number" id="sm-${i}-rr" min="-2" max="127" value="${rr}"
        title="Round-robin index (-2 = hi-hat pedal function)"></td>
      <td><input type="number" id="sm-${i}-hhmin" min="0" max="127" value="${m.hh_min}"></td>
      <td><input type="number" id="sm-${i}-hhmax" min="0" max="127" value="${m.hh_max}"></td>
      <td style="white-space:nowrap;">
        <button class="layer-btn" title="Split zone at its midpoint" onclick="sinZoneOp('split',${i})">&#x2702;</button>
        <button class="layer-btn" title="Add a round-robin variant of this zone" onclick="sinZoneOp('rr',${i})">+RR</button>
        <button class="layer-btn clear" title="Delete zone" onclick="sinZoneOp('del',${i})"
          ${d.mappings.length < 2 ? 'disabled' : ''}>&#x2715;</button>
      </td>
    </tr>`;
  }).join('');
  document.getElementById('sin-body').innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <b style="font-size:.85rem;">${escHtml(name)}</b>
      ${ro ? '<span class="sin-ro-badge">read-only SD preset &mdash; sync library to edit a copy</span>' : ''}
      <button class="play-btn" onclick="previewInstrument(sinEd.sin_rel)" title="Preview">&#9654;</button>
    </div>
    <div class="sin-grid"${dis}>
      <div class="sin-row"><label>Group</label><select id="sin-group">${groupOpts}</select><span class="sin-val"></span></div>
      ${_sinSlider('level', 'Level', p.level, 0, 127)}
      ${_sinSlider('pan', 'Pan', p.pan, -50, 50)}
      ${_sinSlider('decay', 'Decay', p.decay, 0, 127)}
      ${_sinSlider('semi', 'Pitch semi', p.semi, -12, 12)}
      ${_sinSlider('fine', 'Pitch fine', p.fine, -50, 50)}
      ${_sinSlider('cutoff', 'Filter cutoff', p.cutoff, 0, 127)}
      <div class="sin-row"><label>Filter type</label><select id="sin-hipass">
        <option value="0"${p.hipass ? '' : ' selected'}>Low-pass</option>
        <option value="1"${p.hipass ? ' selected' : ''}>High-pass</option></select><span class="sin-val"></span></div>
      ${_sinSlider('vel_level', 'Vel &rarr; Level', p.vel_level, -99, 99)}
      ${_sinSlider('vel_decay', 'Vel &rarr; Decay', p.vel_decay, -99, 99)}
      ${_sinSlider('vel_pitch', 'Vel &rarr; Pitch', p.vel_pitch, -99, 99)}
      ${_sinSlider('vel_filter', 'Vel &rarr; Filter', p.vel_filter, -99, 99)}
      <div class="sin-row"><label>Loop</label><input type="checkbox" id="sin-loop"${p.loop ? ' checked' : ''}
        style="margin:0;width:auto;flex:none;"><span class="sin-val"></span></div>
      <div class="sin-row"><label>Cycle mode</label><select id="sin-cycle">
        <option value="0"${d.cycle_random ? '' : ' selected'}>Round-robin</option>
        <option value="1"${d.cycle_random ? ' selected' : ''}>Random</option></select><span class="sin-val"></span></div>
    </div>
    <div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;margin-top:8px;">
      <div>
        <div class="sin-sec-title" style="margin-top:0;">Velocity response
          <button class="sin-curve-tab" id="sct-vel_level" onclick="setCurveParam('vel_level')">Level</button>
          <button class="sin-curve-tab" id="sct-vel_decay" onclick="setCurveParam('vel_decay')">Decay</button>
          <button class="sin-curve-tab" id="sct-vel_pitch" onclick="setCurveParam('vel_pitch')">Pitch</button>
          <button class="sin-curve-tab" id="sct-vel_filter" onclick="setCurveParam('vel_filter')">Filter</button>
        </div>
        <svg id="sin-curve" width="240" height="120" title="Drag vertically to set depth"></svg>
        <div style="font-size:.6rem;color:#556;margin-top:2px;">soft hit → hard hit · drag curve to set depth</div>
      </div>
      <div style="flex:1;min-width:360px;">
        <div class="sin-sec-title" style="margin-top:0;">Velocity zones (${d.mappings.length}) — drag edges to move split points · click a zone to audition at that velocity</div>
        <svg id="sin-lane" width="100%" height="40"></svg>
      </div>
    </div>
    <div style="font-size:.7rem;color:#667;margin-top:6px;">Sample mappings (${d.mappings.length})</div>
    <div class="sin-maps"${dis}>
      <table><thead><tr><th>Sample</th><th>Vel&nbsp;min</th><th>Vel&nbsp;max</th><th>RR</th>
        <th>HH&nbsp;open&nbsp;min</th><th>HH&nbsp;open&nbsp;max</th><th></th></tr></thead>
      <tbody>${mapRows}</tbody></table>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px;">
      ${d.has_backup && d.editable ? '<button class="btn-secondary" onclick="revertSin()">Revert all edits</button>' : ''}
      ${ro ? '' : '<button class="btn-primary" onclick="saveSin()">Save</button>'}
      <button class="btn-secondary" onclick="closeSinEditor()">Close</button>
    </div>`;
  initSinVisuals();
}

// ── Velocity zone lane + response curves ──────────────────────────────────────
let curveParam   = 'vel_level';
let _laneLayout  = [];    // [{i, vmin, vmax, row}] from last renderZoneLane
let _laneDragB   = null;  // boundary value being dragged, or null
let _laneAudio   = null;  // lazy AudioContext for zone audition
const LANE_ROW_H = 22, LANE_AXIS_H = 14;

function initSinVisuals() {
  renderZoneLane();
  setCurveParam(curveParam);
  const lane = document.getElementById('sin-lane');
  lane.addEventListener('pointerdown', laneDown);
  lane.addEventListener('pointermove', laneHover);
  const curve = document.getElementById('sin-curve');
  curve.addEventListener('pointerdown', curveDown);
}

function _mapVals() {
  return sinEd.mappings.map((m, i) => ({
    i,
    vmin: +document.getElementById(`sm-${i}-vmin`).value,
    vmax: +document.getElementById(`sm-${i}-vmax`).value,
    sample: m.sample,
  }));
}

function _laneW() {
  const el = document.getElementById('sin-lane');
  return Math.max(360, el.clientWidth || el.parentElement.clientWidth || 560);
}

function _velFromX(evt) {
  const rect = document.getElementById('sin-lane').getBoundingClientRect();
  return Math.max(0, Math.min(127, (evt.clientX - rect.left) / rect.width * 128));
}

function renderZoneLane() {
  const lane = document.getElementById('sin-lane');
  if (!lane || !sinEd) return;
  const maps  = _mapVals();
  // Same-range mappings (round robins) stack vertically within one band
  const bands = {};
  maps.forEach(m => { const k = m.vmin + '-' + m.vmax; (bands[k] = bands[k] || []).push(m); });
  _laneLayout = [];
  for (const k in bands) bands[k].forEach((m, row) => _laneLayout.push({...m, row}));
  const rows = Math.max(1, ...Object.values(bands).map(b => b.length));
  const W = _laneW(), H = rows * LANE_ROW_H + LANE_AXIS_H;
  const sx = v => v / 128 * W;
  const colors = ['#3a7bd5', '#3aa07a', '#a07a3a', '#7a3aa0', '#a03a5a', '#5aa0c8'];
  let svg = '';
  // velocity grid lines + labels
  for (const v of [0, 32, 64, 96, 127]) {
    svg += `<line x1="${sx(v)}" y1="0" x2="${sx(v)}" y2="${H - LANE_AXIS_H}" stroke="#26334a" stroke-width="1"/>`
        +  `<text x="${Math.min(sx(v) + 2, W - 18)}" y="${H - 3}" font-size="9" fill="#667">${v}</text>`;
  }
  const bandKeys = Object.keys(bands).sort((a, b) => parseInt(a) - parseInt(b));
  _laneLayout.forEach(m => {
    const bi = bandKeys.indexOf(m.vmin + '-' + m.vmax);
    const x = sx(m.vmin), w = Math.max(2, sx(m.vmax + 1) - x);
    const y = m.row * LANE_ROW_H + 2;
    const name = m.sample.split('/').pop().replace(/\.wav$/i, '');
    svg += `<rect x="${x}" y="${y}" width="${w}" height="${LANE_ROW_H - 4}" rx="3"
              fill="${colors[bi % colors.length]}" fill-opacity="0.75" stroke="#0b0e15" stroke-width="1"/>`;
    if (w > 46) {
      svg += `<text x="${x + 4}" y="${y + 12}" font-size="9" fill="#eef"
                style="pointer-events:none">${escHtml(name.slice(0, Math.floor(w / 6)))}</text>`;
    }
  });
  lane.setAttribute('height', H);
  lane.setAttribute('viewBox', `0 0 ${W} ${H}`);
  lane.setAttribute('preserveAspectRatio', 'none');
  lane.innerHTML = svg;
}

function _nearBoundary(vel) {
  // Returns the boundary value (zone start, or end+1) within grab range of vel
  for (const m of _laneLayout) {
    if (Math.abs(vel - m.vmin) < 2.2) return m.vmin;
    if (Math.abs(vel - (m.vmax + 1)) < 2.2) return m.vmax + 1;
  }
  return null;
}

function laneHover(evt) {
  if (_laneDragB !== null) return;
  const lane = document.getElementById('sin-lane');
  const b = _nearBoundary(_velFromX(evt));
  lane.style.cursor = (b !== null && b > 0 && b < 128 && sinEd.editable) ? 'ew-resize' : 'pointer';
}

function laneDown(evt) {
  evt.preventDefault();
  const vel = _velFromX(evt);
  const b = _nearBoundary(vel);
  if (b !== null && b > 0 && b < 128 && sinEd.editable) {
    _laneDragB = b;
    const move = e => laneDragMove(e);
    const up = () => { _laneDragB = null;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up); };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    return;
  }
  // Audition: find the zone under the pointer at its clicked velocity
  const rect = document.getElementById('sin-lane').getBoundingClientRect();
  const row = Math.floor((evt.clientY - rect.top) / LANE_ROW_H);
  const v = Math.round(vel);
  const hit = _laneLayout.find(m => m.row === row && m.vmin <= v && v <= m.vmax)
           || _laneLayout.find(m => m.vmin <= v && v <= m.vmax);
  if (hit) playZone(hit.i, Math.max(1, v));
}

function laneDragMove(evt) {
  if (_laneDragB === null) return;
  const nb = Math.round(Math.max(1, Math.min(127, _velFromX(evt))));
  if (nb === _laneDragB) return;
  // Move every edge that sat on the old boundary (band mates + abutting neighbours)
  let valid = true;
  const edits = [];
  for (const m of _mapVals()) {
    let vmin = m.vmin, vmax = m.vmax;
    if (vmin === _laneDragB) vmin = nb;
    if (vmax + 1 === _laneDragB) vmax = nb - 1;
    if (vmin > vmax) { valid = false; break; }
    edits.push([m.i, vmin, vmax]);
  }
  if (!valid) return;  // refuse drags that would invert a zone
  for (const [i, vmin, vmax] of edits) {
    document.getElementById(`sm-${i}-vmin`).value = vmin;
    document.getElementById(`sm-${i}-vmax`).value = vmax;
  }
  _laneDragB = nb;
  renderZoneLane();
}

async function playZone(idx, vel) {
  try {
    _laneAudio = _laneAudio || new (window.AudioContext || window.webkitAudioContext)();
    const r = await fetch(`/api/wav?sin=${encodeURIComponent(sinEd.sin_rel)}&idx=${idx}`);
    if (!r.ok) throw new Error();
    const buf = await _laneAudio.decodeAudioData(await r.arrayBuffer());
    const src = _laneAudio.createBufferSource();
    src.buffer = buf;
    const g = _laneAudio.createGain();
    g.gain.value = Math.max(0.04, Math.pow(vel / 127, 2));
    src.connect(g); g.connect(_laneAudio.destination);
    src.start();
    setMsg(`▶ zone ${idx + 1} @ velocity ${vel}`);
  } catch {
    setMsg('Sample unavailable for preview (sync library from SD?)', true);
  }
}

function setCurveParam(p) {
  curveParam = p;
  document.querySelectorAll('.sin-curve-tab').forEach(b =>
    b.classList.toggle('active', b.id === 'sct-' + p));
  renderVelCurve();
}

function renderVelCurve() {
  const svg = document.getElementById('sin-curve');
  if (!svg || !sinEd) return;
  const d = +document.getElementById('sin-' + curveParam).value;  // -99..99 depth
  const W = 240, H = 120, pad = 8;
  // Depth visualization: output vs velocity; d=0 flat, +99 full upward slope
  const y = v => {
    const out = 0.5 + (d / 99) * (v / 127 - 0.5);
    return pad + (1 - out) * (H - 2 * pad);
  };
  let s = `<line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="#26334a"/>`;
  for (const v of [32, 64, 96]) {
    s += `<line x1="${v/127*W}" y1="0" x2="${v/127*W}" y2="${H}" stroke="#1c2738"/>`;
  }
  s += `<polyline points="${[0, 32, 64, 96, 127].map(v => `${v/127*W},${y(v)}`).join(' ')}"
         fill="none" stroke="#3a7bd5" stroke-width="2.5" stroke-linecap="round"/>`;
  s += `<circle cx="${W/2}" cy="${y(63.5)}" r="4" fill="#e0e8ff"/>`;
  s += `<text x="${W - 34}" y="14" font-size="10" fill="#88a">${d > 0 ? '+' : ''}${d}</text>`;
  svg.innerHTML = s;
}

function curveDown(evt) {
  evt.preventDefault();
  if (!sinEd.editable) return;
  const move = e => {
    const rect = document.getElementById('sin-curve').getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const d = Math.round((0.5 - frac) * 2 * 99);
    const slider = document.getElementById('sin-' + curveParam);
    slider.value = d;
    document.getElementById('sin-' + curveParam + '-v').textContent = d;
    renderVelCurve();
  };
  const up = () => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
  move(evt);
}

async function saveSin() {
  const params = _collectSinParams();
  const mappings = sinEd.mappings.map((m, i) => ({
    index: i,
    vmin:   +document.getElementById(`sm-${i}-vmin`).value,
    vmax:   +document.getElementById(`sm-${i}-vmax`).value,
    rr:     +document.getElementById(`sm-${i}-rr`).value,
    hh_min: +document.getElementById(`sm-${i}-hhmin`).value,
    hh_max: +document.getElementById(`sm-${i}-hhmax`).value,
  }));
  const data = await api('/sin_update', {sin_rel: sinEd.sin_rel, params,
                                         cycle_random: +document.getElementById('sin-cycle').value,
                                         mappings});
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

function _collectSinParams() {
  const gv = id => +document.getElementById('sin-' + id).value;
  return {
    group: gv('group'), level: gv('level'), pan: gv('pan'), decay: gv('decay'),
    semi: gv('semi'), fine: gv('fine'), cutoff: gv('cutoff'), hipass: gv('hipass'),
    vel_level: gv('vel_level'), vel_decay: gv('vel_decay'),
    vel_pitch: gv('vel_pitch'), vel_filter: gv('vel_filter'),
    loop: document.getElementById('sin-loop').checked ? 1 : 0,
  };
}

async function sinZoneOp(op, idx) {
  if (!sinEd.editable) return;
  // Current zone list from the live inputs, each cloning its original block (src)
  const zones = sinEd.mappings.map((m, i) => ({
    src: i,
    vmin:   +document.getElementById(`sm-${i}-vmin`).value,
    vmax:   +document.getElementById(`sm-${i}-vmax`).value,
    rr:     +document.getElementById(`sm-${i}-rr`).value,
    hh_min: +document.getElementById(`sm-${i}-hhmin`).value,
    hh_max: +document.getElementById(`sm-${i}-hhmax`).value,
  }));
  const z = zones[idx];
  if (op === 'split') {
    if (z.vmax - z.vmin < 1) { setMsg('Zone too narrow to split', true); return; }
    const mid = Math.floor((z.vmin + z.vmax) / 2);
    zones.splice(idx, 1,
      {...z, vmax: mid},
      {...z, vmin: mid + 1});
  } else if (op === 'rr') {
    const bandMax = Math.max(...zones.filter(o => o.vmin === z.vmin && o.vmax === z.vmax)
                                  .map(o => o.rr >= 0 && o.rr < 128 ? o.rr : 0));
    zones.splice(idx + 1, 0, {...z, rr: bandMax + 1});
  } else if (op === 'del') {
    if (zones.length < 2) { setMsg('An instrument needs at least one zone', true); return; }
    zones.splice(idx, 1);
  }
  const data = await api('/sin_zones', {
    sin_rel: sinEd.sin_rel, zones,
    cycle_random: +document.getElementById('sin-cycle').value,
    params: _collectSinParams(),
  });
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

async function revertSin() {
  const data = await api('/sin_revert', {sin_rel: sinEd.sin_rel});
  if (data.error) { setMsg(data.error, true); return; }
  sinEd = data;
  renderSinEditor();
  setMsg(data.message);
}

// ── Kit duplicate ─────────────────────────────────────────────────────────────
function showDuplicateForm() {
  closeAllPopovers();
  const form = document.getElementById('dup-form');
  form.style.display = 'flex';
  const inp = document.getElementById('dup-name');
  inp.value = kitName.replace(/\.skt$/i, '') + ' copy';
  inp.focus();
  inp.select();
}
function cancelDuplicate() {
  document.getElementById('dup-form').style.display = 'none';
}
async function confirmDuplicate() {
  const name = document.getElementById('dup-name').value.trim();
  if (!name) { setMsg('Enter a name for the copy', true); return; }
  cancelDuplicate();
  const data = await api('/duplicate_kit', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kits = data.kits;
  renderKitList();
  setMsg(data.message);
}

// ── Clear all pads ────────────────────────────────────────────────────────────
async function clearAllPads() {
  if (!await appConfirm('Clear all pad assignments? This can be undone.', 'Clear all')) return;
  const data = await api('/clear_all_pads', {});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap();
  renderPadDetail();
  setMsg(data.message);
  refreshKitSize();
}

// ── Kit templates ─────────────────────────────────────────────────────────────
async function runTemplate(name) {
  setMsg(`Running template ${name}…`);
  const data = await api('/run_template', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = libSavePath;
  kits          = data.kits || kits;
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kne = document.getElementById('kit-name');
  kne.textContent    = '— ' + kitName;
  kne.contentEditable = 'true';
  document.getElementById('save-lib-btn').disabled   = !libSavePath;
  document.getElementById('dup-btn').disabled        = false;
  document.getElementById('clear-pads-btn').disabled = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(false, 0, []);
  renderKitList(); renderPatchPanel(); renderDrumMap(); renderPadDetail(); updateAssignBanner();
  setMsg(data.message || `Template ${name} applied`);
}

// ── Kit size ──────────────────────────────────────────────────────────────────
async function refreshKitSize() {
  const badge = document.getElementById('kit-size-badge');
  if (!badge || !kitName) { if (badge) badge.style.display = 'none'; return; }
  try {
    const data = await fetch('/api/kit_size').then(r => r.json());
    const mb   = (data.total_bytes / 1048576).toFixed(1);
    const warn = data.total_bytes > 178000000;  // warn above ~170 MB
    badge.textContent = `${mb} MB`;
    badge.style.display = '';
    badge.style.color = warn ? '#c08030' : '#557799';
    badge.title = `${data.found_wavs} / ${data.total_wavs} WAV files located`;
  } catch(e) { badge.style.display = 'none'; }
}

async function importAssignCSV(file) {
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  const text = await file.text();
  const assignments = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const cols = line.split(',').map(c => c.trim());
    if (cols.length < 2) continue;
    // Support: pad_id,sin_rel  OR  pad_id,layer,sin_rel
    if (cols.length === 2) {
      assignments.push({pad_id: cols[0], layer: 'a', sin_rel: cols[1]});
    } else {
      assignments.push({pad_id: cols[0], layer: cols[1].toLowerCase(), sin_rel: cols[2]});
    }
  }
  if (!assignments.length) { setMsg('No valid rows found in CSV', true); return; }
  setMsg(`Assigning ${assignments.length} pads from CSV…`);
  const data = await api('/batch_assign_csv', {assignments});
  if (data.error) { setMsg(data.error, true); return; }
  pads = data.pads;
  setDirtyState(data.dirty, data.undo_count, data.history_labels);
  renderDrumMap(); renderPadDetail(); checkPaths();
  setMsg(data.message + (data.skipped?.length ? ` — skipped: ${data.skipped.slice(0,3).join(', ')}${data.skipped.length > 3 ? '…' : ''}` : ''));
}

function printMidiMap() {
  if (!pads.length) { setMsg('Load a kit first', true); return; }
  window.open('/api/midi_map_html', '_blank');
}

async function exportKits() {
  const a = document.createElement('a');
  a.href = '/api/export_kits';
  a.download = 'strike_kits_export.json';
  a.click();
}

// ── SD sync ───────────────────────────────────────────────────────────────────
async function syncKitsFromCard() {
  setMsg('Syncing kits from card…');
  const data = await api('/sync_kits', {});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.kits) { kits = data.kits; renderKitList(); }
  setMsg(data.message);
}

let _syncPollTimer = null;

async function syncLibrary() {
  const btn = document.getElementById('sync-lib-btn');
  const prog = document.getElementById('sync-progress');
  const startData = await api('/sync_library', {});
  if (startData.error) { setMsg(startData.error, true); return; }
  prog.style.display = '';
  if (btn) btn.disabled = true;
  _pollSyncStatus();
}

async function _pollSyncStatus() {
  if (_syncPollTimer) { clearTimeout(_syncPollTimer); _syncPollTimer = null; }
  let data;
  try {
    const r = await fetch('/api/sync_status');
    data = await r.json();
  } catch(e) {
    _syncPollTimer = setTimeout(_pollSyncStatus, 1500);
    return;
  }

  const phaseEl  = document.getElementById('sync-phase');
  const barEl    = document.getElementById('sync-bar');
  const countsEl = document.getElementById('sync-counts');
  const detailEl = document.getElementById('sync-detail');
  const btn      = document.getElementById('sync-lib-btn');
  const prog     = document.getElementById('sync-progress');

  const phaseLabels = {kits:'Kits', instruments:'Instruments', samples:'Samples', done:'Done', error:'Error'};
  if (phaseEl)  phaseEl.textContent  = phaseLabels[data.phase] || data.phase;

  const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
  if (barEl)    barEl.style.width    = pct + '%';

  let counts = '';
  if (data.total > 0) counts = `${data.done}/${data.total}`;
  if (data.mb_copied > 0) counts += `  ${data.mb_copied.toFixed(0)} MB`;
  if (countsEl) countsEl.textContent = counts;
  if (detailEl) detailEl.textContent = data.detail || '';

  if (data.phase === 'done') {
    if (phaseEl) phaseEl.textContent = '✓ Done';
    if (barEl)   barEl.style.width   = '100%';
    if (countsEl) countsEl.textContent = `${data.copied} copied, ${data.skipped} skipped`;
    if (detailEl) detailEl.textContent = '';
    if (btn) btn.disabled = false;
    setMsg('Library sync complete.');
    // Refresh instrument browser
    const idata = await api('/instruments');
    if (idata.instruments) { avail = idata.instruments; instMtimes = idata.mtimes || {}; renderInstruments(); }
    setTimeout(() => { if (prog) prog.style.display = 'none'; }, 4000);
    return;
  }

  if (data.phase === 'error') {
    if (phaseEl) phaseEl.style.color = '#e05060';
    if (phaseEl) phaseEl.textContent = '✗ Error';
    if (detailEl) detailEl.textContent = data.error || 'Unknown error';
    if (btn) btn.disabled = false;
    setMsg(data.error || 'Sync failed', true);
    return;
  }

  // Still running — poll again in 1s
  _syncPollTimer = setTimeout(_pollSyncStatus, 1000);
}

// ── "More like this" similarity search ────────────────────────────────────────
let _simRel = null;

function closeSimilar() {
  document.getElementById('similar-modal').classList.remove('open');
  _simRel = null;
}

async function openSimilar(rel) {
  _simRel = rel;
  const modal = document.getElementById('similar-modal');
  const short = rel.split('/').slice(1).join('/').replace(/\.sin$/i, '');
  document.getElementById('sim-src').textContent = '· ' + short;
  document.getElementById('sim-body').innerHTML = '<p style="color:#667;font-size:.78rem;padding:8px;">Analysing…</p>';
  modal.classList.add('open');
  let data;
  try {
    const r = await fetch('/api/similar?n=10&sin=' + encodeURIComponent(rel));
    data = await r.json();
  } catch(e) {
    document.getElementById('sim-body').innerHTML = '<p style="color:#e07080;font-size:.78rem;padding:8px;">Request failed.</p>';
    return;
  }
  if (_simRel !== rel) return;   // superseded by another click
  renderSimilar(data);
}

function renderSimilar(data) {
  const body = document.getElementById('sim-body');
  if (data.error) {
    body.innerHTML = `<p style="color:#e07080;font-size:.78rem;padding:8px;">${escHtml(data.error)}</p>`;
    return;
  }
  if (data.unfingerprinted) {
    body.innerHTML = `<p style="color:#c89040;font-size:.78rem;padding:8px;">
      No audio fingerprint for this instrument &mdash; its WAV may not be on this machine
      (mount the SD card or Sync the library first).</p>`;
    return;
  }
  if (!data.results || !data.results.length) {
    body.innerHTML = `<p style="color:#667;font-size:.78rem;padding:8px;">
      No neighbours yet. Build the similarity index below to fingerprint the whole library
      (${data.corpus||0} analysed so far).</p>`;
    return;
  }
  const rows = data.results.map(x => `
    <div class="sim-row">
      <button class="play-btn" title="Preview" onclick="event.stopPropagation();previewInstrument('${x.sin_rel}')">&#9654;</button>
      <span class="sim-name" title="${escHtml(x.sin_rel)}" onclick="openSimilar('${x.sin_rel}')" style="cursor:pointer;">${escHtml(x.name)}</span>
      <span class="sim-grp">${escHtml(x.group)}</span>
      <button class="ab-btn" title="Assign to selected pad, Layer A" onclick="event.stopPropagation();directAssign('${x.sin_rel}','a')">A</button>
      <button class="ab-btn" title="Assign to selected pad, Layer B" onclick="event.stopPropagation();directAssign('${x.sin_rel}','b')">B</button>
      <span class="sim-dist" title="distance (lower = closer)">${x.dist.toFixed(2)}</span>
    </div>`).join('');
  body.innerHTML = `<div style="font-size:.66rem;color:#667;margin:2px 0 4px;">
    ${data.results.length} closest of ${data.corpus} fingerprinted &middot; click a name to pivot</div>${rows}`;
}

let _fpPollTimer = null;

async function buildFingerprints() {
  const btn = document.getElementById('sim-build-btn');
  const prog = document.getElementById('sim-build');
  const start = await api('/fingerprint_build', {});
  if (start.error) { setMsg(start.error, true); }
  prog.style.display = '';
  if (btn) btn.disabled = true;
  _pollFingerprintStatus();
}

async function _pollFingerprintStatus() {
  if (_fpPollTimer) { clearTimeout(_fpPollTimer); _fpPollTimer = null; }
  let data;
  try {
    const r = await fetch('/api/fingerprint_status');
    data = await r.json();
  } catch(e) {
    _fpPollTimer = setTimeout(_pollFingerprintStatus, 1500);
    return;
  }
  const phaseEl = document.getElementById('sim-phase');
  const barEl   = document.getElementById('sim-bar');
  const cntEl   = document.getElementById('sim-counts');
  const detEl   = document.getElementById('sim-detail');
  const btn     = document.getElementById('sim-build-btn');

  const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
  if (barEl) barEl.style.width = pct + '%';
  if (phaseEl) phaseEl.textContent = data.phase === 'done' ? '✓ Index built'
                : data.phase === 'error' ? '✗ Error' : 'Fingerprinting';
  if (cntEl) cntEl.textContent = data.total > 0 ? `${data.done}/${data.total}` : '';
  if (detEl) detEl.textContent = (data.detail || '').split('/').slice(1).join('/');

  if (data.phase === 'done') {
    if (cntEl) cntEl.textContent = `${data.computed} analysed, ${data.cached} cached, ${data.skipped} skipped`;
    if (detEl) detEl.textContent = '';
    if (btn) btn.disabled = false;
    setMsg('Similarity index built.');
    if (_simRel) openSimilar(_simRel);   // refresh results now the corpus exists
    return;
  }
  if (data.phase === 'error') {
    if (detEl) { detEl.textContent = data.error || 'Unknown error'; detEl.style.color = '#e05060'; }
    if (btn) btn.disabled = false;
    setMsg(data.error || 'Fingerprint build failed', true);
    return;
  }
  _fpPollTimer = setTimeout(_pollFingerprintStatus, 800);
}

// ── Hex inspector ─────────────────────────────────────────────────────────────
async function hexInspect(padId) {
  const el = document.getElementById('hex-output-' + padId);
  if (el && el.style.display !== 'none') { el.style.display = 'none'; return; }
  setMsg('Loading hex dump…');
  const data = await api('/hex_inspect', {pad_id: padId});
  if (data.error) { setMsg(data.error, true); return; }
  if (el) {
    el.textContent   = data.output;
    el.style.display = '';
  }
  setMsg('');
}

// ── Layer blend preview ───────────────────────────────────────────────────────
async function previewBlend(padId) {
  const pad = pads.find(p => p.id === padId);
  if (!pad || !pad.layer_a_path || !pad.layer_b_path) { setMsg('Need both layers assigned', true); return; }
  try {
    if (!_blendCtx) _blendCtx = new AudioContext();
    if (_blendCtx.state === 'suspended') await _blendCtx.resume();
    const vol = previewVol * previewVelGain;
    const [rawA, rawB] = await Promise.all([
      fetch('/api/preview?sin=' + encodeURIComponent(pad.layer_a_path)).then(r => { if (!r.ok) throw new Error('A unavailable'); return r.arrayBuffer(); }),
      fetch('/api/preview?sin=' + encodeURIComponent(pad.layer_b_path)).then(r => { if (!r.ok) throw new Error('B unavailable'); return r.arrayBuffer(); }),
    ]);
    const [bufA, bufB] = await Promise.all([
      _blendCtx.decodeAudioData(rawA),
      _blendCtx.decodeAudioData(rawB),
    ]);
    const master = _blendCtx.createGain();
    master.gain.value = vol;
    master.connect(_blendCtx.destination);
    const gA = _blendCtx.createGain(); gA.gain.value = (pad.la_level || 95) / 127; gA.connect(master);
    const gB = _blendCtx.createGain(); gB.gain.value = (pad.lb_level || 95) / 127; gB.connect(master);
    const sA = _blendCtx.createBufferSource(); sA.buffer = bufA; sA.connect(gA); sA.start();
    const sB = _blendCtx.createBufferSource(); sB.buffer = bufB; sB.connect(gB); sB.start();
    setMsg(`Blend: ${pad.layer_a_name} + ${pad.layer_b_name}`);
  } catch(err) {
    setMsg('Blend preview failed: ' + err.message, true);
  }
}

// ── Script runner ─────────────────────────────────────────────────────────────
async function loadTools() {
  const data = await api('/tools');
  const el   = document.getElementById('tools-list');
  if (!el || !data.tools) return;
  el.innerHTML = data.tools.map(t =>
    `<div class="tool-item">
       <span title="${escHtml(t.name)}">${escHtml(t.label)}</span>
       <button class="btn-secondary" style="font-size:.65rem;padding:2px 6px;"
         onclick="runTool('${escHtml(t.name)}')">Run</button>
     </div>`
  ).join('');
}

async function runTool(name) {
  const outEl = document.getElementById('tool-output');
  if (outEl) { outEl.textContent = `Running ${name}…`; outEl.classList.add('visible'); }
  setMsg(`Running ${name}…`);
  const data = await api('/run_tool', {name});
  if (data.error) {
    if (outEl) outEl.textContent = 'Error: ' + data.error;
    setMsg(data.error, true);
    return;
  }
  if (outEl) outEl.textContent = data.output || '(no output)';
  if (data.kits) { kits = data.kits; renderKitList(); }
  setMsg(`${name} finished`);
}

// ── WAV import ────────────────────────────────────────────────────────────────
let stagedFiles = [];  // [{file, minVel, maxVel, rrIndex}]

function toggleImportForm() {
  const el = document.getElementById('import-wav-form');
  const nowVisible = el.style.display !== 'none';
  if (nowVisible) {
    hideImportForm();
  } else {
    el.style.display = '';
    document.getElementById('import-progress').textContent = '';
  }
}

function hideImportForm() {
  document.getElementById('import-wav-form').style.display = 'none';
  stagedFiles = [];
  renderStagedFiles();
  document.getElementById('import-name').value = '';
  document.getElementById('import-progress').textContent = '';
}

function handleImportDrop(e) {
  e.preventDefault();
  document.getElementById('import-drop-zone').classList.remove('drag-over');
  const files = [...e.dataTransfer.files].filter(f => f.name.toLowerCase().endsWith('.wav'));
  if (!files.length) { setMsg('Drop WAV files only', true); return; }
  stageFiles(files);
}

function velBands(n) {
  if (n <= 0) return [];
  if (n === 1) return [[1, 127]];
  const size = Math.floor(127 / n);
  return Array.from({length: n}, (_, i) => {
    const lo = 1 + i * size;
    const hi = i < n - 1 ? lo + size - 1 : 127;
    return [lo, hi];
  });
}

function stageFiles(files) {
  const wasEmpty = stagedFiles.length === 0;
  for (const f of files) {
    stagedFiles.push({file: f, minVel: 1, maxVel: 127, rrIndex: stagedFiles.length + 1});
  }
  if (wasEmpty && stagedFiles.length > 0) {
    document.getElementById('import-name').value = stagedFiles[0].file.name.replace(/\.wav$/i, '');
  }
  recalcVelBands();
  renderStagedFiles();
}

function recalcVelBands() {
  const mode  = document.getElementById('import-mode').value;
  const n     = stagedFiles.length;
  if (mode === 'roundrobin') {
    stagedFiles.forEach((f, i) => { f.minVel = 1; f.maxVel = 127; f.rrIndex = i + 1; });
  } else {
    const bands = velBands(n);
    stagedFiles.forEach((f, i) => { f.minVel = bands[i][0]; f.maxVel = bands[i][1]; f.rrIndex = 1; });
  }
}

function renderStagedFiles() {
  const el   = document.getElementById('import-staged-list');
  const mode = document.getElementById('import-mode') ? document.getElementById('import-mode').value : 'velocity';
  const isRR = mode === 'roundrobin';

  if (!stagedFiles.length) {
    el.innerHTML = '';
    const btn = document.getElementById('import-create-btn');
    if (btn) btn.disabled = true;
    return;
  }

  el.innerHTML = stagedFiles.map((f, i) => {
    const fname = escHtml(f.file.name.replace(/\.wav$/i, ''));
    const velPart = isRR
      ? `<span class="staged-rr">RR&nbsp;${f.rrIndex}</span>`
      : `<input class="staged-vel" type="number" min="0" max="127" value="${f.minVel}"
           onchange="stagedFiles[${i}].minVel=Math.min(127,Math.max(0,+this.value))" title="Min velocity">
         <span class="staged-sep">–</span>
         <input class="staged-vel" type="number" min="0" max="127" value="${f.maxVel}"
           onchange="stagedFiles[${i}].maxVel=Math.min(127,Math.max(0,+this.value))" title="Max velocity">`;
    return `<div class="staged-row">
      <span class="staged-name" title="${escHtml(f.file.name)}">${fname}</span>
      ${velPart}
      <button class="layer-btn" onclick="removeStagedFile(${i})" title="Remove">&#x2715;</button>
    </div>`;
  }).join('');

  const btn = document.getElementById('import-create-btn');
  if (btn) btn.disabled = false;
}

function removeStagedFile(idx) {
  stagedFiles.splice(idx, 1);
  if (!stagedFiles.length) document.getElementById('import-name').value = '';
  recalcVelBands();
  renderStagedFiles();
}

async function createInstrument() {
  if (!stagedFiles.length) return;
  const category  = document.getElementById('import-category').value.trim() || 'Custom';
  const name      = document.getElementById('import-name').value.trim()
                 || stagedFiles[0].file.name.replace(/\.wav$/i, '');
  const mode      = document.getElementById('import-mode').value;
  const normalize = document.getElementById('import-normalize')?.checked ?? false;
  const auto_map  = document.getElementById('import-automap')?.checked ?? false;
  const prog     = document.getElementById('import-progress');
  prog.style.color = '';
  prog.textContent = 'Reading files…';

  const btn = document.getElementById('import-create-btn');
  btn.disabled = true;

  try {
    const wavs = [];
    for (let i = 0; i < stagedFiles.length; i++) {
      const f   = stagedFiles[i];
      prog.textContent = `Reading ${i + 1}/${stagedFiles.length}: ${f.file.name}`;
      const buf = await f.file.arrayBuffer();
      // Chunked btoa to avoid call stack overflow on large files
      const u8  = new Uint8Array(buf);
      let bin   = '';
      for (let j = 0; j < u8.length; j += 8192) {
        bin += String.fromCharCode(...u8.subarray(j, j + 8192));
      }
      wavs.push({
        filename:  f.file.name,
        data:      btoa(bin),
        min_vel:   f.minVel,
        max_vel:   f.maxVel,
        rr_index:  f.rrIndex,
      });
    }

    prog.textContent = 'Creating instrument…';
    const resp = await fetch('/api/import_instrument', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({category, name, mode, normalize, auto_map, wavs}),
    });
    const data = await resp.json();
    if (data.error) {
      prog.style.color  = '#e08080';
      prog.textContent  = 'Error: ' + data.error;
      setMsg(data.error, true);
      btn.disabled = false;
    } else {
      avail = data.instruments;
      stagedFiles = [];
      document.getElementById('import-name').value = '';
      renderStagedFiles();
      renderInstruments();
      prog.style.color = '#88c090';
      prog.textContent = data.message;
      setMsg(data.message);
    }
  } catch (err) {
    prog.style.color = '#e08080';
    prog.textContent = 'Error: ' + err.message;
    btn.disabled = false;
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────
async function _doSave(path) {
  if (!path) { setMsg('No kit loaded', true); return; }
  const data = await api('/save', {path});
  if (data.error) { setMsg(data.error, true); return; }
  if (data.kits) {
    kits = data.kits;
    state_kitPath = path;
    if (data.lib_save_path) libSavePath = data.lib_save_path;
    if (data.sd_save_path)  sdSavePath  = data.sd_save_path;
    renderKitList();
  }
  setDirtyState(false, null);
  setMsg(data.message);
}
async function saveToLibrary() { await _doSave(libSavePath); }
async function saveToSD()      { await _doSave(sdSavePath);  }
async function saveCustom() {
  const path = document.getElementById('save-path').value.trim();
  if (!path) { setMsg('Enter a save path', true); return; }
  await _doSave(path);
}

// ── New kit ───────────────────────────────────────────────────────────────────
function showNewKitForm() {
  document.getElementById('new-kit-form').style.display = 'block';
  const inp = document.getElementById('new-kit-name');
  inp.value = '';
  inp.focus();
}
function cancelNewKit() {
  document.getElementById('new-kit-form').style.display = 'none';
}
async function confirmNewKit() {
  const name = document.getElementById('new-kit-name').value.trim() || 'New Kit';
  cancelNewKit();
  const data = await api('/new_kit', {name});
  if (data.error) { setMsg(data.error, true); return; }
  kits          = data.kits;
  kitName       = data.name;
  pads          = data.pads;
  libSavePath   = data.lib_save_path || '';
  sdSavePath    = data.sd_save_path  || '';
  state_kitPath = data.lib_save_path || '';
  selectedMapPad = pads.length ? pads[0].id : null;
  selectedPad    = pads.length ? {id: pads[0].id, layer: 'a'} : null;
  selectedGroup  = pads.length ? (PAD_TO_GROUP[pads[0].id] || null) : null;
  const kitNameEl2 = document.getElementById('kit-name');
  kitNameEl2.textContent = '— ' + kitName;
  kitNameEl2.contentEditable = 'true';
  document.getElementById('parse-warn').style.display = 'none';
  document.getElementById('save-lib-btn').disabled    = !libSavePath;
  document.getElementById('save-sd-btn').disabled     = !sdSavePath;
  document.getElementById('dup-btn').disabled         = false;
  document.getElementById('clear-pads-btn').disabled  = false;
  document.getElementById('save-path').value = libSavePath;
  setDirtyState(false, 0, []);
  renderKitList();
  renderPatchPanel();
  renderDrumMap();
  renderPadDetail();
  updateAssignBanner();
  setMsg(data.message);
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function checkStatus() {
  const s = await api('/status');
  const parts = [];
  if (s.user_mounted)   parts.push('&#x1F4BE; User: ' + s.user_path);
  else                  parts.push('&#x26A0; User card NOT mounted');
  if (s.preset_mounted) parts.push('&#x1F4C0; Preset: ' + s.preset_path + ' (read-only)');
  const volEl = document.getElementById('vol-status');
  volEl.innerHTML = parts.join(' \xB7 ');
  volEl.title = 'Cards are identified by their content, not their name. '
    + 'Saves only ever go to the user card; the factory preset card is never written.';
  const hint = document.getElementById('save-hint');
  if (hint) {
    const sep = (s.user_path || '').includes('\\') ? '\\' : '/';
    hint.textContent = s.user_mounted
      ? `Save to ${s.user_path}${sep}Kits${sep} to write back to the user card. Factory presets are never touched.`
      : 'Mount the user card to save back to SD.';
  }
}

(async () => {
  applyTheme();

  // Wire up SVG drag listeners once (they survive innerHTML replacements)
  const svgEl = document.getElementById('drum-svg');
  svgEl.addEventListener('mousemove', svgMouseMove);
  window.addEventListener('mouseup', e => {
    svgMouseUp(e);
    if (_velDrag?.lastVel != null) {
      setParam(_velDrag.padId, 'xfade_vel', _velDrag.lastVel);
    }
    _velDrag = null;
  });
  window.addEventListener('mousemove', e => {
    if (_velDrag) _applyVelDrag(e.clientX);
  });

  // Scroll-to-zoom on drum map; double-click resets
  document.getElementById('drum-svg-wrap').addEventListener('wheel', e => {
    e.preventDefault();
    const svg  = document.getElementById('drum-svg');
    const rect = svg.getBoundingClientRect();
    const mx   = svgView.x + (e.clientX - rect.left)  / rect.width  * svgView.w;
    const my   = svgView.y + (e.clientY - rect.top)   / rect.height * svgView.h;
    const factor = e.deltaY < 0 ? 0.85 : 1 / 0.85;
    const newW = Math.min(SVG_DEF_W * 3, Math.max(SVG_DEF_W * 0.2, svgView.w * factor));
    const newH = newW * SVG_DEF_H / SVG_DEF_W;
    svgView.x = mx - (e.clientX - rect.left)  / rect.width  * newW;
    svgView.y = my - (e.clientY - rect.top)   / rect.height * newH;
    svgView.w = newW;
    svgView.h = newH;
    applySvgView();
  }, {passive: false});
  document.getElementById('drum-svg-wrap').addEventListener('dblclick', e => {
    if (!e.target.closest('.map-pad')) {
      svgView = {x: 0, y: 0, w: SVG_DEF_W, h: SVG_DEF_H};
      applySvgView();
    }
  });

  // ── Drag-and-drop .skt kit loading ───────────────────────────────────────
  let _dndCount = 0;
  document.addEventListener('dragenter', e => {
    if ([...e.dataTransfer.types].includes('Files')) {
      _dndCount++;
      document.getElementById('drop-overlay').classList.add('active');
      e.preventDefault();
    }
  });
  document.addEventListener('dragover', e => {
    if ([...e.dataTransfer.types].includes('Files')) e.preventDefault();
  });
  document.addEventListener('dragleave', () => {
    _dndCount = Math.max(0, _dndCount - 1);
    if (!_dndCount) document.getElementById('drop-overlay').classList.remove('active');
  });
  document.addEventListener('drop', async e => {
    _dndCount = 0;
    document.getElementById('drop-overlay').classList.remove('active');
    if (e.target.closest && e.target.closest('#import-wav-form')) return;  // let WAV importer handle it
    const sktFiles = [...e.dataTransfer.files].filter(f => f.name.toLowerCase().endsWith('.skt'));
    if (!sktFiles.length) return;
    e.preventDefault();
    const file = sktFiles[0];
    setMsg(`Loading ${file.name}…`);
    try {
      const buf  = await file.arrayBuffer();
      const u8   = new Uint8Array(buf);
      let bin = '';
      for (let j = 0; j < u8.length; j += 8192) bin += String.fromCharCode(...u8.subarray(j, j + 8192));
      const resp = await fetch('/api/load_bytes', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({filename: file.name, data: btoa(bin)}),
      });
      const data = await resp.json();
      if (data.error) { setMsg(data.error, true); return; }
      applyKitData(data, '', {dirty: true});
      setMsg(data.message);
    } catch(err) {
      setMsg('Error loading file: ' + err.message, true);
    }
  });

  // Global keyboard shortcuts
  document.addEventListener('keydown', e => {
    // Don't intercept when focus is inside a text input
    const tag = document.activeElement?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    const mod = e.ctrlKey || e.metaKey;

    if (mod && !e.shiftKey && e.key === 'z') {
      e.preventDefault();
      if (undoCount > 0) undoLast();
      return;
    }
    if (mod && e.key === 's') {
      e.preventDefault();
      if (libSavePath) saveToLibrary();
      return;
    }
    if (!mod && e.key === 'Escape') {
      clearSelection();
      return;
    }
    if (!mod && e.key === ' ') {
      e.preventDefault();
      if (selectedPad) {
        const p = pads.find(p => p.id === selectedPad.id);
        const sinRel = p && (selectedPad.layer === 'a' ? p.layer_a_path : p.layer_b_path);
        if (sinRel) previewInstrument(sinRel);
      }
      return;
    }
    if (!mod && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      const keys = Object.keys(PAD_GROUPS);
      const cur  = selectedGroup ? keys.indexOf(selectedGroup) : -1;
      const next = Math.max(0, Math.min(keys.length - 1, cur + (e.key === 'ArrowRight' ? 1 : -1)));
      if (keys[next]) selectGroupFromPanel(keys[next]);
      return;
    }
    if (!mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      if (!selectedGroup) return;
      const g   = PAD_GROUPS[selectedGroup];
      if (!g)  return;
      const cur = g.pads.indexOf(selectedPad?.id ?? '');
      const idx = Math.max(0, Math.min(g.pads.length - 1, (cur < 0 ? 0 : cur) + (e.key === 'ArrowDown' ? 1 : -1)));
      const pid = g.pads[idx];
      if (pid) {
        selectedMapPad = pid;
        selectedPad    = {id: pid, layer: selectedPad?.layer ?? 'a'};
        updateAssignBanner(); renderPatchPanel(); renderDrumMap(); renderPadDetail();
      }
      return;
    }
  });

  applyPatchPanelState();
  updateLayoutBadge();

  // Apply saved browser toolbar prefs
  const volSlider = document.getElementById('preview-vol-slider');
  if (volSlider) volSlider.value = previewVol;
  const velSlider = document.getElementById('preview-vel-slider');
  try { if (velSlider) velSlider.value = parseFloat(localStorage.getItem('strike_previewVel') ?? '127') || 127; } catch(e) {}
  const sortEl = document.getElementById('inst-sort');
  if (sortEl) sortEl.value = instSort;
  const hoverChk = document.getElementById('hover-preview-chk');
  if (hoverChk) hoverChk.checked = hoverPreview;
  const autoChk = document.getElementById('auto-preview-chk');
  if (autoChk) autoChk.checked = autoPreview;

  // Kit-name inline rename
  const kitNameEl = document.getElementById('kit-name');
  kitNameEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); kitNameEl.blur(); }
    if (e.key === 'Escape') { kitNameEl.textContent = '— ' + kitName; kitNameEl.blur(); }
  });
  kitNameEl.addEventListener('blur', () => {
    if (kitNameEl.contentEditable !== 'true') return;
    const raw = kitNameEl.textContent.replace(/^—\s*/, '').trim();
    if (!raw || raw === kitName.replace(/\.skt$/i, '')) {
      kitNameEl.textContent = '— ' + kitName;
      return;
    }
    const newName = raw.endsWith('.skt') ? raw : raw + '.skt';
    kitName = newName;
    kitNameEl.textContent = '— ' + kitName;
    if (libSavePath) {
      const parts = libSavePath.replace(/\\/g, '/').split('/');
      parts[parts.length - 1] = newName;
      libSavePath = parts.join('/');
      document.getElementById('save-lib-btn').disabled = false;
      document.getElementById('save-path').value = libSavePath;
    }
    setMsg(`Kit name set to ${kitName} — save to apply`);
  });

  // Restore loop panel open state
  if (loopPanelOpen) {
    document.getElementById('loop-body').style.display = '';
    document.getElementById('loop-toggle-arrow').textContent = '▾';
    liveLoop = new LiveLoop();
    const bpmEl = document.getElementById('loop-bpm');
    if (bpmEl) bpmEl.value = liveLoop.bpm;
    renderLoopGrid();
  }

  await checkStatus();
  await loadKitList();
  await loadInstruments();
  loadTags();

  // Rehydrate if the server already has a kit loaded (page reload / second tab):
  // the served HTML is static, so without this the client starts blank.
  const sess = await api('/session');
  if (sess.loaded) {
    applyKitData(sess, sess.path, {dirty: sess.dirty, undoCount: sess.undo_count,
                                   historyLabels: sess.history_labels});
    setMsg(`Restored session — ${sess.name}`);
  }

  checkPaths();
  loadTools();
  renderPatchPanel();
  renderDrumMap();

  // Auto-save every 60 s while there are unsaved changes
  setInterval(async () => {
    if (undoCount > 0) await api('/autosave', {});
  }, 60000);

  // Check for crash-recovery autosaves from previous sessions
  (async () => {
    const data = await api('/autosaves');
    if (!data.autosaves?.length) return;
    const banner = document.createElement('div');
    banner.id = 'autosave-banner';
    const rows = data.autosaves.map(a =>
      `<span class="as-item"><strong>${escHtml(a.name)}</strong>`
      + `<a href="#" onclick="recoverAutosave('${escHtml(a.autosave_path)}','${escHtml(a.kit_path)}');return false;">Recover</a>`
      + `<a href="#" onclick="dismissAutosave('${escHtml(a.autosave_path)}',this);return false;">&#x2715;</a></span>`
    ).join('');
    if (data.autosaves.length === 1) {
      banner.innerHTML = `<span>&#9888;&nbsp;Unsaved changes found:</span>${rows}`;
    } else {
      banner.innerHTML =
        `<span>&#9888;&nbsp;Unsaved changes found for <strong>${data.autosaves.length} kits</strong></span>`
        + `<a href="#" onclick="document.getElementById('autosave-banner').classList.toggle('expanded');return false;">Show</a>`
        + `<a href="#" onclick="dismissAllAutosaves();return false;" style="opacity:.7;">Dismiss all</a>`
        + `<div id="as-list">${rows}</div>`;
    }
    banner.dataset.count = data.autosaves.length;
    document.body.prepend(banner);
  })();
})();

async function recoverAutosave(autosavePath, kitPath) {
  await openKit(autosavePath);
  if (kitPath) {
    document.getElementById('save-path').value = kitPath;
    libSavePath = kitPath;
    document.getElementById('save-lib-btn').disabled = false;
  }
  document.getElementById('autosave-banner')?.remove();
  setMsg('Recovered from autosave — review changes and save to keep them');
}

async function dismissAutosave(autosavePath, el) {
  await api('/delete_autosave', {path: autosavePath});
  const banner = document.getElementById('autosave-banner');
  if (el && banner && +banner.dataset.count > 1) {
    el.closest('.as-item')?.remove();
    banner.dataset.count = +banner.dataset.count - 1;
    if (+banner.dataset.count === 0) banner.remove();
  } else {
    banner?.remove();
  }
}

async function dismissAllAutosaves() {
  const data = await api('/autosaves');
  for (const a of (data.autosaves || [])) {
    await api('/delete_autosave', {path: a.autosave_path});
  }
  document.getElementById('autosave-banner')?.remove();
}
</script>
<div id="drop-overlay">&#x1F4C1; Drop .skt kit to load</div>

<!-- Kit diff modal -->
<div id="diff-modal" onclick="if(event.target===this)closeDiffModal()">
  <div class="diff-box">
    <h3>&#x1F50D; Compare kits</h3>
    <div class="diff-kit-sel">
      <label style="font-size:.72rem;color:#556;white-space:nowrap;">Compare against:</label>
      <select id="diff-kit-select" style="flex:1;padding:4px 6px;background:#0b0e15;border:1px solid #242c3d;color:#e8ebf2;border-radius:4px;font-size:.8rem;">
        <option value="">— select a kit —</option>
      </select>
      <button class="btn-primary" style="font-size:.8rem;padding:5px 14px;" onclick="runDiff()">Compare</button>
      <button class="btn-secondary" style="font-size:.8rem;padding:5px 10px;" onclick="closeDiffModal()">&#x2715;</button>
    </div>
    <div id="diff-result" class="diff-table"></div>
  </div>
</div>

<!-- Kit time machine modal -->
<div id="tm-modal" onclick="if(event.target===this)closeTimeMachine()">
  <div class="tm-box">
    <h3>&#x1F570;&#xFE0F; Kit time machine
      <span id="tm-kit-name" style="font-weight:400;color:#667;font-size:.74rem;"></span></h3>
    <div class="tm-toolbar">
      <button class="btn-primary" style="font-size:.75rem;padding:5px 12px;" onclick="tmSnapshotNow()">&#x1F4F8; Snapshot now</button>
      <label style="font-size:.68rem;color:#667;display:flex;align-items:center;gap:4px;cursor:pointer;">
        <input type="checkbox" id="tm-all-kits" style="width:auto;margin:0;" onchange="loadTimeMachine()"> show all kits</label>
      <span style="flex:1;"></span>
      <button class="btn-secondary" style="font-size:.75rem;padding:5px 10px;" onclick="closeTimeMachine()">&#x2715;</button>
    </div>
    <div class="tm-scrub">
      <span style="font-size:.66rem;color:#556;">newest</span>
      <input type="range" id="tm-slider" min="0" max="0" value="0" oninput="tmScrub(+this.value)">
      <span style="font-size:.66rem;color:#556;">oldest</span>
      <span class="tm-scrub-lbl" id="tm-scrub-lbl"></span>
    </div>
    <div class="tm-cols">
      <div class="tm-list" id="tm-list"></div>
      <div class="tm-detail">
        <div class="tm-cmp">
          <span>Compare</span>
          <select id="tm-cmp-a"></select>
          <span>&#x2192;</span>
          <select id="tm-cmp-b"></select>
          <button class="btn-secondary" style="font-size:.7rem;padding:3px 10px;" onclick="tmCompare()">Diff</button>
        </div>
        <div class="tm-diff" id="tm-diff"><div class="tm-empty">Pick a snapshot on the left, or choose two points to compare.</div></div>
      </div>
    </div>
  </div>
</div>

<!-- Sample relink modal -->
<div id="relink-modal" onclick="if(event.target===this)closeRelinkModal()">
  <div class="sin-box">
    <h3>&#x1F527; Fix broken instrument paths</h3>
    <div id="relink-body"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button id="relink-apply-btn" class="btn-primary" onclick="applyRelink()">Relink selected</button>
      <button class="btn-secondary" onclick="closeRelinkModal()">Close</button>
    </div>
  </div>
</div>

<!-- Kit FX editor modal -->
<div id="kitfx-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="sin-box" style="width:min(560px,94vw);">
    <h3>&#x1F39A; Kit FX</h3>
    <div id="kitfx-body" style="display:flex;flex-direction:column;"></div>
    <div style="display:flex;justify-content:flex-end;">
      <button class="btn-secondary" onclick="document.getElementById('kitfx-modal').classList.remove('open')">Close</button>
    </div>
  </div>
</div>

<!-- Trigger settings backup modal (SysEx) -->
<div id="trig-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="sin-box" style="width:min(620px,94vw);">
    <h3>&#x1F39B; Trigger settings backup</h3>
    <div id="trig-body" style="display:flex;flex-direction:column;"></div>
    <div style="display:flex;justify-content:flex-end;margin-top:8px;">
      <button class="btn-secondary" onclick="document.getElementById('trig-modal').classList.remove('open')">Close</button>
    </div>
  </div>
</div>

<!-- Instrument (.sin) editor modal -->
<div id="sin-modal" onclick="if(event.target===this)closeSinEditor()">
  <div class="sin-box">
    <h3>&#x1F39B; Instrument editor</h3>
    <div id="sin-body"></div>
  </div>
</div>

<!-- "More like this" similarity modal -->
<div id="similar-modal" onclick="if(event.target===this)closeSimilar()">
  <div class="sin-box" style="width:min(560px,94vw);">
    <h3>&#8776; Similar-sounding instruments
      <span id="sim-src" style="font-weight:400;color:#667;font-size:.74rem;"></span></h3>
    <div id="sim-body" style="min-height:60px;"></div>
    <div id="sim-build" class="sync-progress" style="display:none;margin-top:6px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span id="sim-phase" style="color:#88aacc;font-weight:600;"></span>
        <span id="sim-counts" style="color:#556;"></span>
      </div>
      <div class="sync-bar-wrap"><div id="sim-bar" class="sync-bar" style="width:0%"></div></div>
      <div id="sim-detail" class="sync-detail"></div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px;">
      <button id="sim-build-btn" class="btn-secondary" style="font-size:.72rem;" onclick="buildFingerprints()">&#8776; Build similarity index</button>
      <button class="btn-secondary" style="font-size:.72rem;" onclick="closeSimilar()">Close</button>
    </div>
  </div>
</div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access log

    _LOCAL_HOSTS = {'127.0.0.1', 'localhost', '[::1]'}

    def _local_request_ok(self) -> bool:
        """Reject requests that don't come from this machine's own browser.

        The server binds 127.0.0.1, but that alone doesn't stop a malicious
        webpage from firing cross-site POSTs at localhost (no CORS preflight for
        simple requests) or reading responses via DNS rebinding. Requiring a
        localhost Host header defeats rebinding; requiring a localhost Origin
        (when the browser sends one) defeats cross-site writes."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in self._LOCAL_HOSTS:
            return False
        origin = self.headers.get('Origin')
        if origin and origin.lower() not in ('null',):
            o_host = urlparse(origin).hostname
            if o_host not in ('127.0.0.1', 'localhost', '::1'):
                return False
        return True

    def _guard(self) -> bool:
        if self._local_request_ok():
            return True
        self.send_json({'error': 'Forbidden: request must originate from localhost'}, 403)
        return False

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if not self._guard():
            return
        parsed = urlparse(self.path)
        path   = parsed.path

        if path == '/' or path == '/index.html':
            body = HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(body))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/api/kits':
            self.send_json({'kits': find_kit_files()})
            return

        if path == '/api/instruments':
            refresh_available()
            mtimes = {}
            for k, v in state['avail'].items():
                try:
                    mtimes[k] = v.stat().st_mtime
                except OSError:
                    pass
            self.send_json({
                'instruments': {k: str(v) for k, v in state['avail'].items()},
                'mtimes': mtimes,
            })
            return

        if path == '/api/status':
            self.send_json(volume_status())
            return

        if path == '/api/session':
            # Current server-side kit state so a reloaded page can rehydrate
            # (the HTML is static; without this, a reload blanks the client
            # even though the server still holds the loaded kit).
            if state['kit_raw'] is None:
                self.send_json({'loaded': False})
                return
            user, _ = get_volumes()
            kit_name = state['kit_display'] or 'kit.skt'
            self.send_json({
                'loaded':         True,
                'name':           kit_name,
                'path':           state['kit_path'] or '',
                'pads':           self._pad_view(state['pads'], state['instruments']),
                'sd_save_path':   _sd_save_path(user, state['kit_path']) if state['kit_path'] else '',
                'lib_save_path':  str(LIBRARY_DIR / 'kits' / kit_name),
                'skt_lossless':   state['skt_lossless'],
                'dirty':          state['dirty'],
                'undo_count':     len(state['history']),
                'history_labels': _history_labels(),
            })
            return

        if path == '/api/selected':
            self.send_json(selected_view())
            return

        if path == '/api/kit_playback':
            try:
                self.send_json(kit_playback_manifest())
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return

        if path in ('/api/preview', '/api/wav'):
            qs      = parse_qs(parsed.query)
            sin_rel = qs.get('sin', [''])[0]
            idx     = int(qs.get('idx', ['-1'])[0])
            if not sin_rel:
                self.send_response(400); self.end_headers(); return
            wav_path = find_wav_for_sin_idx(sin_rel, idx) if idx >= 0 else find_wav_for_sin(sin_rel)
            if not wav_path:
                self.send_json({'error': 'WAV not found — is the preset SD card mounted?'}, 404)
                return
            try:
                wav_data = wav_path.read_bytes()
            except OSError as e:
                self.send_json({'error': str(e)}, 500)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', len(wav_data))
            self.send_header('Accept-Ranges', 'bytes')
            if path == '/api/wav':
                self.send_header('Cache-Control', 'max-age=3600')
            self.end_headers()
            self.wfile.write(wav_data)
            return

        if path == '/api/autosaves':
            self.send_json({'autosaves': find_autosaves()})
            return

        if path == '/api/sync_status':
            with _sync_lock:
                self.send_json(dict(_sync_state))
            return

        if path == '/api/fingerprint_status':
            with _fp_build_lock:
                self.send_json(dict(_fp_build_state))
            return

        if path == '/api/similar':
            qs      = parse_qs(parsed.query)
            sin_rel = qs.get('sin', [''])[0]
            n       = int(qs.get('n', ['10'])[0] or 10)
            if not sin_rel:
                self.send_json({'error': 'missing sin'}, 400); return
            try:
                self.send_json(similar_instruments(sin_rel, n))
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return

        if path == '/api/tools':
            self.send_json({'tools': list_tools()})
            return

        if path == '/api/kit_size':
            self.send_json(get_kit_size())
            return

        if path == '/api/waveform':
            sin_rel = parse_qs(parsed.query).get('sin', [''])[0]
            if not sin_rel:
                self.send_json({'error': 'missing sin'}, 400); return
            if sin_rel in _waveform_cache:
                self.send_json({'peaks': _waveform_cache[sin_rel]}); return
            wav_path = find_wav_for_sin(sin_rel)
            peaks = compute_waveform(wav_path) if wav_path else None
            _waveform_cache[sin_rel] = peaks
            self.send_json({'peaks': peaks})
            return

        if path == '/api/check_paths':
            self.send_json(check_paths())
            return

        if path == '/api/snapshots':
            try:
                qs = parse_qs(parsed.query)
                all_kits = qs.get('all', ['0'])[0] in ('1', 'true')
                self.send_json({'snapshots': list_snapshots(all_kits=all_kits),
                                'kit': _kit_key()})
            except Exception as e:
                self.send_json({'error': str(e)}, 400)
            return

        if path == '/api/kit_fx':
            try:
                self.send_json(kit_fx_view())
            except Exception as e:
                self.send_json({'error': str(e)}, 400)
            return

        if path == '/api/relink_suggest':
            try:
                self.send_json(relink_suggestions())
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return

        if path == '/api/sin_detail':
            sin_rel = parse_qs(parsed.query).get('sin', [''])[0]
            try:
                self.send_json(sin_detail(sin_rel))
            except Exception as e:
                self.send_json({'error': str(e)}, 400)
            return

        if path == '/api/tags':
            self.send_json({'tags': load_tags()})
            return

        if path == '/api/export_bundle':
            try:
                zip_bytes, fname = export_bundle()
            except Exception as e:
                self.send_json({'error': str(e)}, 400)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
            self.send_header('Content-Length', len(zip_bytes))
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        if path == '/api/export_kits':
            import datetime
            kits_dir  = LIBRARY_DIR / 'kits'
            kit_files = sorted(kits_dir.glob('*.skt')) if kits_dir.is_dir() else []
            out = {'exported_at': datetime.datetime.now().isoformat(), 'kits': []}
            for kf in kit_files:
                try:
                    raw = kf.read_bytes()
                    pads_data, insts = parse_skt(raw)
                    kit_entry = {'name': kf.name, 'pads': []}
                    for pad_id, payload in pads_data:
                        la_idx = struct.unpack_from('<H', payload, 4)[0]
                        lb_idx = struct.unpack_from('<H', payload, 24)[0]
                        def _u8(o): return payload[o] if o < len(payload) else 0
                        def _i8(o): v = _u8(o); return v if v < 128 else v - 256
                        kit_entry['pads'].append({
                            'id':       pad_id,
                            'midi':     _u8(52),
                            'layer_a':  insts[la_idx] if la_idx != 0xFFFF and la_idx < len(insts) else None,
                            'layer_b':  insts[lb_idx] if lb_idx != 0xFFFF and lb_idx < len(insts) else None,
                            'la_level': _u8(LA_LEVEL_OFF), 'la_pan': _i8(LA_PAN_OFF), 'la_pitch': _i8(LA_PITCH_OFF),
                            'la_fine':  _i8(LA_FINE_OFF),  'la_decay': _u8(LA_DECAY_OFF),
                            'la_fcut':  _u8(LA_FCUT_OFF),  'la_fflag': _u8(LA_FFLAG_OFF),
                        })
                    out['kits'].append(kit_entry)
                except Exception:
                    pass
            body = json.dumps(out, indent=2).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Disposition', 'attachment; filename="strike_kits_export.json"')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/api/midi_map_html':
            insts = state.get('instruments', [])
            pads_ = state.get('pads', [])
            pad_by_id = {p['id']: p for p in pads_}
            kit = (state.get('kit_path') or '').replace('\\','/').split('/')[-1] or 'Current Kit'

            def _inst_name(idx):
                if idx == NO_INSTRUMENT or idx >= len(insts): return '—'
                return insts[idx].rsplit('/', 1)[-1].removesuffix('.sin').removesuffix('.SIN')

            rows = []
            for pid in PAD_ORDER:
                p = pad_by_id.get(pid)
                if not p: continue
                pl     = p['payload']
                midi   = pl[MIDI_NOTE_OFF] if len(pl) > MIDI_NOTE_OFF else 0
                gm_lbl = GM_DRUMS.get(midi, '')
                la     = _inst_name(p['layer_a'])
                lb     = _inst_name(p['layer_b'])
                rows.append(f'<tr><td>{pid}</td><td>{PAD_LABEL.get(pid, pid)}</td>'
                            f'<td>{PAD_INPUT.get(pid, "")}</td>'
                            f'<td><b>{midi}</b>{" — " + gm_lbl if gm_lbl else ""}</td>'
                            f'<td>{la}</td><td>{lb}</td></tr>')

            html = f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<title>MIDI Map — {kit}</title>
<style>
  body{{font-family:system-ui,sans-serif;font-size:12px;color:#111;margin:1cm;}}
  h1{{font-size:16px;margin-bottom:4px;}}
  p.sub{{color:#666;font-size:10px;margin:0 0 10px;}}
  table{{border-collapse:collapse;width:100%;}}
  th,td{{border:1px solid #ccc;padding:4px 7px;text-align:left;white-space:nowrap;}}
  th{{background:#e8ecf2;font-weight:600;font-size:11px;}}
  tr:nth-child(even){{background:#f5f7fa;}}
  @media print{{body{{margin:.5cm;}}}}
</style>
</head><body>
<h1>MIDI Map — {kit}</h1>
<p class="sub">Generated by Strike Pro Remapper</p>
<table>
<tr><th>Pad</th><th>Zone</th><th>Input</th><th>MIDI Note</th><th>Layer A</th><th>Layer B</th></tr>
{"".join(rows)}
</table>
<script>window.onload=()=>window.print();</script>
</body></html>'''
            body = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def _pad_view(self, pads, instruments):
        out = []
        for p in pads:
            payload = p['payload']

            def name(idx):
                if idx == NO_INSTRUMENT or idx >= len(instruments):
                    return None
                s = instruments[idx]
                return s.rsplit('/', 1)[-1].replace('.sin', '').replace('.SIN', '')

            def ipath(idx):
                if idx == NO_INSTRUMENT or idx >= len(instruments):
                    return None
                return instruments[idx]

            def u8(off):
                return payload[off] if off < len(payload) else 0

            def i8(off):
                v = payload[off] if off < len(payload) else 0
                return v if v < 128 else v - 256

            midi = u8(MIDI_NOTE_OFF)
            mute_raw = u8(MUTE_GRP_OFF)
            out.append({
                'id':           p['id'],
                'label':        p['label'],
                'layer_a':      p['layer_a'],
                'layer_a_name': name(p['layer_a']),
                'layer_a_path': ipath(p['layer_a']),
                'layer_b':      p['layer_b'],
                'layer_b_name': name(p['layer_b']),
                'layer_b_path': ipath(p['layer_b']),
                # — editable parameters —
                'midi_note':    midi,
                'midi_name':    GM_DRUMS.get(midi, f'note {midi}'),
                'la_level':    u8(LA_LEVEL_OFF),
                'la_pan':      i8(LA_PAN_OFF),
                'la_pitch':    i8(LA_PITCH_OFF),
                'la_decay':    u8(LA_DECAY_OFF),
                'la_vel_dec':  u8(LA_VEL_DEC_OFF),
                'la_vel_pch':  u8(LA_VEL_PCH_OFF),
                'la_vel_flt':  u8(LA_VEL_FLT_OFF),
                'la_vel_vol':  u8(LA_VEL_VOL_OFF),
                'la_fcut':     u8(LA_FCUT_OFF),
                'la_fflag':    u8(LA_FFLAG_OFF),
                'la_fine':     i8(LA_FINE_OFF),
                'la_loop':     u8(LA_LOOP_OFF),
                'la_vel_min':  u8(LA_VEL_MIN_OFF),
                'la_vel_max':  u8(LA_VEL_MAX_OFF),
                'lb_level':    u8(LB_LEVEL_OFF),
                'lb_pan':      i8(LB_PAN_OFF),
                'lb_pitch':    i8(LB_PITCH_OFF),
                'lb_decay':    u8(LB_DECAY_OFF),
                'lb_vel_dec':  u8(LB_VEL_DEC_OFF),
                'lb_vel_pch':  u8(LB_VEL_PCH_OFF),
                'lb_vel_flt':  u8(LB_VEL_FLT_OFF),
                'lb_vel_vol':  u8(LB_VEL_VOL_OFF),
                'xfade_vel':   u8(XFADE_VEL_OFF),
                'lb_fcut':     u8(LB_FCUT_OFF),
                'lb_fflag':    u8(LB_FFLAG_OFF),
                'lb_fine':     i8(LB_FINE_OFF),
                'lb_loop':     u8(LB_LOOP_OFF),
                'reverb':      u8(REVERB_OFF),
                'fx1':         u8(FX1_OFF),
                'fx2':         u8(FX2_OFF),
                'eq_comp':     u8(EQ_COMP_OFF),
                'priority':    u8(PRIORITY_OFF),
                'note_off':    u8(NOTE_OFF_OFF),
                'midi_chan':   u8(MIDI_CHAN_OFF) + 1,
                'play_mode':   u8(PLAY_MODE_OFF),
                'gate_time':   u8(GATE_TIME_OFF),
                'mute_grp':     mute_raw,
                'input':        PAD_INPUT.get(p['id'], ''),
            })
        return out

    def do_POST(self):
        if not self._guard():
            return
        path = urlparse(self.path).path
        body = self.read_json()

        if path == '/api/new_kit':
            try:
                create_new_kit(body.get('name', 'New Kit'))
                user, _ = get_volumes()
                kit_name = Path(state['kit_path']).name
                self.send_json({
                    'name':          kit_name,
                    'message':       state['message'],
                    'pads':          self._pad_view(state['pads'], state['instruments']),
                    'sd_save_path':  _sd_save_path(user, state['kit_path']),
                    'lib_save_path': str(LIBRARY_DIR / 'kits' / kit_name),
                    'kits':          find_kit_files(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/load':
            try:
                load_kit(body['path'])
                user, _ = get_volumes()
                kit_name = Path(state['kit_path']).name
                self.send_json({
                    'name':         kit_name,
                    'message':      state['message'],
                    'pads':         self._pad_view(state['pads'], state['instruments']),
                    'sd_save_path':  _sd_save_path(user, state['kit_path']),
                    'lib_save_path': str(LIBRARY_DIR / 'kits' / kit_name),
                    'skt_lossless': state['skt_lossless'],
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/assign':
            try:
                assign_instrument(body['pad_id'], body['layer'], body['sin_rel'])
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/clear':
            try:
                clear_instrument(body['pad_id'], body['layer'])
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/select':
            state['sel_pad'] = body.get('pad_id') or None
            self.send_json({'ok': True})
            return

        if path == '/api/set_param':
            try:
                set_pad_param(body['pad_id'], body['param'], int(body['value']),
                              coalesce=bool(body.get('coalesce')))
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/kit_fx_set':
            try:
                set_kit_fx(body['param'], int(body['value']))
                self.send_json({
                    'message':        state['message'],
                    'fx':             kit_fx_view(),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/save':
            try:
                save_kit(body['path'])
                user, _ = get_volumes()
                kit_name = Path(state['kit_path']).name
                self.send_json({
                    'message':       state['message'],
                    'kits':          find_kit_files(),
                    'lib_save_path': str(LIBRARY_DIR / 'kits' / kit_name),
                    'sd_save_path':  _sd_save_path(user, state['kit_path']),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/import_wav':
            try:
                parsed_qs = parse_qs(urlparse(self.path).query)
                category  = parsed_qs.get('category', ['Custom'])[0]
                name      = parsed_qs.get('name',     ['Sample'])[0]
                length    = int(self.headers.get('Content-Length', 0))
                if length == 0:
                    self.send_json({'error': 'No file data received'})
                    return
                wav_data = self.rfile.read(length)
                sin_rel  = import_custom_wav(wav_data, category, name)
                self.send_json({
                    'message':     f'Imported → {sin_rel}',
                    'sin_rel':     sin_rel,
                    'instruments': {k: str(v) for k, v in state['avail'].items()},
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/import_instrument':
            try:
                body      = self.read_json()
                category  = body.get('category', 'Custom')
                name      = body.get('name', 'Sample')
                wavs      = body.get('wavs', [])
                normalize = bool(body.get('normalize', False))
                auto_map  = bool(body.get('auto_map', False))
                if not wavs:
                    self.send_json({'error': 'No WAV files provided'})
                    return
                wav_files = []
                for w in wavs:
                    wav_data  = base64.b64decode(w['data'])
                    filename  = w.get('filename', 'sample.wav')
                    min_vel   = int(w.get('min_vel', 1))
                    max_vel   = int(w.get('max_vel', 127))
                    rr_index  = int(w.get('rr_index', 1))
                    wav_files.append((wav_data, filename, min_vel, max_vel, rr_index))
                automap_note = ''
                if auto_map and len(wav_files) > 1:
                    # sort quiet → loud, then spread velocity bands across the order
                    wav_files.sort(key=lambda w: wav_peak(w[0]))
                    bands = _vel_bands(len(wav_files))
                    wav_files = [(data, fn, lo, hi, 1)
                                 for (data, fn, *_), (lo, hi) in zip(wav_files, bands)]
                    automap_note = ' | Auto-mapped by loudness: ' + ', '.join(
                        f'{Path(fn).stem}→{lo}-{hi}' for (_, fn, lo, hi, _) in wav_files)
                sin_rel, norm_notes = import_instrument(wav_files, category, name, normalize=normalize)
                msg = f'Created {len(wav_files)}-layer instrument → {sin_rel}' + automap_note
                if norm_notes:
                    msg += ' | Normalized: ' + '; '.join(norm_notes)
                self.send_json({
                    'message':     msg,
                    'sin_rel':     sin_rel,
                    'instruments': {k: str(v) for k, v in state['avail'].items()},
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/undo':
            try:
                undo()
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/copy_pad':
            try:
                copy_pad(body['from_id'], body['to_id'])
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/swap_pads':
            try:
                swap_pads(body['pad_id_a'], body['pad_id_b'])
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/batch_set_param':
            try:
                batch_set_param(body['pad_ids'], body['param'], int(body['value']))
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/set_tags':
            try:
                sin_rel = body.get('sin_rel', '')
                tags    = body.get('tags', [])
                set_instrument_tags(sin_rel, tags)
                self.send_json({'tags': load_tags()})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/import_bundle':
            try:
                zip_bytes = base64.b64decode(body['data_b64'])
                result = import_bundle(zip_bytes)
                msg = (f"Imported bundle: {result['kits']} kit(s), "
                       f"{result['instruments']} instrument(s), {result['samples']} sample(s)"
                       + (f", {result['skipped']} already present" if result['skipped'] else '')
                       + (f", {len(result['conflicts'])} conflict(s) kept existing" if result['conflicts'] else ''))
                self.send_json({
                    'message':     msg,
                    'kits':        find_kit_files(),
                    'instruments': {k: str(v) for k, v in state['avail'].items()},
                    'result':      result,
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/relink_apply':
            try:
                relink_apply(body.get('mapping', {}))
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/sin_update':
            try:
                self.send_json(sin_update(
                    body['sin_rel'],
                    params=body.get('params'),
                    cycle_random=body.get('cycle_random'),
                    mappings=body.get('mappings'),
                ))
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/sin_zones':
            try:
                self.send_json(sin_update_zones(
                    body['sin_rel'], body.get('zones', []),
                    cycle_random=body.get('cycle_random'),
                    params=body.get('params'),
                ))
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/sin_revert':
            try:
                self.send_json(sin_revert(body['sin_rel']))
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/batch_assign_csv':
            try:
                result = batch_assign_csv(body.get('assignments', []))
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                    'changed':        result['changed'],
                    'skipped':        result['skipped'],
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/diff_kit':
            try:
                result = diff_kit(body['path'])
                self.send_json(result)
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/snapshot':
            try:
                snap = create_snapshot(body.get('label', ''),
                                       body.get('kind', 'manual'),
                                       bool(body.get('pinned', False)))
                self.send_json({
                    'snapshot':  snap,
                    'snapshots': list_snapshots(),
                    'kit':       _kit_key(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/snapshot_diff':
            try:
                self.send_json(diff_snapshots(body['a'], body['b']))
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/snapshot_restore':
            try:
                entry = restore_snapshot(body['id'])
                self.send_json({
                    'message':        state['message'],
                    'label':          entry['label'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/snapshot_delete':
            try:
                delete_snapshot(body['id'])
                self.send_json({'snapshots': list_snapshots(), 'kit': _kit_key()})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/snapshot_pin':
            try:
                set_snapshot_pin(body['id'], bool(body.get('pinned', True)))
                self.send_json({'snapshots': list_snapshots(), 'kit': _kit_key()})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/clear_all_pads':
            try:
                clear_all_pads()
                self.send_json({
                    'message':        state['message'],
                    'pads':           self._pad_view(state['pads'], state['instruments']),
                    'dirty':          state['dirty'],
                    'undo_count':     len(state['history']),
                    'history_labels': _history_labels(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/duplicate_kit':
            try:
                new_path = duplicate_kit(body.get('name', ''))
                self.send_json({
                    'message': f'Saved copy as {Path(new_path).name}',
                    'kits':    find_kit_files(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/load_bytes':
            try:
                data_b64  = body.get('data', '')
                filename  = body.get('filename', 'kit.skt')
                raw_bytes = base64.b64decode(data_b64)
                load_kit_bytes(raw_bytes, filename)
                user, _ = get_volumes()
                lib_path = str(LIBRARY_DIR / 'kits' / Path(filename).name)
                self.send_json({
                    'name':          filename,
                    'message':       state['message'],
                    'pads':          self._pad_view(state['pads'], state['instruments']),
                    'lib_save_path': lib_path,
                    'sd_save_path':  _sd_save_path(user, lib_path) if user else '',
                    'skt_lossless':  state['skt_lossless'],
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/autosave':
            try:
                saved_path = autosave_kit()
                self.send_json({'path': saved_path or ''})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/delete_autosave':
            try:
                p = Path(body.get('path', ''))
                if p.suffix == '.skt' and '.autosave' in p.stem and p.exists():
                    p.unlink()
                self.send_json({'ok': True})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/sync_kits':
            try:
                result = sync_kits_from_sd()
                n = len(result['copied'])
                s = len(result['skipped'])
                msg = f'Synced {n} kit(s) from card' + (f' ({s} already present)' if s else '')
                self.send_json({'message': msg, 'kits': find_kit_files(), **result})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/sync_library':
            ok = start_sync_library()
            if ok:
                self.send_json({'message': 'Sync started'})
            else:
                self.send_json({'error': 'Sync already running'})
            return

        if path == '/api/fingerprint_build':
            ok = start_fingerprint_build()
            self.send_json({'message': 'Fingerprint build started'} if ok
                           else {'error': 'Fingerprint build already running'})
            return

        if path == '/api/hex_inspect':
            try:
                output = hex_inspect_pad(body.get('pad_id', ''))
                self.send_json({'output': output})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/run_tool':
            try:
                name = body.get('name', '')
                args = body.get('args', [])
                output = run_tool(name, args)
                # If the tool modified kit files, refresh the kit list
                self.send_json({'output': output, 'kits': find_kit_files()})
            except subprocess.TimeoutExpired:
                self.send_json({'error': 'Tool timed out (120 s limit)'})
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        if path == '/api/run_template':
            try:
                name = body.get('name', '')
                output = run_tool(name + '.py' if not name.endswith('.py') else name)
                # Reload the kit that the template just saved
                kit_path = state.get('kit_path') or ''
                if kit_path and Path(kit_path).exists():
                    load_kit(kit_path)
                user, _ = get_volumes()
                cur_path  = state.get('kit_path') or ''
                kit_name  = Path(cur_path).name if cur_path else ''
                self.send_json({
                    'output':        output,
                    'message':       state.get('message', f'Template {name} applied'),
                    'pads':          self._pad_view(state['pads'], state['instruments']),
                    'name':          kit_name,
                    'lib_save_path': str(LIBRARY_DIR / 'kits' / kit_name) if kit_name else '',
                    'sd_save_path':  _sd_save_path(user, cur_path),
                    'kits':          find_kit_files(),
                })
            except Exception as e:
                self.send_json({'error': str(e)})
            return

        self.send_response(404)
        self.end_headers()


def main():
    PORT = 8765
    # Threading so one slow request (e.g. an SD scan) can't freeze the whole app
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f"Strike Pro Remapper running at {url}")
    print("Make sure SD card volumes are mounted before browsing instruments.")
    print("Press Ctrl-C to quit.\n")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == '__main__':
    main()
