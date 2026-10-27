import json
import sqlite3
import unittest
from pathlib import Path
import os

from standards.directed_pairs.validate import DirectedPairContractError, validate
from standards.directed_pairs.sqlite_v2 import create_db, map_document

FIXTURE_DIR = Path(__file__).parent / "fixtures"

class TestDirectedPairs(unittest.TestCase):

    def load_fixture(self, name):
        with open(FIXTURE_DIR / name, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_valid_fixture(self):
        doc = self.load_fixture("valid_directed_pairs.json")
        try:
            validate(doc)
        except Exception as e:
            self.fail(f"valid_directed_pairs.json raised Exception unexpectedly: {e}")

    def test_invalid_same_language(self):
        doc = self.load_fixture("invalid_same_language.json")
        with self.assertRaisesRegex(DirectedPairContractError, "must be different"):
            validate(doc)

    def test_invalid_missing_sense(self):
        doc = self.load_fixture("invalid_missing_sense.json")
        with self.assertRaisesRegex(DirectedPairContractError, "missing sense identity"):
            validate(doc)

    def test_invalid_same_sense(self):
        doc = self.load_fixture("invalid_same_sense.json")
        with self.assertRaisesRegex(DirectedPairContractError, "cannot be identical"):
            validate(doc)

    def test_invalid_self_translation(self):
        doc = self.load_fixture("invalid_self_translation.json")
        with self.assertRaisesRegex(DirectedPairContractError, "cannot be identical"):
            validate(doc)

    def test_sqlite_mapping(self):
        doc = self.load_fixture("valid_directed_pairs.json")

        # use in-memory sqlite db for tests
        conn = sqlite3.connect(":memory:")
        create_db(conn)
        map_document(doc, conn)

        cursor = conn.cursor()
        cursor.execute("SELECT pair_id, source_language, target_language, source_sense_id, target_sense_id, target_text, equivalence, fields_json FROM directed_pairs")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 3) # We added 3 fixtures
        row = rows[0]
        self.assertEqual(row[0], "pair.1")
        self.assertEqual(row[1], "eng-US")
        self.assertEqual(row[2], "spa-ES")
        self.assertEqual(row[3], "sense.eng.apple.1")
        self.assertEqual(row[4], "sense.spa.manzana.1")
        self.assertEqual(row[5], "manzana")
        self.assertEqual(row[6], "exact")

        # Check fields_json
        fields = json.loads(row[7])
        self.assertEqual(fields["context"], "fruit")
        self.assertIn("source", fields)

        conn.close()

if __name__ == "__main__":
    unittest.main()
