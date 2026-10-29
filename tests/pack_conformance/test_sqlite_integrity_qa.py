import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.pack_conformance.sqlite_integrity_qa import audit_sqlite_pack

class TestSqliteIntegrityQa(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.valid_db = os.path.join(self.temp_dir.name, "valid.pack")
        conn = sqlite3.connect(self.valid_db)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY);")
        cur.execute("CREATE TABLE child (id INTEGER, p_id INTEGER REFERENCES parent(id));")
        cur.execute("INSERT INTO parent VALUES (1);")
        cur.execute("INSERT INTO child VALUES (10, 1);")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_db(self):
        valid, errors = audit_sqlite_pack(self.valid_db)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_corrupted_header(self):
        corrupt_file = os.path.join(self.temp_dir.name, "corrupt.pack")
        # كتابة ملف أكبر من 16 بايت بهيدر غير صالح
        with open(corrupt_file, "wb") as f:
            f.write(b"CORRUPTED_NON_SQLITE_MAGIC_HEADER_TEST_BYTES_PADDING_1234567890")
        valid, errors = audit_sqlite_pack(corrupt_file)
        self.assertFalse(valid)
        self.assertTrue(any("Invalid SQLite header" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
