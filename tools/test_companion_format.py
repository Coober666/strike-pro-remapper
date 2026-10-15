"""The native viewer's fixtures must agree with Strike's authoritative validator."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from strike_remapper.setlists import validate


class CompanionFormatTests(unittest.TestCase):
    def test_shared_contract_cases(self):
        source = ROOT / 'native/StrikeCompanion'
        for case in json.loads((source / 'Tests/Cases.json').read_text(encoding='utf-8')):
            with self.subTest(case=case['name']):
                try:
                    validate(json.loads(case['json']))
                    accepted = True
                except (ValueError, TypeError):
                    accepted = False
                self.assertEqual(accepted, case['valid'])

    def test_demo_is_an_exportable_document(self):
        path = ROOT / 'native/StrikeCompanion/Resources/Demo.setlist.json'
        document = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(validate(document), document)


if __name__ == '__main__':
    unittest.main()
