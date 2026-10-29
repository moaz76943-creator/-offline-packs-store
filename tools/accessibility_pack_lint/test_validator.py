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
        self.assertIn("Unsupported script 'UnsupportedScript'", result["errors"])

    def test_unsupported_language(self):
        asset = self.load_fixture("unsupported_language.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Unsupported language 'UnsupportedLanguage'", result["errors"])

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

    def test_empty_labels(self):
        asset = self.load_fixture("valid_asset.json")
        asset["labels"] = []
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing or empty alt text", result["errors"])

    def test_missing_concept_id(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["concept_id"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing semantic concept ID", result["errors"])

    def test_missing_fallback_label(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["fallback_label"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing fallback label", result["errors"])

    def test_missing_language(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["labels"][0]["language"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing language metadata", result["errors"])

    def test_control_character_in_alt_text(self):
        asset = self.load_fixture("valid_asset.json")
        asset["labels"][0]["text"] = "Text with \x00 control char"
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Alt text contains control characters", result["errors"])

    def test_missing_contrast_metadata(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["contrast"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing or structurally invalid contrast metadata", result["errors"])

    def test_missing_vector_bounds(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["vector"]["bounds"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Vector bounds missing or invalid", result["errors"])

    def test_missing_vector_complexity(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["vector"]["complexity"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Vector complexity missing", result["errors"])

    def test_nonnumeric_path_count_is_rejected(self):
        asset = self.load_fixture("valid_asset.json")
        asset["vector"]["path_count"] = "51"
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Vector path count must be a nonnegative integer", result["errors"])

    def test_vector_path_count_exceeded(self):
        asset = self.load_fixture("bad_vector_path_count.json")
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Vector path count exceeds safe complexity limits (max 50)", result["errors"])

    def test_missing_version(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["version"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing version identity", result["errors"])

    def test_missing_hash(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["hash"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing hash identity", result["errors"])

    def test_missing_provenance(self):
        asset = self.load_fixture("valid_asset.json")
        del asset["provenance"]
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing provenance identity", result["errors"])

    def test_malformed_direction(self):
        asset = self.load_fixture("valid_asset.json")
        asset["labels"][0]["direction"] = "invalid"
        result = self.validator.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Malformed RTL/LTR direction metadata", result["errors"])

if __name__ == "__main__":
    unittest.main()
