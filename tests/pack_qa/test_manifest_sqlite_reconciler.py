import json
import os
import sqlite3
import tempfile
import unittest
import sys
from unittest import mock
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
            "schema_version": "1.0.0",
            "packs": {"test_de": {
                "path": "test_de.pack.gz",
                "entry_count": 100,
                "lexicon_count": 100,
                "senses_count": 200,
                "sha256": "f" * 64,
                "size_bytes": 500
            }}
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(initial_manifest, f)

        ok, msg = reconcile_pack_in_manifest(self.manifest_path, "test_de", self.db_path)
        self.assertTrue(ok)
        self.assertIn("RECONCILED", msg)

        # Verify manifest now reflects ground truth
        with open(self.manifest_path, 'r') as f:
            updated = json.load(f)

        pack_entry = updated['packs']['test_de']
        self.assertEqual(pack_entry['entry_count'], 2)
        self.assertEqual(pack_entry['lexicon_count'], 2)
        self.assertEqual(pack_entry['senses_count'], 3)
        self.assertEqual(pack_entry['schema_version'], 2)
        self.assertEqual(pack_entry['size_bytes'], 500)
        self.assertEqual(pack_entry['sha256'], 'f' * 64)
        self.assertEqual(updated['schema_version'], '1.0.0')

    def test_missing_pack_remains_unpublished_and_unchanged(self):
        original = {"packs": {"existing": {"path": "x", "entry_count": 2}}}
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(original, f)
        ok, msg = reconcile_pack_in_manifest(self.manifest_path, "missing", self.db_path)
        self.assertFalse(ok)
        self.assertIn("PACK_NOT_FOUND", msg)
        with open(self.manifest_path, encoding='utf-8') as f:
            self.assertEqual(json.load(f), original)

    def test_reject_list_based_manifest(self):
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump({"packs": [{"pack_id": "test_de"}]}, f)
        ok, _ = reconcile_pack_in_manifest(self.manifest_path, "test_de", self.db_path)
        self.assertFalse(ok)

    def test_write_failure_preserves_original_manifest(self):
        original = {"schema_version": "1.0.0",
                    "packs": {"test_de": {"entry_count": 100, "sha256": "f" * 64}}}
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(original, f)
        with open(self.manifest_path, 'rb') as f:
            before = f.read()
        with mock.patch('tools.gha_factory.pack_conformance.manifest_sqlite_reconciler.json.dump',
                        side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                reconcile_pack_in_manifest(self.manifest_path, "test_de", self.db_path)
        with open(self.manifest_path, 'rb') as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(any(name.startswith('.manifest-reconcile-')
                             for name in os.listdir(self.temp_dir.name)))

if __name__ == "__main__":
    unittest.main()
