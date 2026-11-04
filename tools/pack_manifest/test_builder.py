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
        self.assertIn("pack1", packs)
        self.assertIn("pack2", packs)
        self.assertIn("icon", packs)
        self.assertEqual(packs["pack1"]["dependencies"], ["pack2"])
        self.assertIn("payload_sha256", packs["pack1"])
        self.assertIn("language", packs["pack1"])

    def test_broken_dependencies(self):
        manifest_path = self.base_dir / "manifest.json"
        with self.assertRaisesRegex(ValueError, "Missing dependency: pack2 required by pack1"):
            build_manifest(self.base_dir, ["pack1.pack.gz", "icon.vct"], str(manifest_path))

    def test_missing_files_rejected(self):
        manifest_path = self.base_dir / "manifest.json"
        with self.assertRaises(FileNotFoundError):
            build_manifest(self.base_dir, ["nonexistent.pack.gz"], str(manifest_path))

    def test_generate_update_plan(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(old_manifest_path))

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
                "license": "CC-BY-SA-4.0",
                "dependencies": ["pack2"]
            }, f)

        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz", "pack3.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertEqual(plan['added'], ['pack3'])
        self.assertEqual(plan['updated'], ['pack1'])

    def test_removed_packs(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(old_manifest_path))

        pack3_path = self.base_dir / "pack3.pack.gz"
        with gzip.open(pack3_path, 'wt', encoding='utf-8') as f:
            import json
            json.dump({
                "lang_code": "en",
                "version": "1.0.0",
                "terms_count": 0,
                "license": "CC0-1.0"
            }, f)

        build_manifest(self.base_dir, ["pack3.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertIn('pack1', plan['removed'])
        self.assertIn('pack2', plan['removed'])
        self.assertEqual(plan['added'], ['pack3'])

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
        # We need pack2 because pack1 depends on it
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(old_manifest_path))
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertIn('pack1', plan['unchanged'])

    def test_unchanged_payload(self):
        old_manifest_path = self.base_dir / "old_manifest.json"
        new_manifest_path = self.base_dir / "new_manifest.json"
        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(old_manifest_path))

        # Change only version, payload unchanged
        with gzip.open(self.pack1_path, 'wt', encoding='utf-8') as f:
            json.dump({
                "lang_code": "af",
                "version": "1.0.1", # changed
                "terms_count": 2,
                "vocabulary": [1, 2],
                "license": "CC-BY-SA-4.0",
                "dependencies": ["pack2"]
            }, f)

        build_manifest(self.base_dir, ["pack1.pack.gz", "pack2.pack.gz"], str(new_manifest_path))
        plan = generate_update_plan(str(old_manifest_path), str(new_manifest_path))
        self.assertIn('pack1', plan['unchanged'])

    def test_small_compressed_bomb_exceeding_limit_is_rejected(self):
        from unittest.mock import patch
        from tools.pack_manifest.builder import bounded_json_parse
        path = self.base_dir / "bomb.pack.gz"
        with gzip.open(path, 'wb') as output:
            output.write(b'A' * 8192)
        # Low bound makes the memory attack deterministic and cheap in CI.
        with patch("tools.pack_manifest.builder.MAX_JSON_BYTES", 1024):
            with self.assertRaises(ValueError):
                bounded_json_parse(path)

    def test_invalid_or_oversized_vct_is_rejected(self):
        from tools.pack_manifest.builder import bounded_json_parse
        bad = self.base_dir / "invalid.vct"
        for payload in (b'invalid compressed data', zlib.compress(b'x' * 65537),
                        b'\x00' * 2050):
            with self.subTest(payload_bytes=len(payload)):
                bad.write_bytes(payload)
                with self.assertRaises(ValueError):
                    bounded_json_parse(bad)

    def test_colliding_pack_ids_abort_without_overwriting_manifest(self):
        other_dir = self.base_dir / "other"
        other_dir.mkdir()
        other = other_dir / "pack2.pack.gz"
        with gzip.open(other, 'wt', encoding='utf-8') as output:
            json.dump({"lang_code": "ar", "terms_count": 1,
                       "vocabulary": ["word"], "license": "CC0-1.0"}, output)
        target = self.base_dir / "manifest.json"
        build_manifest(self.base_dir, ["pack2.pack.gz"], str(target))
        original = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Duplicate pack identity'):
            build_manifest(self.base_dir, ["pack2.pack.gz", "other/pack2.pack.gz"],
                           str(target))
        self.assertEqual(target.read_bytes(), original)

    def test_preserve_manifest_on_failure(self):
        manifest_path = self.base_dir / "manifest.json"
        build_manifest(self.base_dir, ["pack2.pack.gz"], str(manifest_path)) # pack2 has no dependencies
        invalid_path = self.base_dir / "invalid.pack.gz"
        with open(invalid_path, 'w') as f:
            f.write("not gzip")
        with self.assertRaises(Exception):
            build_manifest(self.base_dir, ["invalid.pack.gz"], str(manifest_path))
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn("pack2", data["packs"])

if __name__ == '__main__':
    unittest.main()
