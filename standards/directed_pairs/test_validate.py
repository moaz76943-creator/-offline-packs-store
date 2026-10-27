"""Run: python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v"""
import copy
import json
import unittest
from pathlib import Path

from validate import DirectedPairsContractError, validate, verify_compatible

HERE = Path(__file__).parent

def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))

class DirectedPairsSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def test_positive_fixture(self):
        self.assertIs(validate(self.data), self.data)
        self.assertEqual(self.data['source_language'], 'en')
        self.assertEqual(self.data['target_language'], 'es')
        self.assertEqual(len(self.data['translations']), 4)

        # Test directed pairs logic - separate entries for opposite directions
        ids = {t['translation_id'] for t in self.data['translations']}
        self.assertIn('tr.bank_financial.es', ids)
        self.assertIn('tr.bank_financial.reverse', ids)

    def test_negative_fixture_rejected(self):
        with self.assertRaises(DirectedPairsContractError):
            validate(fixture('negative'))

    def test_duplicate_translation_id_rejected(self):
        draft = copy.deepcopy(self.data)
        draft['translations'].append(copy.deepcopy(draft['translations'][0]))
        with self.assertRaises(DirectedPairsContractError):
            validate(draft)

    def test_duplicate_pair_identity_rejected(self):
        draft = copy.deepcopy(self.data)
        dup = copy.deepcopy(draft['translations'][0])
        dup['translation_id'] = 'tr.new_id'
        draft['translations'].append(dup)
        with self.assertRaises(DirectedPairsContractError):
            validate(draft)

    def test_publication_gate_rejected_for_fixture(self):
        draft = copy.deepcopy(self.data)
        for t in draft['translations']:
            t['source']['publication_approved'] = False
        with self.assertRaises(DirectedPairsContractError):
            validate(draft, publication=True)

    def test_stable_identity_compatibility(self):
        changed = copy.deepcopy(self.data)
        changed['translations'][0]['text'] = 'margen'
        self.assertTrue(verify_compatible(self.data, changed))

        changed['translations'][0]['from_sense_id'] = 'sense.en.edge'
        with self.assertRaises(DirectedPairsContractError):
            verify_compatible(self.data, changed)

        with self.assertRaises(DirectedPairsContractError):
            verify_compatible(self.data, {'contract_version': '9.0.0'})

if __name__ == '__main__':
    unittest.main()
