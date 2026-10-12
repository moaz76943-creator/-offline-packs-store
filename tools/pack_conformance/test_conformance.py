import unittest
import tempfile
import pathlib
import os

from tools.pack_conformance.engine import verify_pack, ConformanceError, UnverifiedWarning
from tools.pack_conformance.fixtures import generate_pack

class TestPackConformance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_pack(self):
        pack_path = self.root / "valid.pack.gz"
        generate_pack(pack_path)
        verify_pack(pack_path)  # Should not raise

    def test_invalid_gzip(self):
        pack_path = self.root / "bad_gzip.pack.gz"
        pack_path.write_bytes(b"not a gzip")
        with self.assertRaisesRegex(ConformanceError, "valid gzip"):
            verify_pack(pack_path)

    def test_missing_envelope_fields(self):
        pack_path = self.root / "missing_env.pack.gz"
        generate_pack(pack_path, envelope_override={'schemaVersion': '1.0'})
        with self.assertRaisesRegex(ConformanceError, "schemaVersion in envelope"):
            verify_pack(pack_path)

    def test_hash_mismatch(self):
        pack_path = self.root / "hash_mismatch.pack.gz"
        generate_pack(pack_path, metadata_override={'contentSha256': 'wronghash'})
        with self.assertRaisesRegex(ConformanceError, "contentSha256 mismatch"):
            verify_pack(pack_path)

    def test_pack_id_mismatch(self):
        pack_path = self.root / "pack_id_mismatch.pack.gz"
        generate_pack(pack_path, metadata_override={'packId': 'fr'})
        with self.assertRaisesRegex(ConformanceError, "packId mismatch"):
            verify_pack(pack_path)

    def test_missing_fts_table(self):
        pack_path = self.root / "no_fts.pack.gz"
        generate_pack(pack_path, skip_fts=True)
        with self.assertRaisesRegex(ConformanceError, "Missing lexicon_fts table"):
            verify_pack(pack_path)

    def test_unverified_warning_zero_rows(self):
        pack_path = self.root / "zero_rows.pack.gz"
        def db_setup(conn):
            conn.execute('''CREATE TABLE lexicon (
                id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                direction TEXT NOT NULL, fields_json TEXT NOT NULL,
                cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT
            )''')
            conn.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, translation_ar, tokenize='trigram')")

        generate_pack(pack_path, db_setup_override=db_setup, metadata_override={'contentRows': 0, 'verbRows': 0})
        with self.assertRaisesRegex(UnverifiedWarning, "0 rows found"):
            verify_pack(pack_path)

    def test_row_count_mismatch(self):
        pack_path = self.root / "row_count_mismatch.pack.gz"
        generate_pack(pack_path, metadata_override={'contentRows': 999})
        with self.assertRaisesRegex(ConformanceError, "Row count mismatch"):
            verify_pack(pack_path)

    def test_invalid_pos(self):
        pack_path = self.root / "invalid_pos.pack.gz"
        def db_setup(conn):
            conn.execute('''CREATE TABLE lexicon (
                id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                direction TEXT NOT NULL, fields_json TEXT NOT NULL,
                cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT
            )''')
            conn.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, translation_ar, tokenize='trigram')")
            conn.execute("INSERT INTO lexicon VALUES ('1', 'hello', '', 'ltr', '{}', 'A1', 1, 'hello')")
            conn.execute("INSERT INTO lexicon_fts(rowid, surface, translation_ar) VALUES (1, 'hello', 'marhaba')")
            conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
            conn.commit()

        generate_pack(pack_path, db_setup_override=db_setup, metadata_override={'contentRows': 1, 'verbRows': 0})
        with self.assertRaisesRegex(ConformanceError, "part_of_speech must not be empty"):
            verify_pack(pack_path)

    def test_invalid_direction(self):
        pack_path = self.root / "invalid_dir.pack.gz"
        def db_setup(conn):
            conn.execute('''CREATE TABLE lexicon (
                id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                direction TEXT NOT NULL, fields_json TEXT NOT NULL,
                cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT
            )''')
            conn.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, translation_ar, tokenize='trigram')")
            conn.execute("INSERT INTO lexicon VALUES ('1', 'hello', 'noun', 'up', '{}', 'A1', 1, 'hello')")
            conn.execute("INSERT INTO lexicon_fts(rowid, surface, translation_ar) VALUES (1, 'hello', 'marhaba')")
            conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
            conn.commit()

        generate_pack(pack_path, db_setup_override=db_setup, metadata_override={'contentRows': 1, 'verbRows': 0})
        with self.assertRaisesRegex(ConformanceError, "Invalid direction"):
            verify_pack(pack_path)

if __name__ == '__main__':
    unittest.main()
