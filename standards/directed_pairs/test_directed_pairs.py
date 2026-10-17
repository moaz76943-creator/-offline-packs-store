import copy
import json
import unittest
from pathlib import Path

from validate import DirectedPairContractError, validate, verify_compatible

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


class DirectedPairSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture('positive')

    def test_positive_polysemous_pairs(self):
        self.assertIs(validate(self.data), self.data)
        self.assertEqual(len(self.data['pairs']), 3)

    def test_negative_fixture_missing_sense(self):
        with self.assertRaises(DirectedPairContractError) as context:
            validate(fixture('negative'))
        self.assertIn("orphan directed pair", str(context.exception))

    def test_reject_same_language(self):
        draft = copy.deepcopy(self.data)
        draft['senses'][1]['language'] = 'en'  # Change de.bank to en
        with self.assertRaises(DirectedPairContractError) as context:
            validate(draft)
        self.assertIn("directed pair languages must differ", str(context.exception))

    def test_reject_self_referential(self):
        draft = copy.deepcopy(self.data)
        draft['pairs'][0]['to_sense_id'] = 'sense.en.bank.1'
        with self.assertRaises(DirectedPairContractError) as context:
            validate(draft)
        self.assertIn("self-referential pair", str(context.exception))

    def test_verify_compatible_success(self):
        changed = copy.deepcopy(self.data)
        changed['pairs'][0]['source']['confidence'] = 0.99
        self.assertTrue(verify_compatible(self.data, changed))

    def test_verify_compatible_rejects_identity_reassignment(self):
        changed = copy.deepcopy(self.data)
        changed['senses'][0]['language'] = 'fr'
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(self.data, changed)
        self.assertIn("stable identity reassignment", str(context.exception))

    def test_verify_compatible_rejects_removal(self):
        changed = copy.deepcopy(self.data)
        changed['senses'].pop()
        changed['pairs'].pop() # Remove pair 3 which points to the popped sense so we get the breaking removal error
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(self.data, changed)
        self.assertIn("breaking removal", str(context.exception))

    def test_verify_compatible_rejects_pair_reassignment(self):
        changed = copy.deepcopy(self.data)
        changed['pairs'][0]['to_sense_id'] = 'sense.de.ufer.1'
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(self.data, changed)
        self.assertIn("stable identity reassignment", str(context.exception))

if __name__ == '__main__':
    unittest.main()
