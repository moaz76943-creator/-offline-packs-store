import unittest
from community.contributions.ingest import validate_document

class TestValidateDocument(unittest.TestCase):
    def setUp(self):
        self.valid_languages = {"eng", "spa"}
        self.license_ids = {"CC-BY-4.0", "CC0-1.0"}
        self.validate_lexical = lambda doc, publication: None

        self.valid_source = {
            "license_id": "CC0-1.0",
            "fixture_only": False,
            "source_id": "src1",
            "dataset_version": "v1",
            "record_locator": "loc1",
            "publisher": "pub1",
            "origin_url": "http://example.com",
            "artifact_sha256": "a" * 64
        }

        self.valid_doc = {
            "lexemes": [
                {"language": "eng", "source": self.valid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }

    def test_valid_document(self):
        sources = validate_document(
            self.valid_doc, self.valid_languages, self.validate_lexical, self.license_ids
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_id"], "src1")
        self.assertEqual(sources[0]["dataset_version"], "v1")
        self.assertEqual(sources[0]["record_locator"], "loc1")
        self.assertEqual(sources[0]["license_id"], "CC0-1.0")
        self.assertEqual(sources[0]["artifact_sha256"], "a" * 64)

    def test_empty_contribution(self):
        empty_doc = {
            "lexemes": [],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "empty lexical contribution"):
            validate_document(
                empty_doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_unregistered_language(self):
        doc = {
            "lexemes": [
                {"language": "fra", "source": self.valid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "unregistered language"):
            validate_document(
                doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_missing_source_provenance_fields(self):
        invalid_source = self.valid_source.copy()
        del invalid_source["publisher"]
        doc = {
            "lexemes": [
                {"language": "eng", "source": invalid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(
                doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_invalid_artifact_sha256(self):
        invalid_source = self.valid_source.copy()
        invalid_source["artifact_sha256"] = "invalid_hash"
        doc = {
            "lexemes": [
                {"language": "eng", "source": invalid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(
                doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_fixture_only_true_fails(self):
        invalid_source = self.valid_source.copy()
        invalid_source["fixture_only"] = True
        doc = {
            "lexemes": [
                {"language": "eng", "source": invalid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(
                doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_invalid_license_id(self):
        invalid_source = self.valid_source.copy()
        invalid_source["license_id"] = "GPL-3.0"
        doc = {
            "lexemes": [
                {"language": "eng", "source": invalid_source}
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(
                doc, self.valid_languages, self.validate_lexical, self.license_ids
            )

    def test_deep_source_traversal(self):
        doc = {
            "lexemes": [{"language": "eng"}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": [],
            "deeply": {
                "nested": {
                    "source": self.valid_source
                }
            }
        }
        sources = validate_document(
            doc, self.valid_languages, self.validate_lexical, self.license_ids
        )
        self.assertEqual(len(sources), 1)

    def test_validate_lexical_called(self):
        called = False
        def fake_validate(doc, publication):
            nonlocal called
            called = True
            self.assertFalse(publication)

        doc = {
            "lexemes": [{"language": "eng"}],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        sources = validate_document(
            doc, self.valid_languages, fake_validate, self.license_ids
        )
        self.assertTrue(called)
        self.assertEqual(len(sources), 0)

if __name__ == '__main__':
    unittest.main()
