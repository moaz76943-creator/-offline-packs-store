import unittest
from ingest import validate_document

class TestValidateDocument(unittest.TestCase):
    def setUp(self):
        self.valid_languages = {"en", "es"}
        self.license_ids = {"CC-BY-4.0", "CC0-1.0"}
        self.mock_validate_lexical = lambda doc, publication: None

        self.valid_source = {
            "source_id": "test-source",
            "dataset_version": "1.0",
            "record_locator": "loc1",
            "publisher": "Test Pub",
            "origin_url": "http://example.com",
            "license_id": "CC0-1.0",
            "fixture_only": False,
            "artifact_sha256": "a" * 64
        }

        self.valid_doc = {
            "lexemes": [{"language": "en", "source": self.valid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }

    def test_happy_path(self):
        sources = validate_document(self.valid_doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_id"], "test-source")
        self.assertEqual(sources[0]["artifact_sha256"], "a" * 64)

    def test_empty_lexical_contribution(self):
        doc = {
            "lexemes": [],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "empty lexical contribution"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_unregistered_language(self):
        doc = {
            "lexemes": [{"language": "fr", "source": self.valid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "unregistered language"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_missing_source_provenance(self):
        invalid_source = self.valid_source.copy()
        del invalid_source["dataset_version"]
        doc = {
            "lexemes": [{"language": "en", "source": invalid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_fixture_only_source(self):
        invalid_source = self.valid_source.copy()
        invalid_source["fixture_only"] = True
        doc = {
            "lexemes": [{"language": "en", "source": invalid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_invalid_hash(self):
        invalid_source = self.valid_source.copy()
        invalid_source["artifact_sha256"] = "invalid-hash"
        doc = {
            "lexemes": [{"language": "en", "source": invalid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_unsupported_license(self):
        invalid_source = self.valid_source.copy()
        invalid_source["license_id"] = "UNSUPPORTED"
        doc = {
            "lexemes": [{"language": "en", "source": invalid_source}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)

    def test_nested_sources(self):
        doc = {
            "lexemes": [],
            "senses": [],
            "translations": [{"language": "en", "nested": {"deep": {"source": self.valid_source}}}],
            "examples": [],
            "relations": []
        }
        sources = validate_document(doc, self.valid_languages, self.mock_validate_lexical, self.license_ids)
        self.assertEqual(len(sources), 1)

if __name__ == '__main__':
    unittest.main()
