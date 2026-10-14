"""CSV batches validate completely before changing a temporary kit."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app


class CSVAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        original, library = copy.deepcopy(app.state), app.LIBRARY_DIR
        self.addCleanup(lambda: (app.state.clear(), app.state.update(original), app.set_library_root(library)))
        app.set_library_root(Path(self.tmp.name))
        app.create_new_kit('CSV fixture')
        app.state['avail'] = {'Test/One.sin': Path(self.tmp.name) / 'one.sin',
                              'Test/Two.sin': Path(self.tmp.name) / 'two.sin'}
        app.state['dirty'] = False
        app.state['history'] = []
        self.pad = app.state['pads'][0]['id']

    def row(self, **changes):
        return {'pad_id': self.pad, 'layer': 'a', 'sin_rel': 'Test/One.sin', **changes}

    def test_invalid_later_row_keeps_entire_state(self):
        for invalid in (None, self.row(layer='c'), self.row(pad_id='UNKNOWN'),
                        self.row(sin_rel=[]), self.row(pad_id=''), self.row(layer=1)):
            with self.subTest(invalid=invalid):
                before = copy.deepcopy(app.state)
                with self.assertRaises(ValueError):
                    app.batch_assign_csv([self.row(), invalid])
                self.assertEqual(app.state, before)

    def test_empty_or_malformed_batch_is_rejected_without_history(self):
        for value in (None, {}, 'csv', []):
            with self.subTest(value=value):
                before = copy.deepcopy(app.state)
                with self.assertRaises(ValueError):
                    app.batch_assign_csv(value)
                self.assertEqual(app.state, before)

    def test_valid_layers_share_one_undo_and_missing_instruments_are_reported(self):
        before = app._snapshot()
        result = app.batch_assign_csv([self.row(pad_id=self.pad.lower(), layer=' A '),
            self.row(layer='b', sin_rel='Test/Two.sin'), self.row(sin_rel='Missing.sin')])
        self.assertEqual(result['changed'], 2)
        self.assertEqual(result['skipped'], ['Missing.sin'])
        self.assertEqual(len(app.state['history']), 1)
        self.assertTrue(app.state['dirty'])
        self.assertEqual(app.state['pads'][0]['layer_a'], 0)
        self.assertEqual(app.state['pads'][0]['layer_b'], 1)
        app.undo()
        self.assertEqual(app.state['pads'], before['pads'])
        self.assertEqual(app.state['instruments'], before['instruments'])

    def test_missing_and_unchanged_assignments_do_not_dirty_or_consume_undo(self):
        before = copy.deepcopy(app.state)
        self.assertEqual(app.batch_assign_csv([self.row(sin_rel='Missing.sin')])['changed'], 0)
        self.assertEqual(app.state, before)
        app.batch_assign_csv([self.row()])
        app.state['dirty'] = False
        before = copy.deepcopy(app.state)
        self.assertEqual(app.batch_assign_csv([self.row()])['changed'], 0)
        self.assertEqual(app.state, before)


if __name__ == '__main__':
    unittest.main()
