import unittest
from registry import FontAsset, FontRightsRegistry

class TestFontRightsRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = FontRightsRegistry()

    def test_valid_licensing_metadata_only(self):
        asset = FontAsset(
            id="noto-sans-arab",
            family="Noto Sans Arabic",
            source="google_fonts",
            version="2.0",
            author="Google",
            license_id="OFL-1.1",
            scripts=["Arab"],
            embedded=False
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(result["issues"]), 0)

    def test_valid_licensing_embedded(self):
        asset = FontAsset(
            id="noto-sans-arab",
            family="Noto Sans Arabic",
            source="google_fonts",
            version="2.0",
            author="Google",
            license_id="OFL-1.1",
            scripts=["Arab"],
            embedded=True,
            sha256="d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2",
            license_text_included=True
        )
        result = self.registry.validate_asset(asset, expected_hash="d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2")
        self.assertEqual(result["status"], "accepted")

    def test_missing_notices_embedded(self):
        asset = FontAsset(
            id="noto-sans-arab",
            family="Noto Sans Arabic",
            source="google_fonts",
            version="2.0",
            author="Google",
            license_id="OFL-1.1",
            scripts=["Arab"],
            embedded=True,
            sha256="d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2",
            license_text_included=False
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Missing license notice for embedded asset", result["issues"])

    def test_changed_font_hashes(self):
        asset = FontAsset(
            id="noto-sans-arab",
            family="Noto Sans Arabic",
            source="google_fonts",
            version="2.0",
            author="Google",
            license_id="OFL-1.1",
            scripts=["Arab"],
            embedded=True,
            sha256="a2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2",
            license_text_included=True
        )
        result = self.registry.validate_asset(asset, expected_hash="d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2")
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Changed font hashes: actual hash does not match expected hash", result["issues"])

    def test_unknown_source(self):
        asset = FontAsset(
            id="custom-font",
            family="Custom Font",
            source="unknown_vendor",
            version="1.0",
            author="Someone",
            license_id="OFL-1.1",
            scripts=["Latn"]
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Unknown source: unknown_vendor", result["issues"])

    def test_mixed_families(self):
        asset = FontAsset(
            id="mixed-font",
            family="Arial, Times New Roman",
            source="google_fonts",
            version="1.0",
            author="Various",
            license_id="OFL-1.1",
            scripts=["Latn"]
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Mixed families are not allowed", result["issues"])

    def test_unrecognized_license_review_required(self):
        asset = FontAsset(
            id="custom-font",
            family="Custom Font",
            source="google_fonts",
            version="1.0",
            author="Various",
            license_id="Custom-License",
            scripts=["Latn"]
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("Unrecognized or blocked license: Custom-License", result["issues"])

    def test_noto_license_exception(self):
        asset = FontAsset(
            id="noto-sans",
            family="Noto Sans",
            source="google_fonts",
            version="1.0",
            author="Google",
            license_id="Apache-2.0",
            scripts=["Latn"]
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Noto-like fonts must be OFL-1.1 licensed", result["issues"])

    def test_overlapping_violations(self):
        asset = FontAsset(
            id="bad-font",
            family="Bad Font",
            source="unknown_source", # Rejected
            version="1.0",
            author="Someone",
            license_id="Unrecognized", # Normally reviewRequired
            scripts=["Latn"]
        )
        result = self.registry.validate_asset(asset)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Unknown source: unknown_source", result["issues"])
        self.assertIn("Unrecognized or blocked license: Unrecognized", result["issues"])

if __name__ == '__main__':
    unittest.main()
