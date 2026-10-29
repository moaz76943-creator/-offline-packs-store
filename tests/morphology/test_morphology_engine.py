import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.morphology.morphology_engine import validate_morphological_entry

class TestMorphologyEngine(unittest.TestCase):
    def test_valid_verb_entry(self):
        entry = {
            "lemma": "sprechen",
            "pos": "verb",
            "praeteritum": "sprach",
            "partizip2": "gesprochen",
            "auxiliary": "haben"
        }
        valid, errors = validate_morphological_entry(entry)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_valid_noun_entry(self):
        entry = {
            "lemma": "Buch",
            "pos": "noun",
            "gender": "das"
        }
        valid, errors = validate_morphological_entry(entry)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_incomplete_verb_rejected(self):
        entry = {
            "lemma": "gehen",
            "pos": "verb"
        }
        valid, errors = validate_morphological_entry(entry)
        self.assertFalse(valid)
        self.assertTrue(any("missing mandatory principal part" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
