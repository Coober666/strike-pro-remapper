#!/usr/bin/env python3
"""
copy_samples.py — copy kits and instruments from SD cards to a local library.

Creates a library/ folder next to this repo so you can work offline without
the SD cards mounted.

Usage:
    python tools/copy_samples.py            # copy kits + .sin metadata only
    python tools/copy_samples.py --kits     # kits only
    python tools/copy_samples.py --instr    # .sin instrument metadata only
    python tools/copy_samples.py --wav      # WAV audio files only (~3-4 GB)
    python tools/copy_samples.py --all      # everything (kits + .sin + WAV)
    python tools/copy_samples.py --dry-run  # show what would be copied

Output layout:
    library/
        kits/
            MyKit.skt
            ...
        instruments/
            Kicks/
                Big Boom.sin
                ...
            Chinas and Splashes/
                ChinaSabBlackwell_Bow/
                    ChinaSabBlackwell_Bow_-18.208r-4.88p0.wav
                    ...
"""
import argparse
import platform
import shutil
import string as _string
import sys
from pathlib import Path

LIBRARY_DIR = Path(__file__).resolve().parent.parent / 'library'


def _get_windows_volume_label(root: Path) -> str:
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


def find_volumes():
    """Return list of (label, root_path) for mounted Strike Pro SD card volumes."""
    found = []
    if platform.system() == 'Windows':
        for letter in _string.ascii_uppercase[3:]:
            root = Path(f'{letter}:\\')
            if (root / 'Instruments').is_dir():
                label = _get_windows_volume_label(root) or f'{letter}:'
                found.append((label, root))
    else:
        vols_dir = Path('/Volumes')
        if vols_dir.is_dir():
            for v in sorted(vols_dir.iterdir()):
                if (v / 'Instruments').is_dir():
                    found.append((v.name, v))
    return found


def copy_kits(vol_root: Path, label: str, dest: Path, dry_run: bool) -> int:
    """
    Copy .skt files from vol_root to dest, deduped by filename.
    Prefers files found in a 'Kits' subfolder over root-level copies
    (the Strike Pro stores kits in both places on user cards).
    """
    by_name: dict[str, Path] = {}
    for kit in sorted(vol_root.rglob('*.skt')):
        if kit.name.startswith('.') or kit.name.startswith('._'):
            continue
        existing = by_name.get(kit.name)
        if existing is None or len(kit.parts) > len(existing.parts):
            by_name[kit.name] = kit

    count = 0
    for name, kit in sorted(by_name.items()):
        out = dest / name
        if dry_run:
            print(f'  [dry] {kit}  →  {out}')
        else:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(kit, out)
            print(f'  copied {name}')
        count += 1
    return count


def copy_instruments(vol_root: Path, label: str, dest: Path, dry_run: bool) -> int:
    inst_root = vol_root / 'Instruments'
    count = 0
    for sin in sorted(inst_root.rglob('*.sin')):
        rel = sin.relative_to(inst_root)
        out = dest / rel
        if dry_run:
            print(f'  [dry] {sin}  →  {out}')
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                shutil.copy2(sin, out)
                print(f'  copied {rel}')
        count += 1
    return count


def copy_wavs(vol_root: Path, label: str, dest: Path, dry_run: bool) -> tuple[int, int]:
    """
    Copy WAV audio files from the Samples folder on vol_root to dest.
    Returns (count_copied, total_bytes_copied).
    Skips files that already exist at the destination (safe to re-run).
    """
    # WAVs live in Samples/, not Instruments/ — .sin files in Instruments/ reference
    # paths relative to Samples/ (e.g. 'Kicks/BigBoom.wav' → Samples/Kicks/BigBoom.wav)
    samples_root = vol_root / 'Samples'
    if not samples_root.is_dir():
        return 0, 0

    # Collect WAVs (case-insensitive suffix match for cross-platform safety)
    wavs = sorted(p for p in samples_root.rglob('*') if p.suffix.lower() in ('.wav', '.wave'))

    if not wavs:
        return 0, 0

    total_size = sum(w.stat().st_size for w in wavs)
    print(f'  {len(wavs):,} WAV files  ({total_size / 1e9:.1f} GB total on card)')

    if dry_run:
        for w in wavs[:10]:
            rel = w.relative_to(samples_root)
            print(f'  [dry] {rel}')
        if len(wavs) > 10:
            print(f'  [dry] ... and {len(wavs) - 10} more')
        return len(wavs), total_size

    count = 0
    copied_bytes = 0
    skipped = 0
    for i, wav in enumerate(wavs, 1):
        rel = wav.relative_to(samples_root)
        out = dest / rel
        if out.exists():
            skipped += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wav, out)
        sz = wav.stat().st_size
        copied_bytes += sz
        count += 1
        # Progress every 100 files or every 100 MB
        if count % 100 == 0 or copied_bytes % (100 * 1024 * 1024) < sz:
            pct = i / len(wavs) * 100
            print(f'  {i:5d}/{len(wavs)}  ({pct:.0f}%)  {copied_bytes/1e6:.0f} MB copied so far')

    if skipped:
        print(f'  Skipped {skipped} already-present file(s)')
    return count, copied_bytes


