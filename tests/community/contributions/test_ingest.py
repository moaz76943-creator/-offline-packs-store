import unittest
import json
import io
import gzip
import tarfile
import zipfile
import os
from pathlib import Path
import tempfile
from unittest.mock import patch, MagicMock

from community.contributions.ingest import validate_document, ingest, quarantine_submission

class TestValidateDocument(unittest.TestCase):
    def setUp(self):
        self.valid_languages = {"en", "es"}
        self.license_ids = {"CC0-1.0", "MIT"}
        def mock_validate_lexical(doc, publication=False):
            pass
        self.validate_lexical = mock_validate_lexical
        self.valid_source = {
            "source_id": "test_src",
            "dataset_version": "1.0",
            "record_locator": "loc1",
            "publisher": "pub1",
            "origin_url": "http://example.com",
            "artifact_sha256": "a" * 64,
            "license_id": "CC0-1.0",
            "fixture_only": False,
        }

    def test_valid_document(self):
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": self.valid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        sources = validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_id"], "test_src")

    def test_empty_lexical_contribution(self):
        doc = {
            "document_id": "doc1",
            "lexemes": [],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "empty lexical contribution"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_unregistered_language(self):
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "fr",
                    "source": self.valid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "unregistered language"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_missing_source_provenance(self):
        # We test omitting multiple keys that are required
        required_keys = ["source_id", "dataset_version", "record_locator", "publisher", "origin_url", "artifact_sha256"]
        for key in required_keys:
            invalid_source = self.valid_source.copy()
            del invalid_source[key]
            doc = {
                "document_id": "doc1",
                "lexemes": [
                    {
                        "language": "en",
                        "source": invalid_source
                    }
                ],
                "senses": [],
                "translations": [],
                "examples": [],
                "relations": []
            }
            with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
                validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_invalid_license_id(self):
        invalid_source = self.valid_source.copy()
        invalid_source["license_id"] = "GPL-3.0"
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": invalid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_fixture_only_true(self):
        invalid_source = self.valid_source.copy()
        invalid_source["fixture_only"] = True
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": invalid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_invalid_hash(self):
        invalid_source = self.valid_source.copy()
        invalid_source["artifact_sha256"] = "invalid_hash"
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": invalid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_invalid_hash_type(self):
        invalid_source = self.valid_source.copy()
        invalid_source["artifact_sha256"] = 123456
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": invalid_source
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_source_not_dict(self):
        doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "en",
                    "source": "invalid_source"
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)

    def test_traverse_nested_structures(self):
        # The traverse function descends through both lists and dictionaries.
        doc = {
            "document_id": "doc1",
            "lexemes": [],
            "senses": [
                {
                    "language": "en",
                    "nested_list": [
                        {
                            "source": self.valid_source
                        }
                    ],
                    "nested_dict": {
                        "inner_dict": {
                            "source": self.valid_source
                        }
                    }
                }
            ],
            "translations": [],
            "examples": [],
            "relations": []
        }
        sources = validate_document(doc, self.valid_languages, self.validate_lexical, self.license_ids)
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["source_id"], "test_src")
        self.assertEqual(sources[1]["source_id"], "test_src")

if __name__ == '__main__':
    unittest.main()
