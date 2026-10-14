"""Support reports expose only explicitly selected diagnostics."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.support import identity, report


class SupportTests(unittest.TestCase):
    def test_manifest_identity_and_private_state_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / 'BETA-MANIFEST.json'
            manifest.write_text(json.dumps({'format': 'strike-source-beta', 'revision': 'a'*40,
                                            'workingTreeChanged': False}))
            data = report(root, {'kit_path': '/Users/Private/Secret.skt', 'dirty': True,
                                  'pads': [{'name': 'Secret'}], 'history': [], 'token': 'Secret'})
            self.assertEqual(data['application']['revision'], 'a'*40)
            self.assertFalse(data['application']['working_tree_changed'])
            self.assertNotIn('Secret', json.dumps(data))
            self.assertNotIn(folder, json.dumps(data))
            manifest.write_text('broken')
            self.assertEqual(identity(root)['revision'], 'unknown')
            manifest.unlink()
            self.assertEqual(identity(root)['revision'], 'unknown')


if __name__ == '__main__':
    unittest.main()
