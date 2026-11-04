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
        self.cyrillic_font_path = "tools/glyph_coverage/fixtures/test_cyrillic.ttf"
        self.greek_font_path = "tools/glyph_coverage/fixtures/test_greek.ttf"
        self.armenian_font_path = "tools/glyph_coverage/fixtures/test_armenian.ttf"
        self.negative_font_path = "tools/glyph_coverage/fixtures/test_negative.ttf"
        self.geor_font_path = "tools/glyph_coverage/fixtures/test_geor.ttf"
        self.beng_font_path = "tools/glyph_coverage/fixtures/test_beng.ttf"
        self.guru_font_path = "tools/glyph_coverage/fixtures/test_guru.ttf"
        self.gujr_font_path = "tools/glyph_coverage/fixtures/test_gujr.ttf"
        self.taml_font_path = "tools/glyph_coverage/fixtures/test_taml.ttf"
        self.telu_font_path = "tools/glyph_coverage/fixtures/test_telu.ttf"
        self.knda_font_path = "tools/glyph_coverage/fixtures/test_knda.ttf"
        self.mlym_font_path = "tools/glyph_coverage/fixtures/test_mlym.ttf"
        self.orya_font_path = "tools/glyph_coverage/fixtures/test_orya.ttf"
        self.sinh_font_path = "tools/glyph_coverage/fixtures/test_sinh.ttf"
        self.laoo_font_path = "tools/glyph_coverage/fixtures/test_laoo.ttf"
        self.khmr_font_path = "tools/glyph_coverage/fixtures/test_khmr.ttf"
        self.mymr_font_path = "tools/glyph_coverage/fixtures/test_mymr.ttf"
        self.ethi_font_path = "tools/glyph_coverage/fixtures/test_ethi.ttf"
        self.mong_font_path = "tools/glyph_coverage/fixtures/test_mong.ttf"
        self.thaa_font_path = "tools/glyph_coverage/fixtures/test_thaa.ttf"
        self.nkoo_font_path = "tools/glyph_coverage/fixtures/test_nkoo.ttf"
        self.adlm_font_path = "tools/glyph_coverage/fixtures/test_adlm.ttf"
        self.syrc_font_path = "tools/glyph_coverage/fixtures/test_syrc.ttf"
        self.jpan_font_path = "tools/glyph_coverage/fixtures/test_jpan.ttf"
        self.kore_font_path = "tools/glyph_coverage/fixtures/test_kore.ttf"

        self.latin_hash = get_hash(os.path.join(self.repo_root, self.latin_font_path))
        self.arabic_hash = get_hash(os.path.join(self.repo_root, self.arabic_font_path))
        self.hebrew_hash = get_hash(os.path.join(self.repo_root, self.hebrew_font_path))
        self.deva_hash = get_hash(os.path.join(self.repo_root, self.deva_font_path))
        self.cjk_hash = get_hash(os.path.join(self.repo_root, self.cjk_font_path))
        self.thai_hash = get_hash(os.path.join(self.repo_root, self.thai_font_path))
        self.cyrillic_hash = get_hash(os.path.join(self.repo_root, self.cyrillic_font_path))
        self.greek_hash = get_hash(os.path.join(self.repo_root, self.greek_font_path))
        self.armenian_hash = get_hash(os.path.join(self.repo_root, self.armenian_font_path))
        self.negative_hash = get_hash(os.path.join(self.repo_root, self.negative_font_path))
        self.geor_hash = get_hash(os.path.join(self.repo_root, self.geor_font_path))
        self.beng_hash = get_hash(os.path.join(self.repo_root, self.beng_font_path))
        self.guru_hash = get_hash(os.path.join(self.repo_root, self.guru_font_path))
        self.gujr_hash = get_hash(os.path.join(self.repo_root, self.gujr_font_path))
        self.taml_hash = get_hash(os.path.join(self.repo_root, self.taml_font_path))
        self.telu_hash = get_hash(os.path.join(self.repo_root, self.telu_font_path))
        self.knda_hash = get_hash(os.path.join(self.repo_root, self.knda_font_path))
        self.mlym_hash = get_hash(os.path.join(self.repo_root, self.mlym_font_path))
        self.orya_hash = get_hash(os.path.join(self.repo_root, self.orya_font_path))
        self.sinh_hash = get_hash(os.path.join(self.repo_root, self.sinh_font_path))
        self.laoo_hash = get_hash(os.path.join(self.repo_root, self.laoo_font_path))
        self.khmr_hash = get_hash(os.path.join(self.repo_root, self.khmr_font_path))
        self.mymr_hash = get_hash(os.path.join(self.repo_root, self.mymr_font_path))
        self.ethi_hash = get_hash(os.path.join(self.repo_root, self.ethi_font_path))
        self.mong_hash = get_hash(os.path.join(self.repo_root, self.mong_font_path))
        self.thaa_hash = get_hash(os.path.join(self.repo_root, self.thaa_font_path))
        self.nkoo_hash = get_hash(os.path.join(self.repo_root, self.nkoo_font_path))
        self.adlm_hash = get_hash(os.path.join(self.repo_root, self.adlm_font_path))
        self.syrc_hash = get_hash(os.path.join(self.repo_root, self.syrc_font_path))
        self.jpan_hash = get_hash(os.path.join(self.repo_root, self.jpan_font_path))
        self.kore_hash = get_hash(os.path.join(self.repo_root, self.kore_font_path))

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

    def test_validate_coverage_negative_fixture(self):
        # Explicit negative fixture missing all core glyphs
        res = self.validator.validate_coverage("Latn", os.path.join(self.repo_root, self.negative_font_path))
        self.assertEqual(len(res["supported"]), 2) # Variation selectors only
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

    def test_generate_fallback_mapping_valid_cyrillic(self):
        asset = self.build_asset("f1", "CyrillicTest", ["Cyrl"], self.cyrillic_font_path, self.cyrillic_hash)

        mapping = self.validator.generate_fallback_mapping("Cyrl", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("CyrillicTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_greek(self):
        asset = self.build_asset("f1", "GreekTest", ["Grek"], self.greek_font_path, self.greek_hash)

        mapping = self.validator.generate_fallback_mapping("Grek", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("GreekTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_armenian(self):
        asset = self.build_asset("f1", "ArmenianTest", ["Armn"], self.armenian_font_path, self.armenian_hash)

        mapping = self.validator.generate_fallback_mapping("Armn", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("ArmenianTest", mapping.valid_fallback_families)
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


    def test_generate_fallback_mapping_valid_geor(self):
        asset = self.build_asset("f1", "GeorTest", ["Geor"], self.geor_font_path, self.geor_hash)

        mapping = self.validator.generate_fallback_mapping("Geor", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("GeorTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_beng(self):
        asset = self.build_asset("f1", "BengTest", ["Beng"], self.beng_font_path, self.beng_hash)

        mapping = self.validator.generate_fallback_mapping("Beng", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("BengTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_guru(self):
        asset = self.build_asset("f1", "GuruTest", ["Guru"], self.guru_font_path, self.guru_hash)

        mapping = self.validator.generate_fallback_mapping("Guru", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("GuruTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_gujr(self):
        asset = self.build_asset("f1", "GujrTest", ["Gujr"], self.gujr_font_path, self.gujr_hash)

        mapping = self.validator.generate_fallback_mapping("Gujr", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("GujrTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_taml(self):
        asset = self.build_asset("f1", "TamlTest", ["Taml"], self.taml_font_path, self.taml_hash)

        mapping = self.validator.generate_fallback_mapping("Taml", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("TamlTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_telu(self):
        asset = self.build_asset("f1", "TeluTest", ["Telu"], self.telu_font_path, self.telu_hash)

        mapping = self.validator.generate_fallback_mapping("Telu", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("TeluTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_knda(self):
        asset = self.build_asset("f1", "KndaTest", ["Knda"], self.knda_font_path, self.knda_hash)

        mapping = self.validator.generate_fallback_mapping("Knda", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("KndaTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_mlym(self):
        asset = self.build_asset("f1", "MlymTest", ["Mlym"], self.mlym_font_path, self.mlym_hash)

        mapping = self.validator.generate_fallback_mapping("Mlym", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("MlymTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_orya(self):
        asset = self.build_asset("f1", "OryaTest", ["Orya"], self.orya_font_path, self.orya_hash)

        mapping = self.validator.generate_fallback_mapping("Orya", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("OryaTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_sinh(self):
        asset = self.build_asset("f1", "SinhTest", ["Sinh"], self.sinh_font_path, self.sinh_hash)

        mapping = self.validator.generate_fallback_mapping("Sinh", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("SinhTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_laoo(self):
        asset = self.build_asset("f1", "LaooTest", ["Laoo"], self.laoo_font_path, self.laoo_hash)

        mapping = self.validator.generate_fallback_mapping("Laoo", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("LaooTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_khmr(self):
        asset = self.build_asset("f1", "KhmrTest", ["Khmr"], self.khmr_font_path, self.khmr_hash)

        mapping = self.validator.generate_fallback_mapping("Khmr", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("KhmrTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_mymr(self):
        asset = self.build_asset("f1", "MymrTest", ["Mymr"], self.mymr_font_path, self.mymr_hash)

        mapping = self.validator.generate_fallback_mapping("Mymr", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("MymrTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_ethi(self):
        asset = self.build_asset("f1", "EthiTest", ["Ethi"], self.ethi_font_path, self.ethi_hash)

        mapping = self.validator.generate_fallback_mapping("Ethi", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("EthiTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_mong(self):
        asset = self.build_asset("f1", "MongTest", ["Mong"], self.mong_font_path, self.mong_hash)

        mapping = self.validator.generate_fallback_mapping("Mong", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("MongTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_thaa(self):
        asset = self.build_asset("f1", "ThaaTest", ["Thaa"], self.thaa_font_path, self.thaa_hash)

        mapping = self.validator.generate_fallback_mapping("Thaa", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("ThaaTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_nkoo(self):
        asset = self.build_asset("f1", "NkooTest", ["Nkoo"], self.nkoo_font_path, self.nkoo_hash)

        mapping = self.validator.generate_fallback_mapping("Nkoo", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("NkooTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_adlm(self):
        asset = self.build_asset("f1", "AdlmTest", ["Adlm"], self.adlm_font_path, self.adlm_hash)

        mapping = self.validator.generate_fallback_mapping("Adlm", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("AdlmTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_syrc(self):
        asset = self.build_asset("f1", "SyrcTest", ["Syrc"], self.syrc_font_path, self.syrc_hash)

        mapping = self.validator.generate_fallback_mapping("Syrc", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("SyrcTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_jpan(self):
        asset = self.build_asset("f1", "JpanTest", ["Jpan"], self.jpan_font_path, self.jpan_hash)

        mapping = self.validator.generate_fallback_mapping("Jpan", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("JpanTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

    def test_generate_fallback_mapping_valid_kore(self):
        asset = self.build_asset("f1", "KoreTest", ["Kore"], self.kore_font_path, self.kore_hash)

        mapping = self.validator.generate_fallback_mapping("Kore", [asset])
        self.assertTrue(mapping.cmap_coverage)
        self.assertIn("KoreTest", mapping.valid_fallback_families)
        self.assertEqual(len(mapping.unsupported_points), 0)

if __name__ == "__main__":
    unittest.main()
