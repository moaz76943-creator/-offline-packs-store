import unittest
import tempfile
import json
import zipfile
import tarfile
import gzip
import os
from pathlib import Path

from tools.community_automation.cli import ingest_hybrid
from community.contributions.ingest import quarantine_submission

class TestCommunityAutomation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.staging = self.root / "staging"
        self.registry_path = self.root / "registry.json"

        registry_data = {
            "version": "1.0",
            "states": {
                "en": {"status": "unverified"},
                "es": {"status": "unverified"}
            }
        }
        self.registry_path.write_text(json.dumps(registry_data))

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_zip(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        return path

    def test_visual_token_success(self):
        token = {
            "concept_id": "c1",
            "version": 1,
            "semantic_label": "test",
            "viewBox": [0, 0, 100, 100],
            "paths": ["M10 10 L 90 90"],
            "palette": ["#ff0000"],
            "license": "CC0-1.0"
        }
        zip_path = self.write_zip("token.zip", {"token.json": json.dumps(token)})

        receipt = ingest_hybrid(zip_path, self.staging)
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(receipt["documents"], 1)

    def test_visual_token_bad_license(self):
        token = {
            "concept_id": "c1",
            "version": 1,
            "semantic_label": "test",
            "viewBox": [0, 0, 100, 100],
            "paths": ["M10 10 L 90 90"],
            "palette": ["#ff0000"],
            "license": "CC-BY-4.0" # Invalid
        }
        zip_path = self.write_zip("bad_token.zip", {"token.json": json.dumps(token)})

        with self.assertRaisesRegex(ValueError, "CC0-1.0"):
            ingest_hybrid(zip_path, self.staging)

    def test_lexical_submission(self):
        doc = {
            "document_id": "test-doc-1",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "eng-test",
                    "language": "en",
                    "script": "Latn",
                    "direction": "ltr",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "source": {
                        "source_id": "test-source",
                        "dataset_version": "1.0",
                        "record_locator": "123",
                        "publisher": "Test Pub",
                        "origin_url": "https://example.com",
                        "license_id": "CC0-1.0",
                        "artifact_sha256": "a" * 64,
                        "fixture_only": False,
                        "publication_approved": True,
                        "retrieval_id": "some_retrieval_id"
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        zip_path = self.write_zip("lex.zip", {"lex.json": json.dumps(doc)})

        receipt = ingest_hybrid(zip_path, self.staging, registry_path=self.registry_path)
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")

    def test_unsupported_language_lexical(self):
        doc = {
            "document_id": "test-doc-2",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "fra-test",
                    "language": "fr",
                    "script": "Latn",
                    "direction": "ltr",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "source": {
                        "source_id": "test-source",
                        "dataset_version": "1.0",
                        "record_locator": "123",
                        "publisher": "Test Pub",
                        "origin_url": "https://example.com",
                        "license_id": "CC0-1.0",
                        "artifact_sha256": "a" * 64,
                        "fixture_only": False,
                        "publication_approved": True,
                        "retrieval_id": "some_retrieval_id"
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        zip_path = self.write_zip("badlex.zip", {"badlex.json": json.dumps(doc)})

        with self.assertRaisesRegex(ValueError, "unregistered language"):
            ingest_hybrid(zip_path, self.staging, registry_path=self.registry_path)

    def test_malicious_archive(self):
        zip_path = self.root / "malicious.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("../../../etc/passwd", "malicious")

        with self.assertRaises(ValueError):
            ingest_hybrid(zip_path, self.staging)

    def test_unsupported_file(self):
        path = self.root / "unsupported.txt"
        path.write_text("just text")

        with self.assertRaisesRegex(ValueError, "unsupported format"):
            ingest_hybrid(path, self.staging)

if __name__ == '__main__':
    unittest.main()
