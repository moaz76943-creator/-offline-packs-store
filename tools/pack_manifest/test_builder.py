import gzip
import json
import os
import shutil
import tempfile
import unittest
import zlib
from pathlib import Path

from tools.pack_manifest.builder import (
    build_manifest,
    compute_sha256,
    generate_update_plan,
    secure_resolve_path,
)

class TestPackManifestBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.temp_dir)

        self.pack1_path = self.base_dir / "pack1.pack.gz"
        with gzip.open(self.pack1_path, 'wt', encoding='utf-8') as f:
            json.dump({
                "lang_code": "af",
                "version": "1.0.0",
                "terms_count": 2,
                "vocabulary": [1, 2],
                "license": "CC-BY-SA-4.0",
                "dependencies": ["pack2"]
            }, f)

        self.pack2_path = self.base_dir / "pack2.pack.gz"
        with gzip.open(self.pack2_path, 'wt', encoding='utf-8') as f:
            json.dump({
                "header": {
                    "code": "ar",
                    "license": "CC0-1.0"
                },
                "version": "2.0.0",
                "domains": [1, 2, 3]
            }, f)

        self.vct_path = self.base_dir / "icon.vct"
        with open(self.vct_path, 'wb') as f:
            data = json.dumps({"asset_id": "test_icon", "version": "1.1.0", "license": "CC0-1.0"}).encode('utf-8')
            f.write(zlib.compress(data))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_secure_resolve_path(self):
        target = secure_resolve_path(self.base_dir, "pack1.pack.gz")
        self.assertEqual(target, self.pack1_path.resolve())
        with self.assertRaises(ValueError):
            secure_resolve_path(self.base_dir, "../outside.pack.gz")

    def test_compute_sha256(self):
        h = compute_sha256(self.pack1_path)
        self.assertEqual(len(h), 64)

    def test_build_manifest(self):
        manifest_path = self.base_dir / "manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz", "icon.vct"], str(manifest_path))
        self.assertTrue(manifest_path.exists())
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data["schema_version"], "1.0.0")
        packs = data["packs"]
        self.assertIn("af", packs)
        self.assertEqual(packs["af"]["dependencies"], ["pack2"])

    def test_missing_files_rejected(self):
        manifest_path = self.base_dir / "manifest.json"
        with self.assertRaises(FileNotFoundError):
            build_manifest(self.base_dir, ["nonexistent.pack.gz"], str(manifest_path))

    def test_generate_update_plan(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz"], str(old_manifest_path))

        pack3_path = self.base_dir / "pack3.pack.gz"
        with gzip.open(pack3_path, 'wt', encoding='utf-8') as f:
            json.dump({
                "lang_code": "en",
                "version": "1.0.0",
                "terms_count": 0,
                "license": "CC0-1.0"
            }, f)

        with gzip.open(self.pack1_path, 'wt', encoding='utf-8') as f:
            json.dump({
                "lang_code": "af",
                "version": "1.0.1",
                "terms_count": 2,
                "vocabulary": [1, 3], # changed
                "license": "CC-BY-SA-4.0"
            }, f)

        build_manifest(self.base_dir, ["pack1.pack.gz", "pack3.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertEqual(plan['added'], ['en'])
        self.assertEqual(plan['updated'], ['af'])

    def test_removed_packs(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(old_manifest_path))
        build_manifest(self.base_dir, ["pack1.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertEqual(plan['removed'], ['ar'])

    def test_mismatched_entry_count(self):
        bad_pack = self.base_dir / "bad.pack.gz"
        with gzip.open(bad_pack, 'wt', encoding='utf-8') as f:
            json.dump({
                "lang_code": "bad",
                "version": "1.0.0",
                "terms_count": 5,
                "vocabulary": [1], # mismatch!
                "license": "CC0-1.0"
            }, f)
        manifest_path = self.base_dir / "manifest.json"
        with self.assertRaises(ValueError):
            build_manifest(self.base_dir, ["bad.pack.gz"], str(manifest_path))

    def test_unchanged_packs(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz"], str(old_manifest_path))
        build_manifest(self.base_dir, ["pack1.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertEqual(plan['unchanged'], ['af'])

    def test_preserve_manifest_on_failure(self):
        manifest_path = self.base_dir / "manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz"], str(manifest_path))
        invalid_path = self.base_dir / "invalid.pack.gz"
        with open(invalid_path, 'w') as f:
            f.write("not gzip")
        with self.assertRaises(Exception):
            build_manifest(self.base_dir, ["invalid.pack.gz"], str(manifest_path))
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn("af", data["packs"])

if __name__ == '__main__':
    unittest.main()
