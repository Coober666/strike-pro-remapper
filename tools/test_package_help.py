"""Offline guides resolve packaged references and preserve command examples."""
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.package_help import GUIDES, IMAGES, readable, write_help


class PackageHelpTests(unittest.TestCase):
    def test_readable_links_code_and_unicode(self):
        text = readable('# Help\n\nUse **Save**, then [MIDI](MIDI_TOOLKIT.md#capture).\n'
                        '[Evidence](evidence/test.txt) and [website](https://example.com).\n'
                        '![Image](midi-toolkit.png) · café\n'
                        '```text\n[leave](MIDI_TOOLKIT.md) `literal` **literal**\n```\n', 'a' * 40)
        self.assertIn('Use Save, then MIDI (MIDI-toolkit.txt, section: capture).', text)
        self.assertIn('/blob/' + 'a' * 40 + '/docs/evidence/test.txt', text)
        self.assertIn('website (https://example.com)', text)
        self.assertIn('Image (midi-toolkit.png) · café', text)
        self.assertIn('[leave](MIDI_TOOLKIT.md) `literal` **literal**', text)

    def test_delivered_guides_are_complete_and_local_references_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            write_help(folder, 'b' * 40)
            root = Path(folder) / 'Help'
            self.assertEqual({p.name for p in root.iterdir()},
                             set(GUIDES.values()) | set(IMAGES) | {'README.txt'})
            self.assertIn('Build revision: ' + 'b' * 40, (root / 'README.txt').read_text(encoding='utf-8'))
            for name in GUIDES.values():
                text = (root / name).read_text(encoding='utf-8')
                self.assertGreater(len(text), 100)
                # These are actual public guide references, not a hand-picked fixture.
                self.assertNotRegex(text, r'!?\[[^\]\n]+\]\([^h#][^)\n]*\.md[^)\n]*\)')
                for target in re.findall(r'\(([^()\n]+)\)', text):
                    target = target.split(', section:')[0]
                    if re.fullmatch(r'[\w-]+\.(?:txt|png)', target):
                        self.assertTrue((root / target).is_file(), (name, target))
            self.assertIn('Save as new copy', (root / 'MIDI-toolkit.txt').read_text(encoding='utf-8'))
            self.assertIn('not completed hardware tests', (root / 'Device-checks.txt').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
