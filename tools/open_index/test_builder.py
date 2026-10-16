import unittest
import sqlite3
import os
import tempfile
import shutil
from builder import build_index

class TestOpenIndex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        conn = sqlite3.connect(self.db_path)
        conn.execute('CREATE TABLE lexicon(id TEXT PRIMARY KEY, surface TEXT NOT NULL, language_code TEXT NOT NULL)')
        # Latin with accents
        conn.execute("INSERT INTO lexicon VALUES ('test_id1', 'café crème', 'fra')")
        # CJK (trigram)
        conn.execute("INSERT INTO lexicon VALUES ('test_id2', '你好世界', 'zho')")
        # Arabic RTL
        conn.execute("INSERT INTO lexicon VALUES ('test_id3', 'مرحبا', 'ara')")
        # Hebrew RTL
        conn.execute("INSERT INTO lexicon VALUES ('test_id4', 'שלום', 'heb')")
        # Thai (trigram)
        conn.execute("INSERT INTO lexicon VALUES ('test_id5', 'สวัสดี', 'tha')")

        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.db_path + '.staged'):
            os.remove(self.db_path + '.staged')
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_index(self):
        build_index(self.db_path)
        conn = sqlite3.connect(self.db_path)

        # Test fra (unicode61, diacritics removed ideally)
        res = conn.execute("SELECT id FROM lexicon_fts WHERE lexicon_fts MATCH 'cafe'").fetchall()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 'test_id1')

        # Test ara (unicode61)
        res = conn.execute("SELECT id FROM lexicon_fts WHERE lexicon_fts MATCH 'مرحبا'").fetchall()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 'test_id3')

        # Test heb (unicode61)
        res = conn.execute("SELECT id FROM lexicon_fts WHERE lexicon_fts MATCH 'שלום'").fetchall()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 'test_id4')

        # Test zho with trigram
        res = conn.execute("SELECT id FROM lexicon_fts_cjk WHERE lexicon_fts_cjk MATCH '你好世'").fetchall()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 'test_id2')

        # Test tha with trigram
        res = conn.execute("SELECT id FROM lexicon_fts_cjk WHERE lexicon_fts_cjk MATCH 'สวัสดี'").fetchall()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], 'test_id5')

        conn.close()

    def test_invalid_sqlite(self):
        # Create an invalid file
        invalid_path = os.path.join(self.temp_dir, 'invalid.db')
        with open(invalid_path, 'w') as f:
            f.write("This is not a valid SQLite database.")

        with self.assertRaises(ValueError):
            build_index(invalid_path)

        if os.path.exists(invalid_path):
            os.remove(invalid_path)

    def test_atomic_replacement_failure(self):
        conn = sqlite3.connect(self.db_path)
        # Create an invalid state to cause an error
        conn.execute("DROP TABLE lexicon")
        conn.commit()
        conn.close()

        with self.assertRaises(sqlite3.OperationalError):
            build_index(self.db_path)

        # The original db file should still exist and not be replaced by a staged version
        self.assertTrue(os.path.exists(self.db_path))
        self.assertFalse(os.path.exists(self.db_path + '.staged'))

if __name__ == '__main__':
    unittest.main()
