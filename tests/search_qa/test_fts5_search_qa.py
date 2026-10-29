import os
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.search_qa.fts5_search_qa import (
    create_fts5_index_schema,
    index_entry,
    search_fts5
)

class TestFts5SearchQa(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.conn = sqlite3.connect(self.temp_db.name)
        create_fts5_index_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_arabic_diacritic_insensitive_search(self):
        # Entry with full Harakat
        index_entry(self.conn, "مَدْرَسَةٌ", "school")
        # Query with zero Harakat
        matches = search_fts5(self.conn, "مدرسة")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "مَدْرَسَةٌ")

    def test_hamza_variant_insensitive_search(self):
        # Entry with Madda
        index_entry(self.conn, "قُرْآنٌ", "Quran")
        # Query with plain Alef
        matches = search_fts5(self.conn, "قران")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "قُرْآنٌ")

    def test_german_prefix_search(self):
        index_entry(self.conn, "Lernprozess", "learning process")
        matches = search_fts5(self.conn, "Lern")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "Lernprozess")

if __name__ == "__main__":
    unittest.main()
