import os
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.search_qa.fts5_search_qa import (
    create_fts5_index_schema,
    index_entry,
    search_fts5,
    verify_search_pack_qa
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

    def test_quotes_and_fts_syntax_remain_literal(self):
        for term in ('12"', 'book":'):
            index_entry(self.conn, term, 'fixture')
            self.assertIn(term, [row[0] for row in search_fts5(self.conn, term)])

    def test_ordinary_table_is_not_a_verified_fts_index(self):
        self.conn.execute('DROP TABLE fts_lexicon')
        self.conn.execute('CREATE TABLE fts_lexicon(unrelated TEXT)')
        self.conn.commit()
        self.assertFalse(verify_search_pack_qa(self.temp_db.name)[0])

    def test_missing_columns_and_bad_normalized_projection_fail(self):
        self.conn.execute('DROP TABLE fts_lexicon')
        self.conn.execute('CREATE VIRTUAL TABLE fts_lexicon USING fts5(display_term)')
        self.conn.commit()
        self.assertFalse(verify_search_pack_qa(self.temp_db.name)[0])
        self.conn.execute('DROP TABLE fts_lexicon')
        create_fts5_index_schema(self.conn)
        self.conn.execute('INSERT INTO fts_lexicon VALUES (?, ?, ?)', ('مَدْرَسَةٌ', 'incorrect', 'school'))
        self.conn.commit()
        self.assertFalse(verify_search_pack_qa(self.temp_db.name)[0])

    def test_empty_index_cannot_verify_and_valid_dual_projection_can(self):
        self.assertFalse(verify_search_pack_qa(self.temp_db.name)[0])
        index_entry(self.conn, 'مَدْرَسَةٌ', 'school')
        self.assertTrue(verify_search_pack_qa(self.temp_db.name)[0])

if __name__ == "__main__":
    unittest.main()
