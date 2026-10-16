import unittest
import json
from pathlib import Path
from validate import validate, DirectedPairValidationError

class TestDirectedPairFixtures(unittest.TestCase):
    def test_polysemous_word(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-bank-financial",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-bank-1",
                    "target_sense_id": "es-banco-1",
                    "translation_text": "banco",
                    "context": "financial institution",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                },
                {
                    "pair_id": "pair-bank-river",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-bank-2",
                    "target_sense_id": "es-orilla-1",
                    "translation_text": "orilla",
                    "context": "edge of river",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                }
            ]
        }
        self.assertTrue(validate(doc))

    def test_reverse_pair(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-en-es-hello",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-hello-1",
                    "target_sense_id": "es-hola-1",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                },
                {
                    "pair_id": "pair-es-en-hola",
                    "source_language": "es",
                    "target_language": "en",
                    "source_sense_id": "es-hola-1",
                    "target_sense_id": "en-hello-1",
                    "translation_text": "hello",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                }
            ]
        }
        self.assertTrue(validate(doc))

    def test_homograph(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-lead-metal",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "en-lead-metal",
                    "target_sense_id": "fr-plomb-1",
                    "translation_text": "plomb",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                },
                {
                    "pair_id": "pair-lead-guide",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "en-lead-guide",
                    "target_sense_id": "fr-guider-1",
                    "translation_text": "guider",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                }
            ]
        }
        self.assertTrue(validate(doc))

    def test_regional_variant(self):
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-car-es-es",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-car-1",
                    "target_sense_id": "es-coche-1",
                    "translation_text": "coche",
                    "context": "Spain",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                },
                {
                    "pair_id": "pair-car-es-mx",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "en-car-1",
                    "target_sense_id": "es-carro-1",
                    "translation_text": "carro",
                    "context": "Mexico",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "1.0",
                    "confidence_evidence": "human verified"
                }
            ]
        }
        self.assertTrue(validate(doc))

if __name__ == '__main__':
    unittest.main()
