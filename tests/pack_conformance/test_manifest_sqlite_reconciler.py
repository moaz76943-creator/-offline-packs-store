import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.pack_conformance.manifest_sqlite_reconciler import reconcile_manifest_entry

class TestManifestSqliteReconciler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pack_path = os.path.join(self.temp_dir.name, "test.pack")
        conn = sqlite3.connect(self.pack_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE pack_info (key TEXT, value TEXT);")
        cur.execute("CREATE TABLE vocabulary (id INT);")
        cur.execute("INSERT INTO pack_info VALUES ('pack_id', 'de_ar_a1');")
        cur.execute("INSERT INTO vocabulary VALUES (1), (2), (3);")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reconciliation_success(self):
        manifest_entry = {"pack_id": "de_ar_a1", "entry_count": 3}
        valid, errors = reconcile_manifest_entry(self.pack_path, manifest_entry)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_reconciliation_count_mismatch_fails(self):
        manifest_entry = {"pack_id": "de_ar_a1", "entry_count": 5} # ادعاء غير متطابق
        valid, errors = reconcile_manifest_entry(self.pack_path, manifest_entry)
        self.assertFalse(valid)
        self.assertTrue(any("Row count mismatch" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
