import unittest
import json
import os
from validate import validate, verify_compatible, DirectedPairError

class TestDirectedPairs(unittest.TestCase):
    def setUp(self):
        fixture_dir = os.path.join(os.path.dirname(__file__), 'fixtures')
        with open(os.path.join(fixture_dir, 'positive.json'), 'r') as f:
            self.positive = json.load(f)
        with open(os.path.join(fixture_dir, 'negative.json'), 'r') as f:
            self.negative = json.load(f)

    def test_positive(self):
        validated = validate(self.positive)
        self.assertEqual(validated['document_id'], "doc.translation.test")
        self.assertEqual(len(validated['senses']), 9)

    def test_negative(self):
        with self.assertRaises(DirectedPairError):
            validate(self.negative)

    def test_verify_compatible(self):
        new_doc = json.loads(json.dumps(self.positive))
        new_doc['directed_pairs'][0]['confidence'] = 0.95
        self.assertTrue(verify_compatible(self.positive, new_doc))

if __name__ == '__main__':
    unittest.main()
