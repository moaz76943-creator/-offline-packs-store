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
        self.assertEqual({r['source_language'] for r in self.data['pairs']}, {'en'})
        self.assertEqual({r['target_language'] for r in self.data['pairs']}, {'es'})
        self.assertEqual(len(self.data['pairs']), 2)

    def test_negative_fixture_rejected(self):
        with self.assertRaises(DirectedPairsContractError):
            validate(fixture('negative'))

    def test_duplicate_ids_rejected(self):
        draft = copy.deepcopy(self.data)
        draft['pairs'].append(copy.deepcopy(draft['pairs'][0]))
        with self.assertRaises(DirectedPairsContractError):
            validate(draft)

    def test_fixture_cannot_pass_publication_gate(self):
        with self.assertRaises(DirectedPairsContractError):
            validate(self.data, publication=True)

    def test_stable_identity_compatibility(self):
        changed = copy.deepcopy(self.data)
        changed['pairs'][0]['target_text'] = 'banco central'
        self.assertTrue(verify_compatible(self.data, changed))

        changed['pairs'][0]['target_language'] = 'fr'
        with self.assertRaises(DirectedPairsContractError):
            verify_compatible(self.data, changed)

        with self.assertRaises(DirectedPairsContractError):
            verify_compatible(self.data, {'contract_version': '9.0.0'})

if __name__ == '__main__':
    unittest.main()
