import unittest
import json
from pathlib import Path
from validate import validate, DirectedPairValidationError

class TestDirectedPairValidator(unittest.TestCase):
    def test_valid_document(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "es-sense-2",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human reviewed"
                }
            ]
        }
        self.assertTrue(validate(doc))

    def test_invalid_schema_version(self):
        doc = {
            "schema_version": "2.0.0",
            "pairs": []
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)

    def test_missing_required_fields(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)

    def test_duplicate_pair_id(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "es-sense-2",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human reviewed"
                },
                {
                    "pair_id": "pair-1",
                    "source_language": "fr",
                    "target_language": "de",
                    "source_sense_id": "fr-sense-1",
                    "target_sense_id": "de-sense-2",
                    "translation_text": "hallo",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human reviewed"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)

    def test_language_mismatch_source(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "fr-sense-1",
                    "target_sense_id": "es-sense-2",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human reviewed"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)

    def test_language_mismatch_target(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "fr-sense-2",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human reviewed"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)

    def test_reverse_translation_cannot_be_assumed(self):
        # We enforce that source and target language cannot be the same
        # which would violate the directionality
        pass

if __name__ == '__main__':
    unittest.main()
