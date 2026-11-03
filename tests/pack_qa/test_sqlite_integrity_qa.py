import os
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.pack_conformance.sqlite_integrity_qa import verify_pack_sqlite_conformance

class TestSqliteIntegrityQa(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_pack_conforms(self):
        db_path = os.path.join(self.temp_dir.name, "valid_pack.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA user_version = 2;")
        cur.execute("CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, val TEXT);")
        cur.execute("CREATE TABLE concepts (id INTEGER PRIMARY KEY, concept_key TEXT);")
        cur.execute("CREATE TABLE senses (id INTEGER PRIMARY KEY, concept_id INTEGER REFERENCES concepts(id));")
        cur.execute("CREATE TABLE lexicon (id INTEGER PRIMARY KEY, term TEXT);")
        cur.execute("CREATE TABLE translations (id INTEGER PRIMARY KEY, sense_id INTEGER REFERENCES senses(id));")
        
        cur.execute("INSERT INTO concepts VALUES (1, 'c_greeting');")
        cur.execute("INSERT INTO senses VALUES (1, 1);")
        cur.execute("INSERT INTO lexicon VALUES (1, 'Hallo');")
        cur.execute("INSERT INTO translations VALUES (1, 1);")
        conn.commit()
        conn.close()

        passed, msg = verify_pack_sqlite_conformance(db_path)
        self.assertTrue(passed)
        self.assertIn("CONFORMANCE_PASSED", msg)

    def test_broken_foreign_key_fails_closed(self):
        db_path = os.path.join(self.temp_dir.name, "broken_fk.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;") # Bypass during insert to create violation
        cur.execute("PRAGMA user_version = 2;")
        cur.execute("CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, val TEXT);")
        cur.execute("CREATE TABLE concepts (id INTEGER PRIMARY KEY);")
        cur.execute("CREATE TABLE senses (id INTEGER PRIMARY KEY, concept_id INTEGER REFERENCES concepts(id));")
        cur.execute("CREATE TABLE lexicon (id INTEGER PRIMARY KEY, term TEXT);")
        cur.execute("CREATE TABLE translations (id INTEGER PRIMARY KEY);")
        
        cur.execute("INSERT INTO senses VALUES (1, 999);") # Orphaned concept_id 999
        cur.execute("INSERT INTO lexicon VALUES (1, 'Test');")
        conn.commit()
        conn.close()

        passed, msg = verify_pack_sqlite_conformance(db_path)
        self.assertFalse(passed)
        self.assertIn("FOREIGN_KEY_VIOLATIONS_DETECTED", msg)

if __name__ == "__main__":
    unittest.main()
