"""Portable local setlists. Never opens a card or changes the active editor kit."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import uuid
import wave
from strike_remapper.library_assets import local_file, wav_info

from strike_remapper.formats import parse_skt, build_skt, parse_sin, NO_INSTRUMENT

MAX_BYTES = 1024 * 1024
MAX_KIT_BYTES = 2 * 1024 * 1024
MAX_SETS = 50
MAX_ROWS = 128


class Conflict(ValueError):
    pass


def text(value, label, limit, empty=True):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(f'{label} must be text of at most {limit} characters.')
    value = value.strip()
    if not empty and not value:
        raise ValueError(f'{label} is required.')
    return value


def relative(value):
    value = text(value, 'Kit path', 240, False)
    parts = value.split('/')
    if any(p in ('', '.', '..') or any(c in p for c in '\\:*?"<>|\x00') for p in parts) or value.startswith('/') or any(ord(c) < 32 for c in value):
        raise ValueError('Choose a kit inside the library kits folder.')
    if not value.lower().endswith('.skt') or value.lower().endswith('.autosave.skt'):
        raise ValueError('Choose a saved .skt kit, not a recovery copy.')
    return value


def validate(value):
    if not isinstance(value, dict) or value.get('format') != 'strike-setlist' or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Choose a Strike setlist JSON file (version 1).')
    rows = value.get('entries')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(f'A setlist holds up to {MAX_ROWS} songs.')
    if type(value.get('numbered')) is not bool:
        raise ValueError('Numbered filenames must be on or off.')
    clean = {'format': 'strike-setlist', 'version': 1,
             'name': text(value.get('name'), 'Setlist name', 80, False),
             'notes': text(value.get('notes', ''), 'Show notes', 2000),
             'numbered': value['numbered'], 'entries': []}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each song needs a kit reference.')
        clean['entries'].append({'kit': relative(row.get('kit')),
                                 'song': text(row.get('song', ''), 'Song title', 100),
                                 'output': text(row.get('output', ''), 'Output name', 100),
                                 'notes': text(row.get('notes', ''), 'Song notes', 500)})
    return clean


def filename(stem, position=None):
    """Conservative portable ASCII name, 26 characters including the extension."""
    stem = re.sub(r'[^A-Za-z0-9 _-]', '', stem).strip() or 'Kit'
    if stem.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        stem = 'Kit ' + stem
    prefix = f'{position:03d} ' if position is not None else ''
    return prefix + stem[:22-len(prefix)].rstrip() + '.skt'


def inside(root, rel):
    candidate = root / rel
    root = root.resolve()
    candidate.resolve().relative_to(root)
    if any(p.is_symlink() for p in (candidate, *candidate.parents) if p != root and root in p.parents):
        raise ValueError('Linked library files are not supported by Setlist Builder.')
    return candidate


def read_bounded(path, limit):
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'{path.name} is too large to open here.')
    return data


class Store:
    # Call mutations under the editor STATE_LOCK; revisions also protect stale tabs.
    def __init__(self, library, catalog=None):
        self.library = Path(library).resolve()
        self.folder = inside(self.library, 'setlists')
        self.kits = inside(self.library, 'kits')
        self.catalog = catalog

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise ValueError('Invalid setlist identifier.')
        return inside(self.folder, identifier + '.json')

    def load(self, identifier):
        data = read_bounded(self.path(identifier), MAX_BYTES)
        return {'id': identifier, 'revision': hashlib.sha256(data).hexdigest(),
                'document': validate(json.loads(data))}

    def listing(self):
        items = []
        for path in sorted(self.folder.glob('*.json')):
            if not re.fullmatch(r'[0-9a-f]{32}', path.stem):
                continue
            if len(items) >= MAX_SETS:
                raise ValueError('More than 50 setlists are in this library. Move extras out before continuing.')
            try:
                items.append(self.load(path.stem))
            except (OSError, ValueError) as exc:
                items.append({'id': path.stem, 'error': str(exc)})
        kits = []
        truncated = False
        for folder, dirs, files in os.walk(self.kits, followlinks=False):
            safe_dirs = []
            for name in sorted(dirs):
                if name.startswith('.'):
                    continue
                try:
                    inside(self.kits, str((Path(folder) / name).relative_to(self.kits)))
                    safe_dirs.append(name)
                except ValueError:
                    pass
            dirs[:] = safe_dirs
            for name in sorted(files):
                path = Path(folder) / name
                if name.startswith('.') or not name.lower().endswith('.skt') or name.lower().endswith('.autosave.skt'):
                    continue
                rel = path.relative_to(self.kits).as_posix()
                try:
                    inside(self.kits, relative(rel))
                except ValueError:
                    continue
                kits.append({'kit': rel, 'name': path.stem, 'path': str(path)})
                if len(kits) > 2000:
                    kits.pop()
                    truncated = True
                    break
            if truncated:
                break
        return {'setlists': items, 'kits': kits, 'kits_truncated': truncated}

    def save(self, document, identifier=None, revision=None):
        clean = validate(document)
        if identifier:
            current = self.load(identifier)
            if current['revision'] != revision:
                raise Conflict('This setlist changed in another page. Export your draft, then reopen the saved version.')
        else:
            if len(list(self.folder.glob('*.json'))) >= MAX_SETS:
                raise ValueError('This library holds 50 setlists. Export and delete an older one first.')
            identifier = uuid.uuid4().hex
        data = (json.dumps(clean, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ValueError('Setlist exceeds 1 MB.')
        path = self.path(identifier)
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            with tmp.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return self.load(identifier)

    def delete(self, identifier, revision):
        if self.load(identifier)['revision'] != revision:
            raise Conflict('This setlist changed in another page. Reopen it before deleting.')
        self.path(identifier).unlink()
        return {'deleted': True}

    def copy_kit(self, source, name):
        source = inside(self.kits, relative(source))
        name = text(name, 'New kit name', 22, False)
        target_name = filename(name)
        if target_name != name + '.skt':
            raise ValueError('Use up to 22 letters, numbers, spaces, hyphens or underscores. Reserved device names are not allowed.')
        target = inside(self.kits, target_name)
        if any(p.name.casefold() == target_name.casefold() for p in self.kits.iterdir()):
            raise ValueError('A kit with that name already exists. Choose a different name.')
        data = read_bounded(source, MAX_KIT_BYTES)
        parse_skt(data)
        # Exact bytes, exclusive creation; never overwrite or rebuild the source.
        with target.open('xb') as handle:
            try:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                handle.close()
                target.unlink(missing_ok=True)
                raise
        return {'kit': target_name}

    def check(self, document):
        clean = validate(document)
        catalog = set()
        if self.catalog and Path(self.catalog).is_file():
            raw = json.loads(Path(self.catalog).read_text(encoding='utf-8'))
            # Catalog keys provide positive evidence only; absence proves nothing.
            catalog = set(raw.get('instruments', raw))
        rows = []
        assets = {}
        audio_cache = {}
        names = [filename(row['output'] or PurePosixPath(row['kit']).stem, i+1 if clean['numbered'] else None)
                 for i, row in enumerate(clean['entries'])]
        for i, row in enumerate(clean['entries']):
            issues = []
            row_assets = set()
            def issue(level, message):
                issues.append({'level': level, 'message': message})
            if sum(n.casefold() == names[i].casefold() for n in names) > 1:
                issue('blocker', 'Output name is used more than once. Enable numbering or change the output name.')
            try:
                path = inside(self.kits, row['kit'])
                data = read_bounded(path, MAX_KIT_BYTES)
                assets['kits/' + names[i]] = {'path': 'kits/' + names[i], 'source': 'kits/' + row['kit'], 'bytes': len(data), 'kind': 'kit'}
                row_assets.add('kits/' + names[i])
                kit_raw, pads, instruments, tail = parse_skt(data)
                if build_skt(kit_raw, pads, instruments, tail) != data:
                    issue('blocker', 'Kit does not round-trip exactly. Review it in the editor before preparing it.')
                used = set()
                for pad in pads:
                    for key in ('layer_a', 'layer_b'):
                        idx = pad.get(key, NO_INSTRUMENT)
                        if idx == NO_INSTRUMENT:
                            continue
                        if type(idx) is not int or not 0 <= idx < len(instruments):
                            issue('blocker', 'Kit has an invalid instrument reference.')
                        else:
                            used.add(instruments[idx])
                local, factory, unknown = 0, 0, 0
                for rel in sorted(used):
                    parts = rel.replace('\\', '/').split('/')
                    if any(p in ('', '.', '..') or ':' in p for p in parts) or rel.startswith('/'):
                        issue('blocker', 'Unsafe instrument reference: ' + rel)
                        continue
                    sin = inside(self.library, 'instruments/' + '/'.join(parts))
                    if sin.is_file():
                        sin_data = read_bounded(sin, MAX_KIT_BYTES)
                        instrument = parse_sin(sin_data)
                        sin_key = sin.relative_to(self.library).as_posix()
                        assets[sin_key] = {'path': sin_key, 'source': sin_key, 'bytes': len(sin_data), 'kind': 'instrument'}
                        row_assets.add(sin_key)
                        samples = {m['sample'] for m in instrument['mappings']}
                        if not samples:
                            issue('warning', 'Local instrument has no sample mappings: ' + rel)
                        for sample in sorted(samples):
                            try:
                                wav = local_file(self.library, ('instruments', 'samples'), sample)
                                if wav is None:
                                    issue('blocker', 'Missing local sample: ' + sample)
                                    continue
                                key = wav.relative_to(self.library).as_posix()
                                if key not in audio_cache:
                                    if len(audio_cache) >= 4096:
                                        raise ValueError('Collection exceeds 4096 local samples; split the setlist')
                                    try:
                                        audio_cache[key] = wav_info(wav)
                                    except (OSError, ValueError, wave.Error, EOFError) as exc:
                                        audio_cache[key] = str(exc)
                                info = audio_cache[key]
                                if isinstance(info, str):
                                    raise ValueError(info)
                                assets[key] = {'path': 'Samples/' + sample.replace('\\', '/'), 'source': key,
                                               'bytes': info['bytes'], 'pcm_bytes': info['pcm_bytes'], 'kind': 'sample'}
                                row_assets.add(key)
                            except (OSError, ValueError, wave.Error, EOFError):
                                issue('blocker', 'Sample could not be checked (missing, ambiguous, unsafe, truncated or unsupported): ' + sample)
                        local += 1
                    elif rel in catalog:
                        factory += 1
                    else:
                        unknown += 1
                if unknown:
                    issue('warning', f'{unknown} instrument reference(s) cannot be verified from the local library or factory catalog.')
                if local or factory:
                    issue('info', f'{local} local instrument(s); {factory} factory-catalog reference(s). Local sample headers checked; factory samples and card contents are not checked.')
                if not used:
                    issue('warning', 'No instruments are assigned to this kit.')
            except (OSError, ValueError, IndexError, KeyError, AssertionError, struct.error) as exc:
                issue('blocker', 'Saved kit could not be checked: ' + str(exc))
            sample_bytes = sum(assets[k].get('pcm_bytes', 0) for k in row_assets)
            if sample_bytes > 200 * 1024 * 1024:
                issue('warning', 'Local decoded samples exceed 200 MiB. Review module memory limits before deployment.')
            status = 'blocked' if any(v['level'] == 'blocker' for v in issues) else 'review' if any(v['level'] == 'warning' for v in issues) else 'checked'
            rows.append({'position': i+1, 'filename': names[i], 'status': status, 'issues': issues, 'local_sample_bytes': sample_bytes})
        destinations = {}
        for asset in assets.values():
            destinations.setdefault(asset['path'].casefold(), set()).add(asset['source'])
        collisions = sorted(k for k, sources in destinations.items() if len(sources) > 1)
        return {'rows': rows, 'preview': {'files': sorted(assets.values(), key=lambda a: a['path']),
                'local_bytes': sum(a['bytes'] for a in assets.values()),
                'samples': sum(a['kind'] == 'sample' for a in assets.values()),
                'collisions': collisions, 'writes_enabled': False}, 'scope': 'Preview only: local saved kits, instruments and WAV headers. Shared local files counted once. Factory sample sizes, card space, existing destination files and final deployment paths are unverified. Batch writes are disabled; use individual Deploy to Module preflight. Nothing has been deployed.'}
