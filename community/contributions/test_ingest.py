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

    def test_duplicate_entry_id_in_archive(self):
        doc1 = json.loads(json.dumps(self.valid_doc))
        doc2 = json.loads(json.dumps(self.valid_doc))
        doc2["document_id"] = "doc2"
        # Since self.valid_doc has lexemes with no ID right now, let's set an ID explicitly
        doc1["lexemes"][0]["lexeme_id"] = "lex1"
        doc2["lexemes"][0]["lexeme_id"] = "lex1"

        path = Path(self.tmpdir) / "dup_entry.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("doc1.json", json.dumps(doc1))
            zf.writestr("doc2.json", json.dumps(doc2))
        with self.assertRaises(ValueError) as ctx:
            ingest(path, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertIn("duplicate entry ID: lex1", str(ctx.exception))

    def test_resume_interrupted_transaction(self):
        submission = self.write_json("sub.json", self.valid_doc)

        # Simulate partial write (only binary, no index)
        import hashlib
        data = Path(submission).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        staged = self.staging_root / "staged"
        staged.mkdir(exist_ok=True, parents=True)
        (staged / f"{digest}.bin").write_bytes(data)

        # Should recover and write the index
        receipt = ingest(submission, self.staging_root, registry_path=self.registry_path, validator=lambda d, publication: None, licenses={"CC0-1.0"})
        self.assertEqual(receipt["state"], "STAGED_REVIEW_REQUIRED")
        self.assertTrue((self.staging_root / "records" / f"{digest}.json").exists())

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
        from standards.lexical.validate import validate as canonical_validate
        self.registry_path.write_text(json.dumps({"states": {"de": {}, "ar": {}}}))
        source = dict(self.valid_doc['lexemes'][0]['source'])
        source.update(origin_url='https://example.com/fixture',
                      retrieval_id='fixture:retrieval:1',
                      publication_approved=False)
        document = {
            'contract_version': '1.0.0', 'document_id': 'fixture.directed',
            'lexemes': [
                dict(lexeme_id='lex.de.one', language='de', script='Latn',
                     lemma='Haus', surface='Haus', pos='noun',
                     direction='ltr', source=dict(source)),
                dict(lexeme_id='lex.ar.one', language='ar', script='Arab',
                     lemma='بيت', surface='بيت', pos='noun',
                     direction='rtl', source=dict(source)),
            ],
            'senses': [
                dict(sense_id='sense.de.one', lexeme_id='lex.de.one',
                     concept_id='concept.house', definition='house',
                     source=dict(source)),
                dict(sense_id='sense.ar.one', lexeme_id='lex.ar.one',
                     concept_id='concept.house', definition='بيت',
                     source=dict(source)),
            ],
            'translations': [
                dict(translation_id='tr.de.ar', from_sense_id='sense.de.one',
                     to_sense_id='sense.ar.one', language='ar', text='بيت',
                     equivalence='exact', source=dict(source))
            ], 'examples': [], 'relations': [],
        }
        # The positive form must satisfy the *real* lexical contract first.
        canonical_validate(document, publication=False)
        document['translations'][0]['language'] = 'de'
        submission = self.write_json('reversed.json', document)
        with self.assertRaisesRegex(ValueError, 'target language mismatch'):
            ingest(submission, self.staging_root,
                   registry_path=self.registry_path,
                   validator=canonical_validate, licenses={'CC0-1.0'})

if __name__ == "__main__":
    unittest.main()
