import json
import os
import unittest
from tools.accessibility_pack_lint.validator import AccessibilityValidator

class TestAccessibilityValidator(unittest.TestCase):
    def setUp(self):
        self.validator = AccessibilityValidator()
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

    def load_fixture(self, filename: str) -> dict:
        with open(os.path.join(self.fixtures_dir, filename), "r", encoding="utf-8") as f:
            return json.load(f)

    def test_valid_asset(self):
        asset = self.load_fixture("valid_asset.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(result["errors"]), 0)

    def test_missing_alt_text(self):
        asset = self.load_fixture("missing_alt_text.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing or empty alt text", result["errors"])

    def test_unsupported_scripts(self):
        asset = self.load_fixture("unsupported_scripts.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing script metadata", result["errors"])

    def test_mismatched_concept(self):
        asset = self.load_fixture("mismatched_concept.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Mismatched concept ID", result["errors"])

    def test_bad_vector(self):
        asset = self.load_fixture("bad_vector.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing or structurally invalid vector metadata", result["errors"])

    def test_unverified_label(self):
        asset = self.load_fixture("valid_asset.json")
        asset["labels"][0]["verified"] = False
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "review_required")
        self.assertIn("REVIEW_REQUIRED", result["warnings"])

    def test_missing_shaping_evidence(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["device_shaping_evidence"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "accepted")
        self.assertIn("Missing device shaping evidence", result["warnings"])

if __name__ == "__main__":
    unittest.main()
