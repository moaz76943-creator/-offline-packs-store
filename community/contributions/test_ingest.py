import unittest
import os
import tempfile
import json
import gzip
import zipfile
import tarfile
from pathlib import Path
from ingest import ingest, quarantine_submission, unique_json

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.staging_root = Path(self.tmpdir.name)
        self.registry_path = self.staging_root / "registry.json"
        self.registry_path.write_text(json.dumps({"states": {"deu": "verified"}}))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_basic_ingest(self):
        # Create a valid minimal document
        doc = {
            "document_id": "test_doc_1",
            "lexemes": [
                {
                    "language": "deu",
                    "lemma": "Test",
                    "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "CC-BY-SA-4.0",
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "publisher": "Test Pub",
                        "origin_url": "http://example.com",
                        "fixture_only": False
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }
        submission = self.staging_root / "submission.json"
        submission.write_text(json.dumps(doc))

        def mock_validator(doc, publication=False):
            pass

        receipt = ingest(
            submission,
            self.staging_root,
            registry_path=self.registry_path,
            validator=mock_validator,
            licenses={"CC-BY-SA-4.0"}
        )
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(receipt["documents"], 1)
        self.assertTrue((self.staging_root / "staged" / (receipt["sha256"] + ".bin")).exists())

    def test_forged_license(self):
        doc = {
            "document_id": "test_doc_1",
            "lexemes": [
                {
                    "language": "deu",
                    "lemma": "Test",
                    "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "FORGED-LICENSE",
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "publisher": "Test Pub",
                        "origin_url": "http://example.com",
                        "fixture_only": False
                    }
                }
            ],
            "senses": [], "translations": [], "examples": [], "relations": []
        }
        submission = self.staging_root / "submission.json"
        submission.write_text(json.dumps(doc))

        with self.assertRaises(ValueError) as ctx:
             ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication=False: None, licenses={"CC-BY-SA-4.0"})
        self.assertIn("missing/fixture/unverified source provenance", str(ctx.exception))

    def test_reversed_pairs(self):
        # We need to simulate checking directed-pairs. The prompt asks to "Verify language IDs and source/target direction."
        # Actually this suggests the validator checks `validate_lexical`. The prompt specifically mentions:
        # "Add tests for valid records, forged licenses, reversed pairs, malformed Unicode, corrupt archives and duplicate submissions."

        doc = {
            "document_id": "test_doc_pair",
            "lexemes": [],
            "senses": [],
            "translations": [
                {
                    "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "CC-BY-SA-4.0",
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "publisher": "Test Pub",
                        "origin_url": "http://example.com",
                        "fixture_only": False
                    },
                    "source_sense_id": "sense1",
                    "target_sense_id": "sense2",
                    "source_language": "eng",
                    "target_language": "deu",
                    "direction": "reversed" # Assuming the validator or ingest throws error on this
                }
            ],
            "examples": [],
            "relations": []
        }
        submission = self.staging_root / "submission.json"
        submission.write_text(json.dumps(doc))

        # We use the real validator to see what happens
        # It should fail on validation
        with self.assertRaises(ValueError) as ctx:
            ingest(submission, self.staging_root, registry_path=self.registry_path, licenses={"CC-BY-SA-4.0"})

    def test_malformed_unicode(self):
        submission = self.staging_root / "submission.json"
        submission.write_bytes(b'{"document_id": "test", "lexemes": [{"lemma": "T\xe9st"}]}')

        with self.assertRaises(ValueError):
            ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication=False: None, licenses={"CC-BY-SA-4.0"})

    def test_corrupt_archive(self):
        submission = self.staging_root / "submission.zip"
        submission.write_bytes(b'PK\x03\x04This is not a valid zip file')
        with self.assertRaises(zipfile.BadZipFile):
            ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication=False: None, licenses={"CC-BY-SA-4.0"})

    def test_duplicate_submission(self):
        doc = {
            "document_id": "test_doc_dup",
            "lexemes": [
                {
                    "language": "deu",
                    "lemma": "Test",
                    "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "CC-BY-SA-4.0",
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "publisher": "Test Pub",
                        "origin_url": "http://example.com",
                        "fixture_only": False
                    }
                }
            ],
            "senses": [], "translations": [], "examples": [], "relations": []
        }
        submission = self.staging_root / "submission.json"
        submission.write_text(json.dumps(doc))

        receipt1 = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication=False: None, licenses={"CC-BY-SA-4.0"})
        receipt2 = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication=False: None, licenses={"CC-BY-SA-4.0"})

        self.assertEqual(receipt1["sha256"], receipt2["sha256"])

    def test_quarantine(self):
        submission = self.staging_root / "submission.json"
        submission.write_bytes(b'{"bad": "json"')

        with self.assertRaises(ValueError):
            unique_json(b'{"bad": "json"')

        receipt = quarantine_submission(submission, self.staging_root, "JSONDecodeError")
        self.assertEqual(receipt["state"], "QUARANTINED")
        self.assertTrue((self.staging_root / "quarantined" / (receipt["sha256"] + ".bin")).exists())

if __name__ == '__main__':
    unittest.main()
