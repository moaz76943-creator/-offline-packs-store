import unittest
import os
import hashlib
from typing import List
from legal.font_assets.registry import FontAsset
from tools.glyph_coverage.validator import GlyphCoverageValidator, SCRIPT_SAMPLES, VARIATION_SELECTORS

def get_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

class TestGlyphCoverageValidator(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        self.validator = GlyphCoverageValidator(repo_root=self.repo_root)

        self.latin_font_path = "tools/glyph_coverage/fixtures/test_latin.ttf"
        self.arabic_font_path = "tools/glyph_coverage/fixtures/test_arabic.ttf"
        self.hebrew_font_path = "tools/glyph_coverage/fixtures/test_hebrew.ttf"
        self.deva_font_path = "tools/glyph_coverage/fixtures/test_deva.ttf"
        self.cjk_font_path = "tools/glyph_coverage/fixtures/test_cjk.ttf"
        self.thai_font_path = "tools/glyph_coverage/fixtures/test_thai.ttf"

        self.latin_hash = get_hash(os.path.join(self.repo_root, self.latin_font_path))
        self.arabic_hash = get_hash(os.path.join(self.repo_root, self.arabic_font_path))
        self.hebrew_hash = get_hash(os.path.join(self.repo_root, self.hebrew_font_path))
        self.deva_hash = get_hash(os.path.join(self.repo_root, self.deva_font_path))
        self.cjk_hash = get_hash(os.path.join(self.repo_root, self.cjk_font_path))
        self.thai_hash = get_hash(os.path.join(self.repo_root, self.thai_font_path))

        self.evidence_path = "tools/glyph_coverage/fixtures/dummy_evidence.txt"
        self.notice_path = "tools/glyph_coverage/fixtures/dummy_notice.txt"
        self.review_path = "tools/glyph_coverage/fixtures/dummy_review.txt"

        for p in [self.evidence_path, self.review_path]:
            with open(os.path.join(self.repo_root, p), "w") as f:
                f.write("Evidence")

        with open(os.path.join(self.repo_root, self.notice_path), "w") as f:
            f.write("SIL OPEN FONT LICENSE")

        self.evidence_hash = get_hash(os.path.join(self.repo_root, self.evidence_path))
        self.notice_hash = get_hash(os.path.join(self.repo_root, self.notice_path))
        self.review_hash = get_hash(os.path.join(self.repo_root, self.review_path))

        self.review = {
            "reviewer": "test",
            "decision_url": "https://example.com/decision"
        }

        self.build_asset = lambda id, family, scripts, path, fhash, embed=True, lic="OFL-1.1": FontAsset(
            id=id, family=family, source="Test", version="1.0", author="Test",
            license_id=lic, scripts=scripts, embedded=embed,
            sha256=fhash, license_text_included=True, asset_path=path,
            origin_url="https://example.com", license_evidence_url="https://example.com/license",
            license_evidence_path=self.evidence_path, license_evidence_sha256=self.evidence_hash,
            distribution_notice_path=self.notice_path, distribution_notice_sha256=self.notice_hash,
            review_evidence_path=self.review_path, review_evidence_sha256=self.review_hash,
            review=self.review
        )

    def tearDown(self):
        for p in [self.evidence_path, self.notice_path, self.review_path]:
            try:
                os.remove(os.path.join(self.repo_root, p))
            except FileNotFoundError:
                pass

    def test_extract_cmap(self):
        cmap = self.validator.get_font_cmap(os.path.join(self.repo_root, self.latin_font_path))
        self.assertIn(ord('a'), cmap)
        self.assertIn(ord('A'), cmap)
        self.assertIn(0x00E4, cmap)

    def test_validate_coverage_missing_glyphs(self):
        res = self.validator.validate_coverage("Latn", os.path.join(self.repo_root, self.arabic_font_path))
        self.assertEqual(len(res["supported"]), 2) # Variation selectors are supported in both dummy fonts
        self.assertEqual(len(res["unsupported"]), len(SCRIPT_SAMPLES["Latn"]))

    def test_generate_fallback_mapping_valid(self):
        asset = self.build_asset("f1", "LatinTest", ["Latn"], self.latin_font_path, self.latin_hash)

        mapping = self.validator.generate_fallback_mapping("Latn", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("LatinTest", mapping.valid_fallback_families)
        self.assertFalse(mapping.shaping_guaranteed)
        self.assertFalse(mapping.device_rendering_guaranteed)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_hebrew(self):
        asset = self.build_asset("f1", "HebrewTest", ["Hebr"], self.hebrew_font_path, self.hebrew_hash)

        mapping = self.validator.generate_fallback_mapping("Hebr", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("HebrewTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_deva(self):
        asset = self.build_asset("f1", "DevaTest", ["Deva"], self.deva_font_path, self.deva_hash)

        mapping = self.validator.generate_fallback_mapping("Deva", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("DevaTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_cjk(self):
        asset = self.build_asset("f1", "CJKTest", ["Hani"], self.cjk_font_path, self.cjk_hash)

        mapping = self.validator.generate_fallback_mapping("Hani", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("CJKTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_thai(self):
        asset = self.build_asset("f1", "ThaiTest", ["Thai"], self.thai_font_path, self.thai_hash)

        mapping = self.validator.generate_fallback_mapping("Thai", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("ThaiTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_rejected_not_embedded(self):
        asset = self.build_asset("f1", "LatinTest", ["Latn"], self.latin_font_path, self.latin_hash, embed=False)
        mapping = self.validator.generate_fallback_mapping("Latn", [asset])
        self.assertFalse(mapping.cmap_coverage)
        self.assertNotIn("LatinTest", mapping.valid_fallback_families)

    def test_generate_fallback_mapping_rejected_bad_license(self):
        asset = self.build_asset("f1", "LatinTest", ["Latn"], self.latin_font_path, self.latin_hash, lic="INVALID-LICENSE")
        mapping = self.validator.generate_fallback_mapping("Latn", [asset])
        self.assertFalse(mapping.cmap_coverage)
        self.assertNotIn("LatinTest", mapping.valid_fallback_families)

if __name__ == "__main__":
    unittest.main()
