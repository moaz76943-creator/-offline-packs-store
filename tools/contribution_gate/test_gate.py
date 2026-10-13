import hashlib
import tempfile
import unittest
import os
from pathlib import Path

from tools.contribution_gate.gate import validate_contribution, sha256_file

class TestGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

        # Create a dummy asset file
        self.asset_path_str = "dummy_asset.txt"
        self.full_asset_path = self.repo_root / self.asset_path_str
        self.full_asset_path.write_bytes(b"dummy content")
        self.asset_hash = sha256_file(str(self.full_asset_path))

        self.valid_manifest = {
            "artifact_path": self.asset_path_str,
            "sha256": self.asset_hash,
            "kind": "lexical",
            "source_identity": "test_user",
            "contributor_authorization": "https://example.com/auth",
            "license_id": "CC-BY-SA-4.0",
            "attribution_notices": {"test_user": "By test_user"},
            "lexical_provenance": "recorded by test_user",
            "version": "1.0"
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_submission(self):
        result = validate_contribution(self.valid_manifest, str(self.repo_root))
        self.assertEqual(result["status"], "ACCEPT")
        self.assertIn("receipt", result)
        self.assertEqual(result["receipt"]["asset_hash"], self.asset_hash)

    def test_false_cc0_declaration(self):
        manifest = self.valid_manifest.copy()
        manifest["license_id"] = "CC0-1.0"
        # No evidence
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("False CC0 declaration" in r for r in result["reasons"]))

        # Invalid evidence
        manifest["license_evidence"] = "I made this"
        result2 = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result2["status"], "REJECT")

        # Valid evidence
        manifest["license_evidence"] = "I dedicate this to the public domain via CC0"
        result3 = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result3["status"], "ACCEPT")

    def test_incomplete_attribution(self):
        manifest = self.valid_manifest.copy()
        del manifest["attribution_notices"]
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Incomplete attribution" in r for r in result["reasons"]))

    def test_changed_hashes(self):
        manifest = self.valid_manifest.copy()
        manifest["sha256"] = "badhash"
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Hash mismatch" in r for r in result["reasons"]))

    def test_conflicting_obligations(self):
        # Already tested incomplete attribution above, let's test missing artwork provenance
        manifest = self.valid_manifest.copy()
        manifest["kind"] = "artwork"
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Missing artwork provenance" in r for r in result["reasons"]))

        manifest["artwork_provenance"] = "drawn by test_user"
        result2 = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result2["status"], "ACCEPT")

    def test_unverified_third_party(self):
        manifest = self.valid_manifest.copy()
        manifest["source_verification"] = "unverified_third_party"
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("unverified third party" in r for r in result["reasons"]))

    def test_missing_authorization(self):
        manifest = self.valid_manifest.copy()
        del manifest["contributor_authorization"]
        result = validate_contribution(manifest, str(self.repo_root))
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue(any("Missing explicit contributor authorization evidence" in r for r in result["reasons"]))

if __name__ == '__main__':
    unittest.main()
