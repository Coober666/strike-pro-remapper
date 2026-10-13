"""Bounded sample-based balance estimates, never module loudness measurements."""
import hashlib
import io
import json
import math
import statistics
import wave

from strike_remapper.formats import NO_INSTRUMENT, parse_sin, build_skt
from strike_remapper.library_assets import local_file, wav_info

WINDOW_SECONDS = 0.5
MAX_SAMPLES = 96
SCOPE = ('Estimates from the first 0.5 seconds of up to eight highest-velocity mappings per layer '
         '(96 unique local WAVs maximum). RMS averages channel energy; peak is window-only. '
         'Linear layer × instrument levels approximate playback. Pitch, envelopes, velocity response, '
         'effects, pan, round-robin selection and the module mixer are not modeled. '
         'Compare similar sounds by ear; quiet samples may be intentional. WAVs are never changed.')


def window(path):
    info = wav_info(path)
    with wave.open(str(path), 'rb') as audio:
        data = audio.readframes(min(info['frames'], int(info['rate'] * WINDOW_SECONDS)))
    width = info['width']
    count = len(data) // width
    if not count:
        raise ValueError('Empty sample window')
    peak, energy = 0, 0
    for offset in range(0, len(data), width):
        sample = int.from_bytes(data[offset:offset+width], 'little', signed=True)
        peak = max(peak, abs(sample))
        energy += sample * sample
    scale = 2 ** (8 * width - 1)
    return info, data, math.sqrt(energy / count) / scale, peak / scale


def preview(library, reference):
    path = local_file(library, ('instruments', 'samples'), reference)
    if path is None:
        raise ValueError('Local sample unavailable')
    info, data, _, _ = window(path)
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((info['channels'], info['width'], info['rate'], 0, 'NONE', 'not compressed'))
        audio.writeframes(data)
    return output.getvalue()


def db(value):
    return round(20 * math.log10(value), 2) if value > 0 else None


