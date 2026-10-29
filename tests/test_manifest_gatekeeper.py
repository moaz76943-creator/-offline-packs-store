import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.gha_factory.manifest_gatekeeper import validate_manifest_structure

class TestManifestGatekeeper(unittest.TestCase):
    def test_valid_manifest(self):
        manifest = {
            "version": "2.0.0",
            "packs": [
                {
                    "pack_id": "de_ar_a1",
                    "filename": "de_ar_a1.pack",
                    "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                    "size_bytes": 49152,
                    "license": "CC-BY-SA-4.0"
                }
            ]
        }
        valid, errors = validate_manifest_structure(manifest)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_invalid_license_and_hash(self):
        manifest = {
            "packs": [
                {
                    "pack_id": "bad_pack",
                    "filename": "bad.pack",
                    "sha256": "too_short_hash",
                    "size_bytes": 0,
                    "license": "UNAPPROVED_PROPRIETARY"
                }
            ]
        }
        valid, errors = validate_manifest_structure(manifest)
        self.assertFalse(valid)
        self.assertTrue(any("invalid SHA-256" in e for e in errors))
        self.assertTrue(any("unapproved license" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
