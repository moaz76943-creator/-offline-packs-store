import json
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from community.contributions.ingest import ingest, quarantine_submission

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.staging_root = Path(self.tmp_dir) / "staging"

        with open('standards/lexical/fixtures/positive.json') as f:
            self.base_doc = json.load(f)

        def traverse(value):
            if isinstance(value, list):
                for child in value:
                    traverse(child)
            elif isinstance(value, dict):
                if "source" in value:
                    source = value["source"]
                    source["fixture_only"] = False
                    source["license_id"] = "CC0-1.0"
                    source["artifact_sha256"] = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
                for child in value.values():
                    traverse(child)

        traverse(self.base_doc)

        self.valid_json_path = Path(self.tmp_dir) / "valid.json"
        with open(self.valid_json_path, 'w') as f:
            json.dump(self.base_doc, f)

        self.valid_zip_path = Path(self.tmp_dir) / "valid.zip"
        with zipfile.ZipFile(self.valid_zip_path, 'w') as z:
            z.write(self.valid_json_path, "valid.json")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_valid_submission(self):
        receipt = ingest(self.valid_zip_path, self.staging_root)
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(receipt["documents"], 1)
        self.assertTrue(receipt["sha256"] + ".bin" in os.listdir(self.staging_root / "staged"))
        self.assertTrue(receipt["sha256"] + ".json" in os.listdir(self.staging_root / "records"))

        receipt2 = ingest(self.valid_zip_path, self.staging_root)
        self.assertEqual(receipt, receipt2)

    def test_forged_license(self):
        doc = json.loads(json.dumps(self.base_doc))
        doc["lexemes"][0]["source"]["license_id"] = "Forged-License"
        path = Path(self.tmp_dir) / "forged.json"
        with open(path, 'w') as f:
            json.dump(doc, f)

        with self.assertRaises(ValueError) as ctx:
            ingest(path, self.staging_root)
        self.assertIn("missing/fixture/unverified source provenance", str(ctx.exception))

    def test_reversed_pairs(self):
        doc = json.loads(json.dumps(self.base_doc))
        doc["translations"][0]["language"] = "xyz"
        path = Path(self.tmp_dir) / "reversed.json"
        with open(path, 'w') as f:
            json.dump(doc, f)

        with self.assertRaises(Exception) as ctx:
            ingest(path, self.staging_root)
        self.assertTrue("target language mismatch" in str(ctx.exception) or "unregistered language" in str(ctx.exception))

    def test_malformed_unicode(self):
        path = Path(self.tmp_dir) / "malformed.json"
        with open(path, 'wb') as f:
            f.write(b'{"key": "\xff"}')

        with self.assertRaises(UnicodeDecodeError):
            ingest(path, self.staging_root)

    def test_corrupt_archive(self):
        path = Path(self.tmp_dir) / "corrupt.zip"
        with open(path, 'wb') as f:
            f.write(b'PK\x03\x041234567890')

        with self.assertRaises(zipfile.BadZipFile):
            ingest(path, self.staging_root)

    def test_duplicate_submissions(self):
        doc = json.loads(json.dumps(self.base_doc))
        path = Path(self.tmp_dir) / "dup.zip"
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr("doc1.json", json.dumps(doc))
            z.writestr("doc2.json", json.dumps(doc))

        with self.assertRaises(ValueError) as ctx:
            ingest(path, self.staging_root)
        self.assertIn("duplicate document ID", str(ctx.exception))

    def test_quarantine(self):
        receipt = quarantine_submission(self.valid_zip_path, self.staging_root, "test reason")
        self.assertEqual(receipt["state"], "QUARANTINED")
        self.assertEqual(receipt["reason"], "test reason")
        self.assertTrue(receipt["sha256"] + ".bin" in os.listdir(self.staging_root / "quarantined"))

if __name__ == '__main__':
    unittest.main()
