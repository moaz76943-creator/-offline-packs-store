import json
import os
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.pack_conformance.manifest_sqlite_reconciler import (
    get_actual_sqlite_counts,
    reconcile_pack_in_manifest
)

class TestManifestSqliteReconciler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pack.db")
        self.manifest_path = os.path.join(self.temp_dir.name, "manifest.json")

        # Create dummy SQLite database with known row counts
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA user_version = 2;")
        cur.execute("CREATE TABLE lexicon (id INTEGER PRIMARY KEY, term TEXT);")
        cur.execute("CREATE TABLE senses (id INTEGER PRIMARY KEY, gloss TEXT);")
        cur.execute("INSERT INTO lexicon VALUES (1, 'Haus'), (2, 'Baum');") # 2 rows
        cur.execute("INSERT INTO senses VALUES (1, 'house'), (2, 'home'), (3, 'tree');") # 3 rows
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reconciles_manifest_discrepancy_with_ground_truth(self):
        # Manifest falsely claims 100 words and 200 senses
        initial_manifest = {
            "packs": [{
                "pack_id": "test_de",
                "lexicon_count": 100,
                "senses_count": 200
            }]
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(initial_manifest, f)

        ok, msg = reconcile_pack_in_manifest(self.manifest_path, "test_de", self.db_path)
        self.assertTrue(ok)
        self.assertIn("RECONCILED", msg)

        # Verify manifest now reflects ground truth
        with open(self.manifest_path, 'r') as f:
            updated = json.load(f)

        pack_entry = updated['packs'][0]
        self.assertEqual(pack_entry['lexicon_count'], 2)
        self.assertEqual(pack_entry['senses_count'], 3)
        self.assertEqual(pack_entry['schema_version'], 2)

if __name__ == "__main__":
    unittest.main()
