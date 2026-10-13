import unittest
import tempfile
import json
import zipfile
import zlib
from pathlib import Path
import os
import sys

from tools.community_automation.gate import ingest

class TestCommunityAutomationGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.staging = self.root / "staging"
        self.staging.mkdir()
        self.submission_path = self.root / "submission.zip"

        # Build mock registry
        self.registry = {"states": ["en", "es"]}
        self.registry_path = self.root / "registry.json"
        self.registry_path.write_text(json.dumps(self.registry))

        self.valid_doc = {
        "document_id": "test-doc-1",
        "contract_version": "1.0.0",
        "lexemes": [
                {
                        "lexeme_id": "lex-1",
                        "language": "en",
                        "lemma": "hello",
                "surface": "hello",
                "direction": "ltr",
                        "script": "Latn",
                        "pos": "noun",
                        "source": {
                                "source_id": "mock_source",
                                "dataset_version": "1.0",
                                "record_locator": "loc-1",
                                "license_id": "CC0-1.0",
                                "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                "publisher": "mock",
                                "origin_url": "https://mock.com",
                "retrieval_id": "req-1",
                                "fixture_only": False,
                                "publication_approved": True
                        }
                }
        ],
        "senses": [],
        "translations": [],
        "examples": [],
        "relations": []
}

    def tearDown(self):
        self.tmp.cleanup()

    def _write_zip(self, files):
        with zipfile.ZipFile(self.submission_path, 'w') as z:
            for k, v in files.items():
                z.writestr(k, v)

    def test_valid_submission(self):
        self._write_zip({"doc.json": json.dumps(self.valid_doc).encode()})
        res = ingest(self.submission_path, self.staging, registry_path=self.registry_path)
        self.assertEqual(res["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(res["documents"], 1)

    def test_malicious_archive_traversal(self):
        self._write_zip({"../escaped.json": b"{}"})
        with self.assertRaisesRegex(ValueError, "unsafe archive member"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_unsupported_files(self):
        self._write_zip({"exe_payload.exe": b"MZ"})
        with self.assertRaisesRegex(ValueError, "executable payloads or unsupported files rejected"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_license_omissions(self):
        doc = json.loads(json.dumps(self.valid_doc))
        doc["lexemes"][0]["source"]["license_id"] = "INVALID-LICENSE"
        self._write_zip({"doc.json": json.dumps(doc).encode()})
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_wrong_language_ids(self):
        doc = json.loads(json.dumps(self.valid_doc))
        doc["lexemes"][0]["language"] = "xx"  # Not in registry
        self._write_zip({"doc.json": json.dumps(doc).encode()})
        with self.assertRaisesRegex(ValueError, "unregistered language"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_svg_unsafe_media(self):
        self._write_zip({"image.svg": b"<svg><script>alert(1)</script></svg>"})
        with self.assertRaisesRegex(ValueError, "unsafe media"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_vct_invalid_media(self):
        self._write_zip({"vector.vct": b"not_zlib_compressed_data"})
        with self.assertRaisesRegex(ValueError, "invalid compact vector"):
            ingest(self.submission_path, self.staging, registry_path=self.registry_path)

    def test_vct_valid_media(self):
        valid_vct = zlib.compress(b"mock_vector_data")
        self._write_zip({"vector.vct": valid_vct})
        res = ingest(self.submission_path, self.staging, registry_path=self.registry_path)
        self.assertEqual(res["documents"], 1)

if __name__ == "__main__":
    unittest.main()
