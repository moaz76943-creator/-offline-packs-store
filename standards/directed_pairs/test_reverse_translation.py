import unittest
import json
from validate import validate, DirectedPairValidationError

class TestDirectedPairReverse(unittest.TestCase):
    def test_reverse_translation_rejected(self):
        # Let's ensure that source and target language are distinct, meaning a pair can't be "reverse" on itself
        doc = {
            "schema_version": "1.0.0",
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "source_language": "en",
                    "target_language": "en", # Same language!
                    "source_sense_id": "en-sense-1",
                    "target_sense_id": "en-sense-2",
                    "translation_text": "hello",
                    "equivalence": "literal",
                    "provenance_id": "prov-1",
                    "source_version": "v1",
                    "confidence_evidence": "human"
                }
            ]
        }
        with self.assertRaises(DirectedPairValidationError):
            validate(doc)
