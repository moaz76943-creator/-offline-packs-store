import tempfile
import unittest
import json
import sqlite3
from pathlib import Path
from tools.pack_conformance.validator import PackConformanceValidator, PackConformanceError
from tools.pack_conformance.fixture_builder import build_all
from tools.pack_manifest.builder import compute_sha256

class TestPackConformanceValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.fixtures = Path(cls.temp.name)
        build_all(cls.fixtures)
        cls.manifest_path = cls.fixtures / "manifest.json"

        valid_db = cls.fixtures / "valid.db"
        count = 1 # valid.db has 1 lexeme
        sha256 = compute_sha256(valid_db)

        manifest = {
            "packs": {
                "valid": {
                    "path": "valid.db",
                    "entry_count": count,
                    "sha256": sha256
                },
                "mismatch_count": {
                    "path": "unverified.db",
                    "entry_count": 999,
                    "sha256": compute_sha256(cls.fixtures / "unverified.db")
                },
                "mismatch_hash": {
                    "path": "corrupt_schema.db",
                    "entry_count": 1,
                    "sha256": "badhash"
                }
            }
        }

        with open(cls.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f)

    def test_valid_pack(self):
        validator = PackConformanceValidator(self.fixtures / "valid.db")
        self.assertFalse(validator.validate())

    def test_unverified_pack(self):
        validator = PackConformanceValidator(self.fixtures / "unverified.db")
        self.assertFalse(validator.validate())

    def test_empty_pack(self):
        validator = PackConformanceValidator(self.fixtures / "empty.db")
        with self.assertRaisesRegex(PackConformanceError, "Pack is empty"):
            validator.validate()

    def test_corrupt_schema_pack(self):
        validator = PackConformanceValidator(self.fixtures / "corrupt_schema.db")
        with self.assertRaisesRegex(PackConformanceError, "Invalid POS"):
            validator.validate()

    def test_corrupt_json_pack(self):
        validator = PackConformanceValidator(self.fixtures / "corrupt_json.db")
        with self.assertRaisesRegex(PackConformanceError, "Corrupt JSON"):
            validator.validate()

    def test_multilingual_pack_is_valid_when_each_row_matches_its_payload(self):
        # The reference builder supports directed relations across languages.
        candidate = self.fixtures / "mismatched_lang.db"
        validator = PackConformanceValidator(candidate)
        self.assertFalse(validator.validate())  # Synthetic source is unverified.
        self.assertEqual(validator.language_codes, {'en', 'es'})
        self.assertIsNone(validator.language_code)

        # A tampered per-row language is still rejected, even though
        # multiple *valid* languages are allowed in one database.
        with sqlite3.connect(candidate) as db:
            db.execute("UPDATE lexicon SET language_code='fr' WHERE id='lex2'")
        with self.assertRaisesRegex(PackConformanceError, 'projection mismatch'):
            validator.validate()

    def test_missing_fts_pack(self):
        validator = PackConformanceValidator(self.fixtures / "missing_fts.db")
        with self.assertRaisesRegex(PackConformanceError, "schema mismatch"):
            validator.validate()

    def test_missing_metadata_pack(self):
        validator = PackConformanceValidator(self.fixtures / "missing_metadata.db")
        with self.assertRaisesRegex(PackConformanceError, "Missing mandatory metadata fields"):
            validator.validate()

    def test_missing_file(self):
        validator = PackConformanceValidator(self.fixtures / "does_not_exist.db")
        with self.assertRaises(FileNotFoundError):
            validator.validate()

    def test_manifest_valid(self):
        validator = PackConformanceValidator(self.fixtures / "valid.db", self.manifest_path)
        self.assertFalse(validator.validate())

    def test_manifest_mismatch_count(self):
        validator = PackConformanceValidator(self.fixtures / "unverified.db", self.manifest_path)
        with self.assertRaisesRegex(PackConformanceError, "Mismatched declared count"):
            validator.validate()

    def test_manifest_mismatch_hash(self):
        validator = PackConformanceValidator(self.fixtures / "corrupt_schema.db", self.manifest_path)
        with self.assertRaisesRegex(PackConformanceError, "Hash mismatch"):
            validator.validate()


if __name__ == '__main__':
    unittest.main()
