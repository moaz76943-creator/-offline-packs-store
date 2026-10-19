import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from community.contributions.ingest import ingest, quarantine_submission

def get_valid_source():
    return {
        "source_id": "org.example.test",
        "dataset_version": "1.0",
        "record_locator": "doc123",
        "publisher": "Example Org",
        "origin_url": "https://example.org/test",
        "license_id": "CC0-1.0",
        "fixture_only": False,
        "artifact_sha256": "0" * 64,
        "retrieval_id": "doc123",
        "publication_approved": True
    }

def create_valid_doc(doc_id="doc-123", language="eng"):
    return {
        "document_id": doc_id,
        "contract_version": "1.0.0",
        "lexemes": [
            {
                "lexeme_id": f"lex-{doc_id}",
                "language": language,
                "script": "Latn",
                "direction": "ltr",
                "lemma": "test",
                "surface": "test",
                "pos": "noun",
                "source": get_valid_source()
            }
        ],
        "senses": [
            {
                "sense_id": f"sense-{doc_id}",
                "lexeme_id": f"lex-{doc_id}",
                "concept_id": "test_concept",
                "definition": "test definition",
                "source": get_valid_source()
            }
        ],
        "translations": [],
        "examples": [],
        "relations": []
    }

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.staging = self.root / "staging"
        self.registry_path = self.root / "registry.json"
        self.registry_path.write_text(json.dumps({"states": {"eng": "test", "fra": "test"}}))
        self.mock_validator_calls = []

        def mock_validator(doc, publication=False):
            self.mock_validator_calls.append((doc, publication))
        self.validator = mock_validator
        self.licenses = {"CC0-1.0"}

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, name, content):
        path = self.root / name
        path.write_bytes(json.dumps(content).encode("utf-8"))
        return path

    def write_zip(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            for k, v in files.items():
                z.writestr(k, v)
        return path

    def write_tar_gz(self, name, files):
        path = self.root / name
        with tarfile.open(path, "w:gz") as tar:
            for k, v in files.items():
                info = tarfile.TarInfo(name=k)
                info.size = len(v)
                tar.addfile(tarinfo=info, fileobj=io.BytesIO(v))
        return path

    def write_gz(self, name, content):
        path = self.root / name
        with gzip.GzipFile(path, "wb") as f:
            f.write(content)
        return path

    def test_valid_json_record(self):
        doc = create_valid_doc()
        path = self.write_json("test.json", doc)
        receipt = ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(receipt["documents"], 1)
        self.assertFalse(receipt["rights_approved"])
        self.assertEqual(len(self.mock_validator_calls), 1)

    def test_valid_zip_archive(self):
        files = {
            "doc1.json": json.dumps(create_valid_doc("doc1")).encode("utf-8"),
            "doc2.json": json.dumps(create_valid_doc("doc2")).encode("utf-8")
        }
        path = self.write_zip("test.zip", files)
        receipt = ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)
        self.assertEqual(receipt["documents"], 2)

    def test_valid_tar_gz_archive(self):
        files = {
            "doc1.json": json.dumps(create_valid_doc("doc1")).encode("utf-8"),
            "doc2.json": json.dumps(create_valid_doc("doc2")).encode("utf-8")
        }
        path = self.write_tar_gz("test.tar.gz", files)
        receipt = ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)
        self.assertEqual(receipt["documents"], 2)

    def test_forged_license(self):
        doc = create_valid_doc()
        doc["lexemes"][0]["source"]["license_id"] = "FORGED-1.0"
        path = self.write_json("test.json", doc)
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

    def test_reversed_pair(self):
        doc = create_valid_doc()
        # Create a document with a translation
        doc["lexemes"].append({
            "lexeme_id": "lex-target",
            "language": "fra",
            "script": "Latn",
            "direction": "ltr",
            "lemma": "test_fra",
            "surface": "test_fra",
            "pos": "noun",
            "source": get_valid_source()
        })
        doc["senses"].append({
            "sense_id": "sense-target",
            "lexeme_id": "lex-target",
            "concept_id": "test_concept",
            "definition": "test definition 2",
            "source": get_valid_source()
        })
        doc["translations"].append({
            "translation_id": "trans-1",
            "from_sense_id": "sense-target",
            "to_sense_id": f"sense-{doc['document_id']}",
            "language": "fra",
            "text": "test",
            "equivalence": "exact",
            "source": get_valid_source()
        })
        # The true validator enforces these directionality rules, our mock does not
        # So we'll substitute the real validator
        from standards.lexical.validate import validate as real_validator
        self.validator = real_validator

        path = self.write_json("test.json", doc)
        with self.assertRaisesRegex(ValueError, "target language mismatch"):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

    def test_malformed_unicode(self):
        doc = create_valid_doc()
        path = self.root / "test.json"
        # Write invalid UTF-8 byte sequence
        path.write_bytes(json.dumps(doc).encode("utf-8") + b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

    def test_corrupt_zip_archive(self):
        path = self.root / "test.zip"
        path.write_bytes(b"PK\x03\x04" + b"bad_data")
        with self.assertRaises(zipfile.BadZipFile):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

    def test_duplicate_submission(self):
        files = {
            "doc1.json": json.dumps(create_valid_doc("doc1")).encode("utf-8"),
            "doc1_dup.json": json.dumps(create_valid_doc("doc1")).encode("utf-8")
        }
        path = self.write_zip("test.zip", files)
        with self.assertRaisesRegex(ValueError, "duplicate document ID"):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

    def test_missing_source_evidence(self):
        doc = create_valid_doc()
        del doc["lexemes"][0]["source"]["artifact_sha256"]
        path = self.write_json("test.json", doc)
        with self.assertRaisesRegex(ValueError, "missing/fixture/unverified source provenance"):
            ingest(path, self.staging, registry_path=self.registry_path, validator=self.validator, licenses=self.licenses)

if __name__ == "__main__":
    unittest.main()