def main():
    ap = argparse.ArgumentParser(description='Copy Strike Pro SD card files to local library.')
    ap.add_argument('--kits',    action='store_true', help='Copy .skt kit files')
    ap.add_argument('--instr',   action='store_true', help='Copy .sin instrument metadata files')
    ap.add_argument('--wav',     action='store_true', help='Copy WAV audio files (~3-4 GB from preset card)')
    ap.add_argument('--all',     action='store_true', help='Copy kits + .sin + WAV files')
    ap.add_argument('--dry-run', action='store_true', help='Print what would be copied, do not write')
    args = ap.parse_args()

    # Determine which operations to run
    # Default (no flags): kits + .sin only (same as before, WAV is opt-in due to size)
    nothing_specified = not (args.kits or args.instr or args.wav or args.all)
    do_kits  = args.kits  or args.all or nothing_specified
    do_instr = args.instr or args.all or nothing_specified
    do_wavs  = args.wav   or args.all
    dry      = args.dry_run

    if do_wavs and not dry:
        print('WAV copy requested — this may take several minutes and ~3-4 GB of disk space.')
        print('Files already present in the library will be skipped.\n')

    volumes = find_volumes()
    if not volumes:
        print('No Strike Pro SD card volumes found. Plug in the card reader and try again.')
        sys.exit(1)

    print(f'Found {len(volumes)} volume(s):')
    for label, root in volumes:
        print(f'  [{label}]  {root}')

    if dry:
        print('\n(DRY RUN — nothing will be written)\n')

    total_kits = total_instr = total_wavs = total_wav_bytes = 0

    for label, root in volumes:
        print(f'\n── [{label}] {root} ──')

        if do_kits:
            dest_kits = LIBRARY_DIR / 'kits'
            print(f'  Kits → {dest_kits}')
            n = copy_kits(root, label, dest_kits, dry)
            total_kits += n
            print(f'  {n} kit(s) {"would be " if dry else ""}copied')

        if do_instr:
            dest_instr = LIBRARY_DIR / 'instruments'
            inst_count = sum(1 for _ in (root / 'Instruments').rglob('*.sin')) \
                if (root / 'Instruments').is_dir() else 0
            if inst_count == 0:
                print(f'  Instruments: (none found — is the preset card also mounted?)')
            else:
                print(f'  Instruments (.sin) → {dest_instr}')
                n = copy_instruments(root, label, dest_instr, dry)
                total_instr += n
                print(f'  {n} .sin file(s) {"would be " if dry else ""}copied')

        if do_wavs:
            dest_wavs = LIBRARY_DIR / 'instruments'
            inst_root = root / 'Instruments'
            if not inst_root.is_dir():
                print(f'  WAV audio: (no Instruments folder on this card)')
            else:
                print(f'  WAV audio → {dest_wavs}')
                n, nb = copy_wavs(root, label, dest_wavs, dry)
                total_wavs += n
                total_wav_bytes += nb
                verb = 'would be copied' if dry else 'copied'
                print(f'  {n:,} WAV file(s) {verb}  ({nb/1e6:.0f} MB)')

    print(f'\nDone.')
    if do_kits:  print(f'  Kits: {total_kits}')
    if do_instr: print(f'  Instruments (.sin): {total_instr}')
    if do_wavs:  print(f'  WAV audio: {total_wavs:,} files  ({total_wav_bytes/1e6:.0f} MB)')
    if not dry:
        print(f'Library at: {LIBRARY_DIR}')


if __name__ == '__main__':
    main()
