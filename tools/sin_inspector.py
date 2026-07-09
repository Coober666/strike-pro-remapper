#!/usr/bin/env python3
"""
sin_inspector.py — identify the binary format of a .sin instrument file.

Usage:
    python tools/sin_inspector.py path/to/instrument.sin
    python tools/sin_inspector.py E:\\Instruments\\Kicks\\   # inspect all .sin in a folder

Determines whether .sin files are plain WAV, AIFF, or a proprietary format,
which tells us whether live audio playback is feasible without format conversion.
"""
import struct
import sys
from pathlib import Path

# Magic-byte signatures → (format name, notes)
SIGNATURES = [
    (b'RIFF',       'RIFF container'),
    (b'FORM',       'IFF / AIFF container'),
    (b'fLaC',       'FLAC audio'),
    (b'OggS',       'Ogg container (Vorbis/Opus)'),
    (b'\xff\xfb',  'MP3 frame (MPEG-1 Layer III)'),
    (b'\xff\xf3',  'MP3 frame (MPEG-2 Layer III)'),
    (b'\xff\xf2',  'MP3 frame (MPEG-2.5 Layer III)'),
    (b'ID3',        'MP3 with ID3v2 tag'),
    (b'\x1aE\xdf\xa3', 'Matroska / WebM'),
]


def classify(data: bytes) -> tuple[str, str]:
    """Return (format_tag, detail_string)."""
    magic4 = data[:4]

    for sig, desc in SIGNATURES:
        if data[:len(sig)] == sig:
            detail = desc

            if magic4 == b'RIFF' and len(data) >= 12:
                riff_type = data[8:12]
                detail += f' / {riff_type.decode("ascii", errors="replace")}'
                if riff_type == b'WAVE':
                    return 'WAV', detail
                return 'RIFF', detail

            if magic4 == b'FORM' and len(data) >= 12:
                form_type = data[8:12]
                detail += f' / {form_type.decode("ascii", errors="replace")}'
                if form_type == b'AIFF':
                    return 'AIFF', detail
                if form_type == b'AIFC':
                    return 'AIFC', detail
                return 'IFF', detail

            return desc.split()[0].upper(), detail

    return 'UNKNOWN', f'magic={magic4.hex(" ")}'


def inspect_wav(data: bytes) -> dict:
    """Parse WAV header fields from a RIFF/WAVE file."""
    info = {}
    if len(data) < 44:
        return info
    pos = 12
    while pos + 8 <= len(data):
        chunk_id   = data[pos:pos + 4]
        chunk_size = struct.unpack_from('<I', data, pos + 4)[0]
        if chunk_id == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, pos + 8)
            info['audio_fmt']   = fmt[0]  # 1=PCM, 3=IEEE float, 65534=extensible
            info['channels']    = fmt[1]
            info['sample_rate'] = fmt[2]
            info['byte_rate']   = fmt[3]
            info['bits']        = fmt[5]
            info['duration_s']  = len(data) / fmt[3] if fmt[3] else 0
        elif chunk_id == b'data':
            info['data_bytes'] = chunk_size
        pos += 8 + chunk_size + (chunk_size % 2)  # chunks are word-aligned
    return info


def hexdump(data: bytes, n: int = 128) -> None:
    chunk = data[:n]
    print(f'\n  First {min(n, len(data))} bytes:')
    for i in range(0, len(chunk), 16):
        row    = chunk[i:i + 16]
        hex_   = ' '.join(f'{b:02x}' for b in row)
        ascii_ = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f'    {i:04x}  {hex_:<48}  |{ascii_}|')


def inspect_file(path: Path) -> None:
    data = path.read_bytes()
    fmt_tag, detail = classify(data)

    bar = '-' * 60
    print(f'\n{bar}')
    print(f'  File  : {path.name}')
    print(f'  Size  : {len(data):,} bytes  ({len(data) / 1024:.1f} KB)')
    print(f'  Format: {fmt_tag}  —  {detail}')

    if fmt_tag == 'WAV':
        info = inspect_wav(data)
        if info:
            fmt_name = {1: 'PCM', 3: 'IEEE float', 65534: 'Extensible'}.get(
                info.get('audio_fmt', 0), f"fmt={info.get('audio_fmt')}"
            )
            print(f'  WAV   : {info.get("channels", "?")}ch  '
                  f'{info.get("sample_rate", "?"):,} Hz  '
                  f'{info.get("bits", "?")} bit  '
                  f'{fmt_name}  '
                  f'~{info.get("duration_s", 0):.3f}s')
        print('  Playback: YES — standard WAV, readable by Python wave / soundfile')
    elif fmt_tag in ('AIFF', 'AIFC'):
        print('  Playback: YES — AIFF/AIFC readable by Python aifc module')
    elif fmt_tag == 'UNKNOWN':
        print('  Playback: UNKNOWN — proprietary or custom header; needs further analysis')
        hexdump(data, 128)
    else:
        print(f'  Playback: MAYBE — {fmt_tag} may need a library (e.g. pydub)')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        files = sorted(target.rglob('*.sin'))
        if not files:
            print(f'No .sin files found in {target}')
            sys.exit(1)
        seen_formats: dict[str, int] = {}
        for f in files:
            data = f.read_bytes()
            fmt_tag, detail = classify(data)
            seen_formats[fmt_tag] = seen_formats.get(fmt_tag, 0) + 1

        # Summary mode for directories
        print(f'\nScanned {len(files)} .sin files in {target}')
        print('Format summary:')
        for tag, count in sorted(seen_formats.items(), key=lambda x: -x[1]):
            print(f'  {tag:<12} {count:4d} files')

        # Show one example of each format
        shown = set()
        for f in files:
            data = f.read_bytes()
            fmt_tag, _ = classify(data)
            if fmt_tag not in shown:
                inspect_file(f)
                shown.add(fmt_tag)
        return

    if not target.exists():
        print(f'ERROR: file not found: {target}')
        sys.exit(1)

    inspect_file(target)


if __name__ == '__main__':
    main()
