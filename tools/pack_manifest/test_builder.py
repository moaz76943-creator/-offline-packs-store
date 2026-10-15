import unittest
import os
import json
import gzip
import tempfile
import shutil
from pathlib import Path

from tools.pack_manifest.builder import (
    secure_resolve_path,
    compute_sha256,
    count_entries,
    build_manifest,
    generate_update_plan
)

class TestPackManifestBuilder(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_secure_resolve_path(self):
        base_dir = os.path.join(self.test_dir, "base")
        os.makedirs(base_dir)

        valid = "pack.gz"
        with open(os.path.join(base_dir, valid), 'w') as f:
            f.write("content")

        resolved = secure_resolve_path(base_dir, valid)
        self.assertTrue(str(resolved).startswith(str(Path(base_dir).resolve())))

        with self.assertRaises(ValueError):
            secure_resolve_path(base_dir, "../escaped.gz")

        with self.assertRaises(ValueError):
            secure_resolve_path(base_dir, "/etc/passwd")

    def test_count_entries_pack_gz(self):
        filepath = os.path.join(self.test_dir, "test.pack.gz")
        data = {"terms_count": 42}
        with gzip.open(filepath, 'wt', encoding='utf-8') as f:
            json.dump(data, f)

        self.assertEqual(count_entries(filepath), 42)

    def test_count_entries_json_vocab(self):
        filepath = os.path.join(self.test_dir, "test.json")
        data = {"vocabulary": [1, 2, 3]}
        with open(filepath, 'wt', encoding='utf-8') as f:
            json.dump(data, f)

        self.assertEqual(count_entries(filepath), 3)

    def test_count_entries_json_list(self):
        filepath = os.path.join(self.test_dir, "test.json")
        data = [1, 2, 3, 4]
        with open(filepath, 'wt', encoding='utf-8') as f:
            json.dump(data, f)

        self.assertEqual(count_entries(filepath), 4)

    def test_build_manifest_success(self):
        base_dir = os.path.join(self.test_dir, "base")
        os.makedirs(base_dir)

        # Create dummy pack
        pack_path = "en_core.pack.gz"
        full_pack_path = os.path.join(base_dir, pack_path)
        with gzip.open(full_pack_path, 'wt', encoding='utf-8') as f:
            json.dump({"terms_count": 10}, f)

        # Create dummy dependency
        dep_path = "vector1.vct"
        full_dep_path = os.path.join(base_dir, dep_path)
        with open(full_dep_path, 'w') as f:
            f.write("vector data")

        records = [
            {
                "path": pack_path,
                "language": "en",
                "pack_id": "en_core",
                "schema_version": "2.0.0",
                "source_id": "src1",
                "license_id": "CC0",
                "dependencies": ["vector1.vct"]
            }
        ]

        out_path = os.path.join(self.test_dir, "manifest.json")
        build_manifest(base_dir, records, out_path)

        self.assertTrue(os.path.exists(out_path))
        with open(out_path, 'r') as f:
            manifest = json.load(f)

        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(len(manifest["packs"]), 1)
        self.assertEqual(manifest["packs"][0]["entry_count"], 10)
        self.assertEqual(manifest["packs"][0]["dependencies"], ["vector1.vct"])

    def test_build_manifest_failures(self):
        base_dir = os.path.join(self.test_dir, "base")
        os.makedirs(base_dir)

        pack_path = "en_core.pack.gz"
        full_pack_path = os.path.join(base_dir, pack_path)
        with gzip.open(full_pack_path, 'wt', encoding='utf-8') as f:
            json.dump({"terms_count": 10}, f)

        out_path = os.path.join(self.test_dir, "manifest.json")

        # Missing file
        with self.assertRaises(FileNotFoundError):
            build_manifest(base_dir, [{"path": "missing.pack.gz"}], out_path)

        # Missing provenance
        with self.assertRaises(ValueError) as ctx:
            build_manifest(base_dir, [{"path": pack_path, "language": "en"}], out_path)
        self.assertIn("missing source_id", str(ctx.exception))

        # Mismatched entry count
        bad_count_record = {
            "path": pack_path, "language": "en", "pack_id": "en_core",
            "schema_version": "2.0.0", "source_id": "src1", "license_id": "CC0",
            "entry_count": 99 # wrong
        }
        with self.assertRaises(ValueError) as ctx:
            build_manifest(base_dir, [bad_count_record], out_path)
        self.assertIn("Mismatched entry count", str(ctx.exception))

        # Broken dependency
        broken_dep_record = {
            "path": pack_path, "language": "en", "pack_id": "en_core",
            "schema_version": "2.0.0", "source_id": "src1", "license_id": "CC0",
            "dependencies": ["missing_vector.vct"]
        }
        with self.assertRaises(FileNotFoundError) as ctx:
            build_manifest(base_dir, [broken_dep_record], out_path)
        self.assertIn("Broken dependency", str(ctx.exception))


    def test_generate_update_plan(self):
        old_manifest = {
            "packs": [
                {"path": "unchanged.pack.gz", "sha256": "hash1", "size_bytes": 100},
                {"path": "updated.pack.gz", "sha256": "hash2", "size_bytes": 200},
                {"path": "meta_only.pack.gz", "sha256": "hash3", "size_bytes": 300, "source_id": "src1"},
                {"path": "removed.pack.gz", "sha256": "hash4", "size_bytes": 400}
            ]
        }

        new_manifest = {
            "packs": [
                {"path": "unchanged.pack.gz", "sha256": "hash1", "size_bytes": 100},
                {"path": "updated.pack.gz", "sha256": "hash2_new", "size_bytes": 200},
                # Meta changed, payload same
                {"path": "meta_only.pack.gz", "sha256": "hash3", "size_bytes": 300, "source_id": "src2"},
                {"path": "added.pack.gz", "sha256": "hash5", "size_bytes": 500}
            ]
        }

        plan = generate_update_plan(old_manifest, new_manifest)

        self.assertIn("unchanged.pack.gz", plan["unchanged"])
        self.assertIn("meta_only.pack.gz", plan["unchanged"]) # Payload hash identical -> skipped

        self.assertIn("updated.pack.gz", plan["updated"])
        self.assertIn("added.pack.gz", plan["added"])
        self.assertIn("removed.pack.gz", plan["removed"])

if __name__ == '__main__':
    unittest.main()
