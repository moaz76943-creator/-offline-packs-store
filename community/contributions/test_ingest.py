import json
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

# Important: make sure we can import the CLI
import ingest

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

        # Override paths in ingest
        self.original_staged_dir = ingest.STAGED_DIR
        self.original_quarantine_dir = ingest.QUARANTINE_DIR
        self.original_manifest_file = ingest.MANIFEST_FILE

        ingest.STAGED_DIR = Path(self.temp_dir) / 'staged'
        ingest.QUARANTINE_DIR = Path(self.temp_dir) / 'quarantined'
        ingest.STAGED_DIR.mkdir()
        ingest.QUARANTINE_DIR.mkdir()
        ingest.MANIFEST_FILE = ingest.STAGED_DIR / 'manifest.json'

        self.valid_data = {
            "contract_version": "1.0.0",
            "document_id": "doc-01",
            "lexemes": [
                {
                    "lexeme_id": "lex-01",
                    "language": "en",
                    "script": "Latn",
                    "lemma": "test",
                    "surface": "test",
                    "pos": "noun",
                    "direction": "ltr",
                    "source": {
                        "source_id": "src-01",
                        "origin_url": "https://example.com/src",
                        "publisher": "Example Pub",
                        "dataset_version": "1.0",
                        "retrieval_id": "ret-01",
                        "license_id": "CC-BY-SA-4.0",
                        "record_locator": "loc-01",
                        "publication_approved": True,
                        "fixture_only": False,
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                    }
                }
            ],
            "senses": [
                {
                    "sense_id": "sense-01",
                    "lexeme_id": "lex-01",
                    "concept_id": "concept-01", "definition": "test definition",
                    "source": {
                        "source_id": "src-01",
                        "origin_url": "https://example.com/src",
                        "publisher": "Example Pub",
                        "dataset_version": "1.0",
                        "retrieval_id": "ret-01",
                        "license_id": "CC-BY-SA-4.0",
                        "record_locator": "loc-01",
                        "publication_approved": True,
                        "fixture_only": False,
                        "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                    }
                }
            ],
            "translations": [],
            "examples": [],
            "relations": []
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        ingest.STAGED_DIR = self.original_staged_dir
        ingest.QUARANTINE_DIR = self.original_quarantine_dir
        ingest.MANIFEST_FILE = self.original_manifest_file

    def write_json(self, data, filename="test.json"):
        filepath = Path(self.temp_dir) / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return filepath

    def write_zip(self, data, filename="test.zip"):
        json_path = self.write_json(data)
        filepath = Path(self.temp_dir) / filename
        with zipfile.ZipFile(filepath, 'w') as zf:
            zf.write(json_path, arcname="test.json")
        return filepath

    def test_valid_submission(self):
        filepath = self.write_json(self.valid_data)

        # Test parse and validate directly
        valid_langs = ingest.get_valid_languages()
        ingest.parse_and_validate_file(filepath, valid_langs)

        # Test full pipeline (simulating main)
        file_hash = ingest.get_hash(filepath)
        ingest.stage_file(filepath, file_hash)
        ingest.update_manifest(file_hash, filepath.name)

        self.assertTrue(ingest.MANIFEST_FILE.exists())
        self.assertTrue(ingest.is_already_processed(file_hash))

        # Ensure it got copied to staged
        staged_files = list(ingest.STAGED_DIR.glob(f"{file_hash}*"))
        self.assertEqual(len(staged_files), 1)

    def test_forged_license(self):
        data = dict(self.valid_data)
        data['lexemes'][0]['source']['license_id'] = 'FORGED-LICENSE'
        filepath = self.write_json(data)

        valid_langs = ingest.get_valid_languages()
        with self.assertRaises(ValueError) as context:
            ingest.parse_and_validate_file(filepath, valid_langs)
        self.assertIn("Unsupported or forged license", str(context.exception))

        # Test quarantine
        file_hash = ingest.get_hash(filepath)
        ingest.quarantine_file(filepath, file_hash, str(context.exception))

        quarantined_files = list(ingest.QUARANTINE_DIR.glob(f"{file_hash}*.json"))
        reason_files = list(ingest.QUARANTINE_DIR.glob(f"{file_hash}*.reason.txt"))
        self.assertEqual(len(quarantined_files), 1)
        self.assertEqual(len(reason_files), 1)

    def test_reversed_language_pair(self):
        data = dict(self.valid_data)

        # Add another lexeme in target language
        data['lexemes'].append({
            "lexeme_id": "lex-02",
            "language": "es",
            "script": "Latn",
            "lemma": "prueba",
            "surface": "prueba",
            "pos": "noun",
            "direction": "ltr",
            "source": data['lexemes'][0]['source']
        })

        # Add senses
        data['senses'].append({
            "sense_id": "sense-02",
            "lexeme_id": "lex-02",
            "concept_id": "concept-01", "definition": "test definition",
            "source": data['senses'][0]['source']
        })

        # Add translation from en to en (reversed / self)
        data['translations'].append({
            "translation_id": "trans-01",
            "from_sense_id": "sense-01",
            "to_sense_id": "sense-01",  # Same language!
            "language": "en",
            "text": "test",
            "equivalence": "exact",
            "source": data['senses'][0]['source']
        })

        filepath = self.write_json(data)
        valid_langs = ingest.get_valid_languages()
        with self.assertRaises(ValueError) as context:
            ingest.parse_and_validate_file(filepath, valid_langs)
        self.assertIn("Reversed or self translation", str(context.exception))

    def test_unknown_language_id(self):
        data = dict(self.valid_data)
        data['lexemes'][0]['language'] = 'xx'
        filepath = self.write_json(data)

        valid_langs = ingest.get_valid_languages()
        with self.assertRaises(ValueError) as context:
            ingest.parse_and_validate_file(filepath, valid_langs)
        self.assertIn("Unknown language ID", str(context.exception))

    def test_duplicate_submission(self):
        filepath = self.write_json(self.valid_data)
        file_hash = ingest.get_hash(filepath)

        # Stage first time
        ingest.stage_file(filepath, file_hash)
        ingest.update_manifest(file_hash, filepath.name)

        self.assertTrue(ingest.is_already_processed(file_hash))

        # Process again (should just return True indicating it's duplicate logic)
        self.assertFalse(ingest.update_manifest(file_hash, filepath.name))

    def test_duplicate_entry_ids(self):
        data = dict(self.valid_data)
        # Duplicate lexeme_id
        data['lexemes'].append(data['lexemes'][0])
        filepath = self.write_json(data)

        valid_langs = ingest.get_valid_languages()
        with self.assertRaises(ValueError) as context:
            ingest.parse_and_validate_file(filepath, valid_langs)
        self.assertIn("Lexical validation failed", str(context.exception))

    def test_malformed_unicode(self):
        filepath = Path(self.temp_dir) / "bad.json"
        with open(filepath, 'wb') as f:
            f.write(b'{"key": "\xff"}')

        valid_langs = ingest.get_valid_languages()
        with self.assertRaises(ValueError) as context:
            ingest.parse_and_validate_file(filepath, valid_langs)
        self.assertIn("Malformed Unicode", str(context.exception))

    def test_corrupt_archive(self):
        filepath = Path(self.temp_dir) / "bad.zip"
        with open(filepath, 'wb') as f:
            f.write(b'PK1234NotAZipArchive')

        with self.assertRaises(zipfile.BadZipFile):
            ingest.extract_bundle(filepath, Path(self.temp_dir))

    def test_unsupported_executable_payload(self):
        filepath = Path(self.temp_dir) / "payload.zip"
        with zipfile.ZipFile(filepath, 'w') as zf:
            zf.writestr("malicious.sh", "echo 'pwned'")

        with self.assertRaises(ValueError) as context:
            ingest.extract_bundle(filepath, Path(self.temp_dir))
        self.assertIn("Unsupported executable payload", str(context.exception))

if __name__ == '__main__':
    unittest.main()
