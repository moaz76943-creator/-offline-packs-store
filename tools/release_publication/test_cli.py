import unittest
import tempfile
import json
import hashlib
from pathlib import Path
import os
import tarfile

from cli import run_pipeline

class TestReleasePublication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.packs_dir = self.root / "packs"
        self.packs_dir.mkdir()

        self.manifest_path = self.root / "manifest.json"
        self.output_path = self.root / "release.tar.gz"

        # Create dummy pack
        self.pack_content = b"dummy pack content"
        self.pack_file = "test_v1.pack.gz"
        self.pack_path = self.packs_dir / self.pack_file
        self.pack_path.write_bytes(self.pack_content)

        self.pack_sha256 = hashlib.sha256(self.pack_content).hexdigest()

        # Create dummy manifest
        self.valid_manifest = {
            "intellectual_property_status": "PUBLIC_DOMAIN_ZERO_COPYRIGHT",
            "languages": [
                {
                    "code": "test",
                    "pack_file": self.pack_file,
                    "sha256": self.pack_sha256,
                    "format": "legacy-json-gzip"
                }
            ]
        }
        self.write_manifest(self.valid_manifest)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_manifest(self, data):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_successful_archive_creation(self):
        run_pipeline(self.manifest_path, self.packs_dir, self.output_path)
        self.assertTrue(self.output_path.exists())

        # Test deterministic output by running again and checking hashes
        output_path_2 = self.root / "release2.tar.gz"
        run_pipeline(self.manifest_path, self.packs_dir, output_path_2)

        sha_1 = hashlib.sha256(self.output_path.read_bytes()).hexdigest()
        sha_2 = hashlib.sha256(output_path_2.read_bytes()).hexdigest()
        self.assertEqual(sha_1, sha_2)

        with tarfile.open(self.output_path, "r:gz") as tar:
            members = tar.getnames()
            self.assertIn("manifest.json", members)
            self.assertIn(f"packs/{self.pack_file}", members)

            # Check attribution
            manifest_file = tar.extractfile("manifest.json")
            archived_manifest = json.load(manifest_file)
            self.assertEqual(archived_manifest["attribution"], "Open-content catalog semantic asset package. Verified public release.")

    def test_dry_run(self):
        run_pipeline(self.manifest_path, self.packs_dir, self.output_path, dry_run=True)
        self.assertFalse(self.output_path.exists())

    def test_invalid_license_status(self):
        invalid_manifest = self.valid_manifest.copy()
        invalid_manifest["intellectual_property_status"] = "PROPRIETARY"
        self.write_manifest(invalid_manifest)
        with self.assertRaisesRegex(ValueError, "PUBLIC_DOMAIN_ZERO_COPYRIGHT"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path)

    def test_hash_mismatch(self):
        invalid_manifest = self.valid_manifest.copy()
        invalid_manifest["languages"][0]["sha256"] = "invalid_hash"
        self.write_manifest(invalid_manifest)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path)

    def test_missing_pack_file(self):
        self.pack_path.unlink()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path)

    def test_unsupported_format(self):
        invalid_manifest = self.valid_manifest.copy()
        invalid_manifest["languages"][0]["format"] = "unsupported_format"
        self.write_manifest(invalid_manifest)
        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path)

    def test_unauthorized_publication(self):
        with self.assertRaisesRegex(ValueError, "Credentials required"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path, publish=True, credentials=None)
        with self.assertRaisesRegex(ValueError, "Credentials required"):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path, publish=True, credentials="")

    def test_existing_approved_packages_remain_unchanged_on_failure(self):
        # Create a dummy existing archive
        self.output_path.write_bytes(b"existing archive content")

        # Cause a failure
        invalid_manifest = self.valid_manifest.copy()
        invalid_manifest["intellectual_property_status"] = "PROPRIETARY"
        self.write_manifest(invalid_manifest)

        with self.assertRaises(ValueError):
            run_pipeline(self.manifest_path, self.packs_dir, self.output_path)

        self.assertEqual(self.output_path.read_bytes(), b"existing archive content")
