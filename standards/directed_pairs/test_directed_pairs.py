import unittest
from standards.directed_pairs.validate import validate, verify_compatible, DirectedPairContractError

class TestDirectedPairs(unittest.TestCase):
    def setUp(self):
        self.valid_source = {
            "source_id": "src-123",
            "origin_url": "https://example.com/data",
            "publisher": "Example Corp",
            "dataset_version": "1.0",
            "retrieval_id": "ret-456",
            "license_id": "CC-BY-4.0",
            "record_locator": "loc-789",
            "publication_approved": True,
            "fixture_only": True,
            "confidence": 0.95
        }

    def test_valid_translation(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc-001",
            "translations": [
                {
                    "translation_id": "trans-001",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-fr-1",
                    "target_text": "bonjour",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        self.assertEqual(validate(doc), doc)

    def test_invalid_same_language(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc-002",
            "translations": [
                {
                    "translation_id": "trans-002",
                    "source_language": "en",
                    "target_language": "en",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-en-2",
                    "target_text": "hello",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as context:
            validate(doc)
        self.assertIn("target language mismatch with source language", str(context.exception))

    def test_missing_sense_identity(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc-003",
            "translations": [
                {
                    "translation_id": "trans-003",
                    "source_language": "en",
                    "target_language": "es",
                    "target_text": "hola",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as context:
            validate(doc)
        self.assertIn("JSON Schema violation", str(context.exception))

    def test_verify_compatible_valid(self):
        doc1 = {
            "contract_version": "1.0.0",
            "document_id": "doc-001",
            "translations": [
                {
                    "translation_id": "trans-001",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-fr-1",
                    "target_text": "bonjour",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        doc2 = {
            "contract_version": "1.0.0",
            "document_id": "doc-001",
            "translations": [
                {
                    "translation_id": "trans-001",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-fr-1",
                    "target_text": "salut",
                    "equivalence": "approximate",
                    "source": self.valid_source
                }
            ]
        }
        self.assertTrue(verify_compatible(doc1, doc2))

    def test_verify_compatible_invalid_id_change(self):
        doc1 = {
            "contract_version": "1.0.0",
            "document_id": "doc-001",
            "translations": [
                {
                    "translation_id": "trans-001",
                    "source_language": "en",
                    "target_language": "fr",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-fr-1",
                    "target_text": "bonjour",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        doc2 = {
            "contract_version": "1.0.0",
            "document_id": "doc-001",
            "translations": [
                {
                    "translation_id": "trans-001",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sense-en-1",
                    "target_sense_id": "sense-fr-1",
                    "target_text": "hola",
                    "equivalence": "exact",
                    "source": self.valid_source
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(doc1, doc2)
        self.assertIn("stable identity reassignment", str(context.exception))

if __name__ == "__main__":
    unittest.main()
