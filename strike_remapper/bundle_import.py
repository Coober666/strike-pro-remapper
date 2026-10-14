"""Preflight bundle archives before publishing new local-library files."""
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

MAX_ZIP_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_SIN_BYTES = 16 * 1024 * 1024


class ImportStopped(ValueError):
    def __init__(self, completed, detail):
        self.completed = completed
        super().__init__(f'Bundle import stopped after {completed} completed new file(s). '
                         f'{detail} Earlier completed files were kept. Refresh the library '
                         'and check free space/permissions before retrying; existing files are never overwritten.')


def parts(reference):
    values = reference.replace('\\', '/').split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}
    if any(not p or p in ('.', '..') or p.endswith((' ', '.')) or
           p.split('.')[0].upper() in reserved or any(c in p for c in ':*?"<>|') or
           any(ord(c) < 32 for c in p) for p in values):
        raise ValueError('Unsafe or non-portable path in bundle. Nothing imported.')
    return tuple(values)


def destination(library, kind, reference):
    root = Path(library).resolve()
    path = root / kind / Path(*parts(reference))
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise ValueError('Bundle destination leaves the library. Nothing imported.') from None
    for item in (path, *path.parents):
        if item == root:
            break
        try:
            reparse = getattr(item.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        except FileNotFoundError:
            reparse = False
        if item.is_symlink() or reparse:
            raise ValueError('Linked bundle destinations are not supported. Nothing imported.')
    return path


def same_file(left, right):
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as a, right.open('rb') as b:
        while chunk := a.read(1024 * 1024):
            if chunk != b.read(len(chunk)):
                return False
    return True


def publish(source, target):
    """Exclusive create; a handled copy failure removes only this new partial file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming:
        outgoing = target.open('xb')
        try:
            with outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except BaseException:
            try:
                target.unlink()
            except OSError as cleanup:
                raise ValueError(f'Could not remove incomplete file {target.name}; inspect it before retrying.') from cleanup
            raise


def import_archive(zip_bytes, library, classify, parse_samples):
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError('Bundle exceeds the 512 MiB ZIP limit. Split it into smaller bundles.')
    counts = {'kits': 0, 'instruments': 0, 'samples': 0, 'skipped': 0, 'conflicts': [], 'kit_names': []}
    with tempfile.TemporaryDirectory(prefix='strike-bundle-') as scratch:
        staged, names, total = [], set(), 0
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                if len(z.infolist()) > MAX_ENTRIES:
                    raise ValueError('Bundle exceeds 10,000 entries. Nothing imported.')
                for info in z.infolist():
                    if stat.S_ISLNK(info.external_attr >> 16):
                        raise ValueError('Linked archive entries are not supported. Nothing imported.')
                    entry_parts = parts(info.filename.rstrip('/') if info.is_dir() else info.filename)
                    if info.is_dir() or entry_parts[-1] in ('manifest.json', '.DS_Store'):
                        continue
                    key = '/'.join(entry_parts).casefold()
                    if key in names:
                        raise ValueError('Duplicate archive paths are ambiguous. Nothing imported.')
                    names.add(key)
                    if entry_parts[-1].rsplit('.', 1)[-1].lower() not in ('skt', 'sin', 'wav', 'wave'):
                        continue
                    limit = MAX_SIN_BYTES if entry_parts[-1].lower().endswith('.sin') else MAX_FILE_BYTES
                    if info.file_size > limit or total + info.file_size > MAX_TOTAL_BYTES:
                        raise ValueError('Bundle exceeds extraction limits (512 MiB/file, 16 MiB/instrument, 2 GiB total). Nothing imported.')
                    target = Path(scratch) / str(len(staged))
                    size = 0
                    with z.open(info) as incoming, target.open('xb') as outgoing:
                        while chunk := incoming.read(1024 * 1024):
                            size += len(chunk)
                            if size > limit or total + size > MAX_TOTAL_BYTES:
                                raise ValueError('Bundle exceeds extraction limits. Nothing imported.')
                            outgoing.write(chunk)
                    if size != info.file_size:
                        raise ValueError('Truncated bundle entry. Nothing imported.')
                    total += size
                    staged.append((entry_parts, target))
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
            raise ValueError('Could not read or stage this ZIP (corrupt, encrypted, unsupported, or insufficient temporary space). Nothing imported.') from exc
        if not staged:
            raise ValueError('No .skt, .sin, or .wav files found in ZIP — not a kit/instrument bundle.')
        sample_paths = {}
        for entry_parts, source in staged:
            if entry_parts[-1].lower().endswith('.sin'):
                try:
                    references = parse_samples(source.read_bytes())
                except Exception:
                    continue  # Preserve compatibility with unrecognized instrument variants.
                for reference in references:
                    safe = '/'.join(parts(reference))
                    sample_paths.setdefault(safe.rsplit('/', 1)[-1].lower(), safe)
        plan, destinations = [], {}
        for entry_parts, source in staged:
            kind, relative = classify(entry_parts, sample_paths)
            destination(library, kind, relative)  # Preflight every destination before publication.
            key = (kind, relative.casefold())
            if key in destinations and destinations[key] != relative:
                raise ValueError('Bundle destinations differ only by case. Nothing imported.')
            destinations[key] = relative
            plan.append((kind, relative, source))
        for kind, relative, source in plan:
            try:
                target = destination(library, kind, relative)
                if kind == 'kits':
                    base, suffix, counter = target.stem, target.suffix, 2
                    while target.exists() and not same_file(target, source):
                        target = destination(library, kind, f'{base} ({counter}){suffix}')
                        counter += 1
                    counts['kit_names'].append(target.name)
                if target.exists():
                    if same_file(target, source):
                        counts['skipped'] += 1
                    else:
                        counts['conflicts'].append(relative)
                    continue
                publish(source, target)
                counts[kind] += 1
            except Exception as exc:
                detail = str(exc).replace('Nothing imported.', '').strip() if isinstance(exc, ValueError) else 'A destination could not be written.'
                raise ImportStopped(sum(counts[k] for k in ('kits', 'instruments', 'samples')), detail) from exc
    return counts
