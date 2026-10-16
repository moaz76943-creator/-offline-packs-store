import unittest
import json
from validate import validate, verify_compatible, DirectedPairValidationError

class TestDirectedPairVersioning(unittest.TestCase):
    def test_verify_compatible_success(self):
        doc1 = {
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
                    "confidence_evidence": "human"
                }
            ]
        }
        doc2 = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "es-sense-3", # Correcting target sense is allowed
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v2",
                    "confidence_evidence": "human"
                }
            ]
        }
        self.assertTrue(verify_compatible(doc1, doc2))

    def test_verify_compatible_removal(self):
        doc1 = {
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
                    "confidence_evidence": "human"
                }
            ]
        }
        doc2 = {
            "schema_version": "1.0.0",
            "pairs": []
        }
        with self.assertRaises(DirectedPairValidationError):
            verify_compatible(doc1, doc2)

    def test_verify_compatible_reassignment(self):
        doc1 = {
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
                    "confidence_evidence": "human"
                }
            ]
        }
        doc2 = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "fr", # changed target language
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "fr-sense-1",
                    "translation_text": "bonjour",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            verify_compatible(doc1, doc2)

if __name__ == '__main__':
    unittest.main()
