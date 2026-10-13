import unittest
import json
import gzip
import os
import shutil
import tempfile
from tools.pack_manifest.builder import ManifestBuilder, UpdatePlanGenerator, ManifestBuilderError

class TestPackManifest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.builder = ManifestBuilder(packs_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _create_pack(self, name, data):
        path = os.path.join(self.temp_dir, name)
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            json.dump(data, f)
        return path

    def test_generate_manifest_success(self):
        self._create_pack("en_universal_v1.pack.gz", {
            "header": {"code": "en", "license": "MIT", "terms_count": 2},
            "domains": [{"id": 1}, {"id": 2}]
        })
        self._create_pack("de_vocab_a1.pack.gz", {
            "lang_code": "de", "license": "CC0", "terms_count": 3, "items": [1,2,3]
        })

        manifest_path = os.path.join(self.temp_dir, "manifest.json")
        manifest = self.builder.generate_manifest(manifest_path)

        self.assertEqual(manifest["schemaVersion"], "2.0.0")
        self.assertIn("en_universal_v1.pack.gz", manifest["packs"])
        self.assertIn("de_vocab_a1.pack.gz", manifest["packs"])

        en_pack = manifest["packs"]["en_universal_v1.pack.gz"]
        self.assertEqual(en_pack["language"], "en")
        self.assertEqual(en_pack["entry_count"], 2)

        de_pack = manifest["packs"]["de_vocab_a1.pack.gz"]
        self.assertEqual(de_pack["language"], "de")
        self.assertEqual(de_pack["entry_count"], 3)
        self.assertEqual(de_pack["license"], "CC0")

    def test_mismatched_entry_count(self):
        self._create_pack("bad.pack.gz", {
            "header": {"code": "en", "license": "MIT", "terms_count": 5},
            "domains": [{"id": 1}, {"id": 2}] # only 2 domains
        })
        with self.assertRaises(ManifestBuilderError) as ctx:
            self.builder.generate_manifest(os.path.join(self.temp_dir, "manifest.json"))
        self.assertIn("Mismatched entry count", str(ctx.exception))

    def test_missing_artifact(self):
        with self.assertRaises(ManifestBuilderError) as ctx:
            self.builder.sha256_file(os.path.join(self.temp_dir, "does_not_exist.pack.gz"))
        self.assertIn("Missing artifact", str(ctx.exception))

    def test_path_traversal(self):
        with self.assertRaises(ManifestBuilderError) as ctx:
            self.builder._safe_path("/etc/passwd")
        self.assertIn("Path traversal detected", str(ctx.exception))

    def test_update_plan_generator(self):
        old_manifest = {
            "packs": {
                "unchanged.pack.gz": {"size_bytes": 100, "sha256": "123", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "updated.pack.gz": {"size_bytes": 100, "sha256": "456", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "removed.pack.gz": {"size_bytes": 100, "sha256": "789", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "metadata.pack.gz": {"size_bytes": 100, "sha256": "111", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []}
            }
        }

        new_manifest = {
            "packs": {
                "unchanged.pack.gz": {"size_bytes": 100, "sha256": "123", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "updated.pack.gz": {"size_bytes": 101, "sha256": "999", "entry_count": 12, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "added.pack.gz": {"size_bytes": 100, "sha256": "000", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []},
                "metadata.pack.gz": {"size_bytes": 100, "sha256": "111", "entry_count": 10, "language": "en", "schema_version": "2.0", "source_provenance": "src", "license": "GPL", "semantic_vector_assets": [], "dependencies": []}
            }
        }

        plan = UpdatePlanGenerator().compare_manifests(old_manifest, new_manifest)
        self.assertIn("unchanged.pack.gz", plan["unchanged"])
        self.assertIn("updated.pack.gz", plan["to_update"])
        self.assertIn("added.pack.gz", plan["to_add"])
        self.assertIn("removed.pack.gz", plan["to_remove"])
        self.assertIn("metadata.pack.gz", plan["metadata_only_changes"])

    def test_broken_dependencies(self):
        # A pack depending on an absent pack
        old = {
            "packs": {
                "core.pack.gz": {"size_bytes": 100, "sha256": "123", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": ["vocab.pack.gz"]}
            }
        }
        new = {
            "packs": {
                "core.pack.gz": {"size_bytes": 100, "sha256": "123", "entry_count": 10, "language": "en", "schema_version": "1.0", "source_provenance": "src", "license": "MIT", "semantic_vector_assets": [], "dependencies": []}
            }
        }
        plan = UpdatePlanGenerator().compare_manifests(old, new)
        self.assertIn("core.pack.gz", plan["metadata_only_changes"])

    def test_broken_dependency_generation(self):
        # A test to ensure we reject broken dependencies
        self._create_pack("core.pack.gz", {
            "lang_code": "en", "license": "MIT", "terms_count": 2, "items": [1, 2],
            "dependencies": ["missing.pack.gz"]
        })
        with self.assertRaises(ManifestBuilderError) as ctx:
            self.builder.generate_manifest(os.path.join(self.temp_dir, "manifest.json"))
        self.assertIn("Broken dependency", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
