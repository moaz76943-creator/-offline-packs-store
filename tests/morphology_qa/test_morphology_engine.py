import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.morphology.morphology_engine import (
    parse_german_verb_morphology,
    parse_german_noun_morphology,
    validate_morphology_record
)

class TestMorphologyEngine(unittest.TestCase):
    def test_irregular_strong_verb_parsing(self):
        raw = {
            'praesens_3sg': 'sieht',
            'praeteritum': 'sah',
            'partizip_ii': 'gesehen',
            'auxiliary': 'haben'
        }
        res = parse_german_verb_morphology('sehen', raw)
        self.assertEqual(res['infinitive'], 'sehen')
        self.assertEqual(res['praesens_3sg'], 'sieht')
        self.assertEqual(res['praeteritum'], 'sah')
        self.assertEqual(res['partizip_ii'], 'gesehen')
        self.assertFalse(res['is_separable'])

    def test_separable_verb_detection(self):
        raw = {
            'praesens_3sg': 'steht auf',
            'praeteritum': 'stand auf',
            'partizip_ii': 'aufgestanden',
            'auxiliary': 'sein'
        }
        res = parse_german_verb_morphology('aufstehen', raw)
        self.assertTrue(res['is_separable'])
        self.assertEqual(res['prefix'], 'auf')
        self.assertEqual(res['auxiliary'], 'sein')

    def test_noun_gender_and_plural_parsing(self):
        raw = {'plural': 'Bücher', 'genitive': 'Buches'}
        res = parse_german_noun_morphology('Buch', 'neutrum', raw)
        self.assertEqual(res['lemma'], 'Buch')
        self.assertEqual(res['gender'], 'neutrum')
        self.assertEqual(res['plural'], 'Bücher')

    def test_empty_record_validation_fails(self):
        self.assertFalse(validate_morphology_record({}))
        self.assertFalse(validate_morphology_record({'infinitive': ''}))

if __name__ == "__main__":
    unittest.main()