def analyze(library, state):
    if not state.get('kit_raw') or not state.get('pads'):
        raise ValueError('Open a kit first')
    if len(state['pads']) > 64:
        raise ValueError('Kit exceeds the 64-pad analysis limit')
    cache, rows, notes, sources = {}, [], [], []
    for pad in state['pads']:
        for layer, offset in (('a', 6), ('b', 26)):
            idx = pad.get('layer_' + layer, NO_INSTRUMENT)
            if idx == NO_INSTRUMENT:
                continue
            key = pad['id'] + ':' + layer
            row = {'id': key, 'pad': pad['id'], 'label': pad.get('label', pad['id']),
                   'layer': layer, 'level': pad['payload'][offset], 'suggested': None, 'reasons': []}
            rows.append(row)
            try:
                if type(idx) is not int or not 0 <= idx < len(state['instruments']):
                    raise ValueError('Invalid instrument reference')
                rel = state['instruments'][idx]
                sin = local_file(library, ('instruments',), rel)
                if sin is None:
                    raise ValueError('Instrument is not in the local library')
                with sin.open('rb') as handle:
                    raw = handle.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('Instrument exceeds analysis limit')
                sources.append(hashlib.sha256(raw).hexdigest())
                detail = parse_sin(raw)
                mappings = detail['mappings']
                if not mappings:
                    raise ValueError('No sample mappings')
                high = max(m['vmax'] for m in mappings)
                refs = sorted({m['sample'] for m in mappings if m['vmax'] == high})
                if len(refs) > 8:
                    raise ValueError('More than eight highest-velocity samples; layer skipped')
                measured = []
                for ref in refs:
                    if ref not in cache:
                        if len(cache) >= MAX_SAMPLES:
                            raise ValueError('96-sample analysis limit reached; layer skipped')
                        path = local_file(library, ('instruments', 'samples'), ref)
                        if path is None:
                            raise ValueError('A highest-velocity sample is missing locally')
                        info, data, rms, peak = window(path)
                        cache[ref] = (rms, peak, hashlib.sha256(data).hexdigest(), info)
                    measured.append(cache[ref])
                inst_level = detail['params']['level']
                if inst_level > 127 or row['level'] > 127:
                    raise ValueError('Invalid level; review this instrument in the editor')
                gain = row['level'] / 127 * inst_level / 127
                rms = statistics.median(m[0] for m in measured) * gain
                peak = max(m[1] for m in measured) * gain
                row.update(rms_db=db(rms), peak_db=db(peak), group=detail['params']['group'],
                           instrument_level=inst_level, sample=refs[0], sample_count=len(refs),
                           velocity=high, rms=rms, peak=peak,
                           vmin=pad['payload'][19 if layer == 'a' else 39],
                           vmax=pad['payload'][20] if layer == 'a' else 127)
                if rms == 0:
                    row['reasons'].append('Silent window or muted level; no automatic gain suggestion.')
                if peak >= 0.98:
                    row['reasons'].append('Measured window has little peak headroom; check for clipping by ear.')
            except (OSError, ValueError, wave.Error, EOFError, IndexError, KeyError):
                row['reasons'].append('Not measured: missing, unsafe, ambiguous or unsupported local sample/instrument, or analysis limit reached. Sync/check this sound separately.')

    def suggest(row, delta, reason):
        row['reasons'].append(reason)
        if not row.get('rms') or not row['level']:
            return
        target = max(1, min(127, round(row['level'] * 10 ** (max(-6, min(6, delta)) / 20))))
        # Multiple warnings on a layer choose the more conservative level.
        if target != row['level']:
            row['suggested'] = min(target, row['suggested']) if row['suggested'] is not None else target

    valid = [r for r in rows if r.get('rms') and r['vmin'] <= r['vmax']]
    for row in valid:
        peers = [r for r in valid if r['group'] == row['group'] and r['layer'] == row['layer']]
        if len({r['pad'] for r in peers}) >= 3:
            median = statistics.median(r['rms_db'] for r in peers)
            delta = median - row['rms_db']
            if abs(delta) >= 6:
                suggest(row, delta, f'{abs(delta):.1f} dB {"quieter" if delta > 0 else "louder"} than the median of {len(peers)} same-group layers. Adjustment capped at 6 dB; timbre/intent may differ.')
    for pad in state['pads']:
        pair = [r for r in valid if r['pad'] == pad['id']]
        if len(pair) != 2:
            continue
        a, b = pair
        delta = a['rms_db'] - b['rms_db']
        overlap = max(a['vmin'], b['vmin']) <= min(a['vmax'], b['vmax'])
        if abs(delta) >= 6:
            louder = a if delta > 0 else b
            suggest(louder, -abs(delta), f'A/B estimate differs by {abs(delta):.1f} dB. {"Both layers can overlap." if overlap else "Listen for a level jump at the velocity boundary."}')
        if overlap and a['peak'] + b['peak'] >= 0.98:
            notes.append(f'{pad.get("label", pad["id"])}: overlapping layers may exceed peak headroom (worst-case peak sum; phase and velocity not modeled).')
    payload = {'rows': rows, 'notes': notes, 'scope': SCOPE}
    kit = build_skt(state['kit_raw'], state['pads'], state['instruments'], state.get('tail', b''))
    evidence = [hashlib.sha256(kit).hexdigest(), str(library), state.get('kit_path'), state.get('param_rev', 0), sources,
                sorted((key, value[2], value[3]) for key, value in cache.items()), payload]
    payload['token'] = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return payload


def selected_changes(report, token, selected):
    if token != report['token']:
        raise ValueError('Kit or sample evidence changed. Analyze again before applying.')
    if not isinstance(selected, list) or not selected or len(selected) > 48 or any(not isinstance(x, str) for x in selected):
        raise ValueError('Select at least one suggested adjustment')
    if len(set(selected)) != len(selected):
        raise ValueError('Duplicate selection')
    available = {r['id']: r for r in report['rows'] if r['suggested'] is not None}
    if any(key not in available for key in selected):
        raise ValueError('Selection is no longer available. Analyze again.')
    return [available[key] for key in selected]
