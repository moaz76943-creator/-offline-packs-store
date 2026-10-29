import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.search_qa.fts5_search_qa import (
    create_dual_projection_fts_table,
    index_search_term,
    execute_tolerant_search,
)

class TestFts5SearchQa(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        create_dual_projection_fts_table(self.conn)
        index_search_term(self.conn, 1, "Äpfel", "Aepfel Apfel", "تفاح")
        index_search_term(self.conn, 2, "كِتَابٌ", "كتاب", "Buch")

    def tearDown(self):
        self.conn.close()

    def test_search_by_display_term(self):
        results = execute_tolerant_search(self.conn, "Äpfel")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "Äpfel")

    def test_search_by_normalized_key(self):
        results = execute_tolerant_search(self.conn, "Apfel")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "Äpfel")

    def test_search_arabic_unvoweled(self):
        results = execute_tolerant_search(self.conn, "كتاب")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "كِتَابٌ")

if __name__ == '__main__':
    unittest.main()
