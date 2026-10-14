"""Synthetic balance measurements, stale evidence, explicit apply and single undo."""
import copy
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app
from strike_remapper.balance import analyze, window, preview, selected_changes


def tone(path, amplitude, width=2, stereo=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b''.join((amplitude if i % 2 else -amplitude).to_bytes(width, 'little', signed=True) +
                      ((-amplitude if i % 2 else amplitude).to_bytes(width, 'little', signed=True) if stereo else b'')
                      for i in range(24000))
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((2 if stereo else 1, width, 48000, 0, 'NONE', 'not compressed'))
        audio.writeframes(frames)


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        old_state = copy.deepcopy(app.state); old_library = app.LIBRARY_DIR
        self.addCleanup(lambda: (app.state.clear(), app.state.update(old_state), app.set_library_root(old_library)))
        app.set_library_root(self.root)
        app.create_new_kit('Balance fixture')
        for i, amplitude in enumerate((12000, 12000, 1200, 30000)):
            ref = f'Test/{i}.sin'; sample = f'Test/{i}.wav'
            path = self.root / 'instruments' / ref; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(app._build_sin([(sample, 1, 127, 1)]))
            tone(self.root / 'samples' / sample, amplitude)
            app.state['instruments'].append(ref)
            pad = app.state['pads'][i]; pad['layer_a'] = i
            struct.pack_into('<H', pad['payload'], 4, i)
        app.state['history'] = []
        app.state['dirty'] = False

    def test_known_rms_stereo_energy_24bit_and_silence(self):
        for width in (2, 3):
            path = self.root / f'measure{width}.wav'
            tone(path, 2 ** (width*8-2), width, True)
            _, _, rms, peak = window(path)
            self.assertAlmostEqual(rms, .5); self.assertAlmostEqual(peak, .5)
        tone(path, 0, 3)
        self.assertEqual(window(path)[2:], (0, 0))

    def test_direction_missing_samples_and_no_mutation_or_card_discovery(self):
        before = copy.deepcopy(app.state)
        with patch.object(app, 'get_volumes', side_effect=AssertionError('no cards')):
            result = analyze(self.root, app.state)
        self.assertEqual(app.state, before)
        rows = result['rows']
        self.assertGreater(rows[2]['suggested'], rows[2]['level'])
        self.assertLess(rows[3]['suggested'], rows[3]['level'])
        (self.root / 'samples/Test/0.wav').unlink()
        result = analyze(self.root, app.state)
        self.assertNotIn('rms_db', result['rows'][0])
        self.assertIn('rms_db', result['rows'][1])

    def test_single_undo_and_stale_or_unselected_never_mutate(self):
        result = analyze(self.root, app.state)
        before = copy.deepcopy(app.state)
        wavs = {p: p.read_bytes() for p in self.root.rglob('*.wav')}
        for selected in ([], ['unknown'], [result['rows'][2]['id']]*2):
            with self.assertRaises(ValueError):
                app.apply_balance(result['token'], selected)
            self.assertEqual(app.state, before)
        selected = [r['id'] for r in result['rows'] if r['suggested'] is not None]
        original_path = app.state['kit_path']
        app.state['kit_path'] = str(self.root / 'Different kit.skt')
        with self.assertRaises(ValueError):
            app.apply_balance(result['token'], selected)
        app.state['kit_path'] = original_path
        app.apply_balance(result['token'], selected)
        self.assertEqual(len(app.state['history']), 1)
        self.assertTrue(app.state['dirty'])
        with self.assertRaises(ValueError):
            app.apply_balance(result['token'], selected)
        app.undo()
        self.assertEqual(app.state['pads'], before['pads'])
        self.assertEqual(app.state['instruments'], before['instruments'])
        for path, data in wavs.items():
            self.assertEqual(path.read_bytes(), data)
        fresh = analyze(self.root, app.state)
        tone(self.root / 'samples/Test/2.wav', 2000)
        with self.assertRaises(ValueError):
            app.apply_balance(fresh['token'], selected)

    def test_clipping_warning_muted_layers_and_truncated_wavs(self):
        pad = app.state['pads'][0]
        pad['layer_a'] = 3; pad['layer_b'] = 3
        pad['payload'][6] = 127; pad['payload'][26] = 127
        pad['payload'][19] = 1; pad['payload'][20] = 127; pad['payload'][39] = 1
        result = analyze(self.root, app.state)
        self.assertIn('peak headroom', str(result['notes']))
        pad['payload'][6] = 0
        self.assertIsNone(analyze(self.root, app.state)['rows'][0]['suggested'])
        path = self.root / 'samples/Test/3.wav'
        path.write_bytes(path.read_bytes()[:-2])
        self.assertNotIn('rms_db', analyze(self.root, app.state)['rows'][0])
        with self.assertRaises(ValueError):
            window(path)

    def test_ab_transition_overlap_warning_and_bounded_preview(self):
        pad = app.state['pads'][0]; pad['layer_b'] = 2
        struct.pack_into('<H', pad['payload'], 24, 2)
        result = analyze(self.root, app.state)
        self.assertIn('A/B estimate', str(result))
        pad['payload'][19] = 1; pad['payload'][20] = 50; pad['payload'][39] = 51
        self.assertIn('velocity boundary', str(analyze(self.root, app.state)))
        data = preview(self.root, 'Test/0.wav')
        with wave.open(io.BytesIO(data), 'rb') as audio:
            self.assertEqual(audio.getnframes(), 24000)
        for ref in ('../private.wav', 'C:/private.wav', '/private.wav'):
            with self.assertRaises(ValueError):
                preview(self.root, ref)


if __name__ == '__main__':
    unittest.main()
