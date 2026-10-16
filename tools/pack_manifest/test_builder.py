import unittest
import os
import json
import gzip
import zlib
from tools.pack_manifest.builder import ManifestBuilder, generate_update_plan, build_system_manifest

class TestPackManifest(unittest.TestCase):
    def setUp(self):
        self.builder = ManifestBuilder()
        os.makedirs("test_data", exist_ok=True)

        self.pack_data = {
            "lang_code": "xy",
            "license": "CC0",
            "terms_count": 2,
            "terms": [{"word": "a"}, {"word": "b"}],
            "dependencies": ["abc"],
            "provenance": "test-source"
        }
        with gzip.open("test_data/xy_core.pack.gz", "wb") as f:
            f.write(json.dumps(self.pack_data).encode('utf-8'))

        self.vct_data = {
            "license": "CC-BY",
            "paths": ["a", "b", "c"]
        }
        with open("test_data/icon.vct", "wb") as f:
            f.write(zlib.compress(json.dumps(self.vct_data).encode('utf-8')))

    def tearDown(self):
        for f in ["test_data/xy_core.pack.gz", "test_data/icon.vct", "test_data/bad.pack.gz", "test_data/old_manifest.json"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists("test_data"):
            os.rmdir("test_data")

    def test_build_manifest_gz(self):
        manifest = self.builder.build_manifest("test_data/xy_core.pack.gz")
        self.assertEqual(manifest["language"], "xy")
        self.assertEqual(manifest["license"], "CC0")
        self.assertEqual(manifest["entry_count"], 2)
        self.assertIn("sha256", manifest)

    def test_build_manifest_vct(self):
        manifest = self.builder.build_manifest("test_data/icon.vct")
        self.assertEqual(manifest["license"], "CC-BY")
        self.assertEqual(manifest["entry_count"], 3)

    def test_mismatched_entry_count(self):
        bad_data = {
            "lang_code": "zz",
            "terms_count": 5,
            "terms": [{"word": "a"}] # only 1
        }
        with gzip.open("test_data/bad.pack.gz", "wb") as f:
            f.write(json.dumps(bad_data).encode('utf-8'))

        with self.assertRaises(ValueError):
            self.builder.build_manifest("test_data/bad.pack.gz")

    def test_path_traversal(self):
        with self.assertRaises(ValueError):
            self.builder.build_manifest("../test_data/xy_core.pack.gz")
        with self.assertRaises(ValueError):
            self.builder.build_manifest("/etc/passwd")

    def test_update_plan_identical_versions(self):
        old_m = {"packs": [{"pack_id": "a", "sha256": "123"}]}
        new_m = {"packs": [{"pack_id": "a", "sha256": "123"}]}

        plan = generate_update_plan(old_m, new_m)
        self.assertEqual(plan["unchanged"], ["a"])
        self.assertEqual(plan["updated"], [])
        self.assertEqual(plan["added"], [])
        self.assertEqual(plan["removed"], [])

    def test_update_plan_changed_bytes(self):
        old_m = {"packs": [{"pack_id": "a", "sha256": "123"}]}
        new_m = {"packs": [{"pack_id": "a", "sha256": "456"}]}

        plan = generate_update_plan(old_m, new_m)
        self.assertEqual(plan["unchanged"], [])
        self.assertEqual(plan["updated"], ["a"])
        self.assertEqual(plan["added"], [])
        self.assertEqual(plan["removed"], [])

    def test_update_plan_added_removed(self):
        old_m = {"packs": [{"pack_id": "a", "sha256": "123"}]}
        new_m = {"packs": [{"pack_id": "b", "sha256": "456"}]}

        plan = generate_update_plan(old_m, new_m)
        self.assertEqual(plan["unchanged"], [])
        self.assertEqual(plan["updated"], [])
        self.assertEqual(plan["added"], ["b"])
        self.assertEqual(plan["removed"], ["a"])

    def test_build_system_manifest(self):
        old_m = {
            "version": "1.0",
            "packs": [
                {"pack_id": "icon.vct", "sha256": "OLD_SHA"},
                {"pack_id": "removed.pack.gz", "sha256": "OLD_SHA"}
            ]
        }
        with open("test_data/old_manifest.json", "w") as f:
            json.dump(old_m, f)

        new_man, plan = build_system_manifest("test_data", "test_data/old_manifest.json")
        self.assertEqual(len(new_man["packs"]), 2)
        self.assertIn("xy_core.pack.gz", plan["added"])
        self.assertIn("icon.vct", plan["updated"])
        self.assertIn("removed.pack.gz", plan["removed"])

    def test_broken_dependencies(self):
        old_m = {"packs": []}
        new_m = {
            "packs": [
                {"pack_id": "a", "sha256": "1", "dependencies": ["missing"]},
                {"pack_id": "b", "sha256": "2"}
            ]
        }
        plan = generate_update_plan(old_m, new_m)
        self.assertIn("broken_dependencies", plan)
        self.assertIn("missing", plan["broken_dependencies"]["a"])

if __name__ == '__main__':
    unittest.main()
