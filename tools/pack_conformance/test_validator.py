import unittest
import json
import sqlite3
from pathlib import Path
from tools.pack_conformance.validator import PackConformanceValidator, PackConformanceError
from tools.pack_conformance.fixture_builder import build_all, FIXTURES_DIR
from tools.pack_manifest.builder import compute_sha256

class TestPackConformanceValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_all()
        cls.manifest_path = FIXTURES_DIR / "manifest.json"

        valid_db = FIXTURES_DIR / "valid.db"
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
                    "sha256": compute_sha256(FIXTURES_DIR / "unverified.db")
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
        validator = PackConformanceValidator(FIXTURES_DIR / "valid.db")
        self.assertTrue(validator.validate())

    def test_unverified_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "unverified.db")
        self.assertFalse(validator.validate())

    def test_empty_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "empty.db")
        with self.assertRaisesRegex(PackConformanceError, "Pack is empty"):
            validator.validate()

    def test_corrupt_schema_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "corrupt_schema.db")
        with self.assertRaisesRegex(PackConformanceError, "Invalid POS"):
            validator.validate()

    def test_corrupt_json_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "corrupt_json.db")
        with self.assertRaisesRegex(PackConformanceError, "Corrupt fields_json"):
            validator.validate()

    def test_mismatched_lang_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "mismatched_lang.db")
        with self.assertRaisesRegex(PackConformanceError, "Cross-language mislabeled package"):
            validator.validate()

    def test_missing_fts_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "missing_fts.db")
        with self.assertRaisesRegex(PackConformanceError, "Incompatible or missing FTS5 index|lexicon_fts is not an FTS5 table"):
            validator.validate()

    def test_missing_metadata_pack(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "missing_metadata.db")
        with self.assertRaisesRegex(PackConformanceError, "Missing mandatory metadata fields"):
            validator.validate()

    def test_missing_file(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "does_not_exist.db")
        with self.assertRaises(FileNotFoundError):
            validator.validate()

    def test_manifest_valid(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "valid.db", self.manifest_path)
        self.assertTrue(validator.validate())

    def test_manifest_mismatch_count(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "unverified.db", self.manifest_path)
        with self.assertRaisesRegex(PackConformanceError, "Mismatched declared count"):
            validator.validate()

    def test_manifest_mismatch_hash(self):
        validator = PackConformanceValidator(FIXTURES_DIR / "corrupt_schema.db", self.manifest_path)
        with self.assertRaisesRegex(PackConformanceError, "Hash mismatch"):
            validator.validate()


if __name__ == '__main__':
    unittest.main()
