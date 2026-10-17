import unittest
import os
import tempfile
import json
import zipfile
import shutil
from pathlib import Path

from tools.community_automation.gate import process_bundle, validate_svg

class TestGate(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.staging_root = Path(self.test_dir) / "staging"
        self.staging_root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_malicious_archive(self):
        zip_path = Path(self.test_dir) / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("bad.svg", b"<svg><script>alert('xss')</script></svg>")
            z.writestr("test.json", b'{"document_id": "doc1", "contract_version": "1.0.0", "lexemes": [], "senses": [], "translations": [], "examples": [], "relations": []}')
        with self.assertRaises(ValueError) as ctx:
            process_bundle(zip_path, self.staging_root)
        self.assertIn("unsafe svg: scripts forbidden", str(ctx.exception))

    def test_missing_license(self):
        doc = {
            "document_id": "test_doc",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "l_1",
                    "language": "en",
                    "script": "Latn",
                    "direction": "ltr",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "source": {
                        "license_id": "UNKNOWN",
                        "source_id": "test",
                        "dataset_version": "1.0",
                        "record_locator": "123",
                        "publisher": "test",
                        "origin_url": "https://example.com",
                        "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        "publication_approved": True,
                        "fixture_only": False,
                        "retrieval_id": "ret_1"
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        json_path = Path(self.test_dir) / "test.json"
        with open(json_path, "w") as f:
            json.dump(doc, f)

        with self.assertRaises(ValueError) as ctx:
            process_bundle(json_path, self.staging_root)
        self.assertIn("missing/fixture/unverified source provenance", str(ctx.exception))

    def test_wrong_language_id(self):
        doc = {
            "document_id": "test_doc",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "l_1",
                    "language": "xx",
                    "script": "Latn",
                    "direction": "ltr",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "source": {
                        "license_id": "CC0-1.0",
                        "source_id": "test",
                        "dataset_version": "1.0",
                        "record_locator": "123",
                        "publisher": "test",
                        "origin_url": "https://example.com",
                        "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        "publication_approved": True,
                        "fixture_only": False,
                        "retrieval_id": "ret_1"
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        json_path = Path(self.test_dir) / "test.json"
        with open(json_path, "w") as f:
            json.dump(doc, f)

        with self.assertRaises(ValueError) as ctx:
            process_bundle(json_path, self.staging_root)
        self.assertIn("unregistered language", str(ctx.exception))

    def test_unsupported_file(self):
        txt_path = Path(self.test_dir) / "test.txt"
        with open(txt_path, "w") as f:
            f.write("hello")

        with self.assertRaises(ValueError) as ctx:
            process_bundle(txt_path, self.staging_root)
        self.assertIn("unsupported format", str(ctx.exception))

    def test_valid_submission(self):
        doc = {
            "document_id": "test_doc_valid",
            "contract_version": "1.0.0",
            "lexemes": [
                {
                    "lexeme_id": "l_1",
                    "language": "en",
                    "script": "Latn",
                    "direction": "ltr",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "source": {
                        "license_id": "CC0-1.0",
                        "source_id": "test_source",
                        "dataset_version": "1.0",
                        "record_locator": "123",
                        "publisher": "test_pub",
                        "origin_url": "https://example.com",
                        "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        "publication_approved": True,
                        "fixture_only": False,
                        "retrieval_id": "ret_1"
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        json_path = Path(self.test_dir) / "test.json"
        with open(json_path, "w") as f:
            json.dump(doc, f)

        receipt = process_bundle(json_path, self.staging_root)
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")

    def test_path_traversal(self):
        zip_path = Path(self.test_dir) / "bad_path.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("../test.json", b'{"document_id": "doc1", "contract_version": "1.0.0", "lexemes": [], "senses": [], "translations": [], "examples": [], "relations": []}')
        with self.assertRaises(ValueError) as ctx:
            process_bundle(zip_path, self.staging_root)
        self.assertIn("archive path traversal forbidden", str(ctx.exception))

    def test_validate_svg(self):
        with self.assertRaises(ValueError) as ctx:
            validate_svg(b'<svg><foreignObject></foreignObject></svg>')
        self.assertIn("unsafe svg: foreignObject forbidden", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_svg(b'<svg><image href="http://example.com/image.jpg" /></svg>')
        self.assertIn("unsafe svg: external references forbidden", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
