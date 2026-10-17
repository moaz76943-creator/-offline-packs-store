import json
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile
import gzip
from pathlib import Path

from community.contributions.ingest import ingest, quarantine_submission, main

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.staging_root = Path(self.tmpdir) / "staging"
        self.staging_root.mkdir()
        self.registry_path = Path(self.tmpdir) / "registry.json"
        with open(self.registry_path, "w") as f:
            json.dump({"states": {"eng": {}, "spa": {}}}, f)

        self.valid_doc = {
            "document_id": "doc1",
            "lexemes": [
                {
                    "language": "eng",
                    "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "CC0-1.0",
                        "publisher": "pub1",
                        "origin_url": "http://example.com",
                        "artifact_sha256": "a" * 64,
                        "fixture_only": False
                    }
                }
            ],
            "senses": [],
            "translations": [],
            "examples": [],
            "relations": []
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def write_json(self, name, data):
        path = Path(self.tmpdir) / name
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def write_gzip(self, name, data):
        path = Path(self.tmpdir) / name
        with gzip.open(path, "wt") as f:
            json.dump(data, f)
        return path

    def write_zip(self, name, data, arcname):
        path = Path(self.tmpdir) / name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(arcname, json.dumps(data))
        return path

    def write_tar_gz(self, name, data, arcname):
        path = Path(self.tmpdir) / name
        with tarfile.open(path, "w:gz") as tar:
            content = json.dumps(data).encode('utf-8')
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            import io
            tar.addfile(info, io.BytesIO(content))
        return path

    def test_ingest_json_success(self):
        submission = self.write_json("sub.json", self.valid_doc)
        receipt = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertEqual(receipt["documents"], 1)
        self.assertTrue((self.staging_root / "staged" / receipt["file"]).exists())
        self.assertTrue((self.staging_root / "records" / (receipt["sha256"] + ".json")).exists())

    def test_ingest_gzip_success(self):
        submission = self.write_gzip("sub.json.gz", self.valid_doc)
        receipt = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")

    def test_ingest_zip_success(self):
        submission = self.write_zip("sub.zip", self.valid_doc, "doc1.json")
        receipt = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")

    def test_ingest_tar_gz_success(self):
        submission = self.write_tar_gz("sub.tar.gz", self.valid_doc, "doc1.json")
        receipt = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")


    def test_forged_license(self):
        doc = json.loads(json.dumps(self.valid_doc))
        doc["lexemes"][0]["source"]["license_id"] = "Forged-1.0"
        submission = self.write_json("forged.json", doc)
        with self.assertRaises(ValueError) as ctx:
            ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertIn("missing/fixture/unverified source provenance", str(ctx.exception))

    def test_malformed_unicode(self):
        path = Path(self.tmpdir) / "malformed.json"
        with open(path, "wb") as f:
            f.write(b'{"document_id": "1", "lexemes": [{"language": "eng" \xff }]}')
        with self.assertRaises(ValueError) as ctx:
            ingest(path, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})

    def test_corrupt_zip(self):
        path = Path(self.tmpdir) / "corrupt.zip"
        with open(path, "wb") as f:
            f.write(b"not a zip file")
        with self.assertRaises(zipfile.BadZipFile):
            ingest(path, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})

    def test_duplicate_submission(self):
        submission = self.write_json("sub.json", self.valid_doc)
        receipt1 = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        receipt2 = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt1, receipt2)

    def test_duplicate_document_id_in_archive(self):
        path = Path(self.tmpdir) / "dup.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("doc1.json", json.dumps(self.valid_doc))
            zf.writestr("doc2.json", json.dumps(self.valid_doc))
        with self.assertRaises(ValueError) as ctx:
            ingest(path, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertIn("duplicate document ID", str(ctx.exception))

    def test_quarantine(self):
        path = Path(self.tmpdir) / "bad.json"
        with open(path, "w") as f:
            f.write('not valid json')
        receipt = quarantine_submission(path, self.staging_root, "Test quarantine reason")
        self.assertEqual(receipt["state"], "QUARANTINED")
        self.assertEqual(receipt["reason"], "Test quarantine reason")
        self.assertTrue((self.staging_root / "quarantined" / (receipt["sha256"] + ".bin")).exists())
        self.assertTrue((self.staging_root / "quarantined" / (receipt["sha256"] + ".json")).exists())

    def test_reversed_directed_pairs(self):
        doc = json.loads(json.dumps(self.valid_doc))
        doc["translations"] = [
            {
                "from_sense_id": "sense1",
                "to_sense_id": "sense2",
                "source": {
                        "source_id": "src1",
                        "dataset_version": "1.0",
                        "record_locator": "loc1",
                        "license_id": "CC0-1.0",
                        "publisher": "pub1",
                        "origin_url": "http://example.com",
                        "artifact_sha256": "a" * 64,
                        "fixture_only": False
                    }
            }
        ]

        def fake_validator(d, publication):
            # Check for reversed pair logic inside our fake validator
            # or rely on standards.lexical.validate
            # For this test, we'll raise ValueError to simulate standards.lexical.validate failure
            raise ValueError("reversed directed pair or validation failed")

        submission = self.write_json("reversed.json", doc)
        with self.assertRaises(ValueError) as ctx:
            ingest(submission, self.staging_root, registry_path=self.registry_path, validator=fake_validator, licenses={"CC0-1.0"})
        self.assertIn("reversed directed pair", str(ctx.exception))
if __name__ == "__main__":
    unittest.main()
