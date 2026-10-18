import unittest
import json
import gzip
import zlib
import os
import shutil
from pathlib import Path
import tempfile
from tools.pack_manifest.builder import build_manifest, generate_update_plan, ManifestError, _resolve_path

class TestManifestBuilder(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.test_dir)
        self.packs_dir = self.repo_root / "packs"
        self.packs_dir.mkdir()

        # Valid pack
        self.valid_pack_path = self.packs_dir / "valid.pack.gz"
        header = {"language": "en", "pack_id": "pack_en", "schema_version": "1.0", "lexical_count": 1, "dependencies": ["pack_vct"]}
        with gzip.open(self.valid_pack_path, "wt", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            f.write(json.dumps({"word": "hello"}) + "\n")

        # Valid vct
        self.valid_vct_path = self.packs_dir / "valid.vct"
        vct_meta = {"pack_id": "pack_vct", "version": "1.0", "source": "src", "license": "CC0"}
        self.valid_vct_path.write_bytes(zlib.compress(json.dumps(vct_meta).encode('utf-8')))

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_build_manifest_success(self):
        paths = ["packs/valid.pack.gz", "packs/valid.vct"]
        manifest = build_manifest(self.repo_root, paths)

        self.assertEqual(manifest["version"], "1.0.0")
        self.assertIn("packs/valid.pack.gz", manifest["entries"])
        self.assertIn("packs/valid.vct", manifest["entries"])

        pack_entry = manifest["entries"]["packs/valid.pack.gz"]
        self.assertEqual(pack_entry["language"], "en")
        self.assertEqual(pack_entry["entry_count"], 1)

    def test_missing_artifacts(self):
        paths = ["packs/missing.pack.gz"]
        with self.assertRaises(ManifestError) as context:
            build_manifest(self.repo_root, paths)
        self.assertIn("Missing artifact", str(context.exception))

    def test_mismatched_entry_count(self):
        path = self.packs_dir / "mismatch.pack.gz"
        header = {"language": "en", "pack_id": "pack_mismatch", "schema_version": "1.0", "lexical_count": 2} # Expects 2, we give 1
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            f.write(json.dumps({"word": "hello"}) + "\n")

        with self.assertRaises(ManifestError) as context:
            build_manifest(self.repo_root, ["packs/mismatch.pack.gz"])
        self.assertIn("Mismatched entry counts", str(context.exception))

    def test_untrusted_paths(self):
        with self.assertRaises(ManifestError):
            _resolve_path(self.repo_root, "../outside.pack.gz")
        with self.assertRaises(ManifestError):
            _resolve_path(self.repo_root, "/etc/passwd")

    def test_broken_dependencies(self):
        paths = ["packs/valid.pack.gz"] # Depends on "pack_vct" but it's not provided in file_paths
        with self.assertRaises(ManifestError) as context:
            build_manifest(self.repo_root, paths)
        self.assertIn("Broken dependency", str(context.exception))

    def test_generate_update_plan(self):
        old_manifest = {
            "entries": {
                "packs/unchanged.pack.gz": {"sha256": "hash_u", "payload_sha256": "payload_u"},
                "packs/changed.pack.gz": {"sha256": "hash_c1", "payload_sha256": "payload_c1"},
                "packs/removed.pack.gz": {"sha256": "hash_r", "payload_sha256": "payload_r"}
            }
        }
        new_manifest = {
            "entries": {
                "packs/unchanged.pack.gz": {"sha256": "hash_u", "payload_sha256": "payload_u"}, # Same payload
                "packs/changed.pack.gz": {"sha256": "hash_c2", "payload_sha256": "payload_c2"}, # Payload delta
                "packs/added.pack.gz": {"sha256": "hash_a", "payload_sha256": "payload_a"}
            }
        }

        plan = generate_update_plan(old_manifest, new_manifest)
        self.assertIn("packs/unchanged.pack.gz", plan["unchanged"])
        self.assertIn("packs/changed.pack.gz", plan["changed"])
        self.assertIn("packs/removed.pack.gz", plan["removed"])
        self.assertIn("packs/added.pack.gz", plan["added"])

if __name__ == '__main__':
    unittest.main()
