import unittest
from tools.visual_lexicon.schema import validate_manifest, generate_incremental_update

class TestSchema(unittest.TestCase):
    def test_validate_manifest(self):
        valid = {
            "concept_id": "concept.en.circle",
            "author": "Bob",
            "source": "https://example.com/circle",
            "license": "CC0"
        }
        self.assertTrue(validate_manifest(valid))

        invalid = {
            "concept_id": "concept.en.circle",
            "author": "Bob",
            "source": "https://example.com/circle",
            "license": "All Rights Reserved"
        }
        with self.assertRaises(ValueError):
            validate_manifest(invalid)

    def test_generate_incremental_update(self):
        old_m = {
            "concept.1": {"concept_id": "concept.1", "version": 1},
            "concept.2": {"concept_id": "concept.2", "version": 1},
        }
        new_m = {
            "concept.2": {"concept_id": "concept.2", "version": 2},
            "concept.3": {"concept_id": "concept.3", "version": 1},
        }
        update = generate_incremental_update(old_m, new_m)
        self.assertEqual(update["added"], ["concept.3"])
        self.assertEqual(update["updated"], ["concept.2"])
        self.assertEqual(update["deleted"], ["concept.1"])
        self.assertEqual(update["unchanged"], [])
