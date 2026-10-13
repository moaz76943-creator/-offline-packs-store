import unittest
import os
import json
import tempfile
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from tools.glyph_coverage.validator import GlyphCoverageValidator

class TestGlyphCoverageValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = os.path.join(self.temp_dir.name, "test_registry.json")
        with open(self.registry_path, "w") as f:
            json.dump({
                "scripts": {
                    "Latn": {"name": "Latin", "direction": "ltr"},
                    "Arab": {"name": "Arabic", "direction": "rtl"}
                }
            }, f)

        self.font_path = os.path.join(self.temp_dir.name, "test_font.ttf")
        fb = FontBuilder(1024, isTTF=True)
        fb.setupGlyphOrder([".notdef", "A", "a", "A_acute", "S_sharp", "acute_comb"])
        # Map to Latn fixtures: A, a, é, ß, combining acute (0x0301)
        fb.setupCharacterMap({
            0x0041: "A", 0x0061: "a",
            0x00E9: "A_acute", 0x00DF: "S_sharp",
            0x0301: "acute_comb",
            0x0627: "A" # some Arabic
        })
        fb.setupNameTable({"familyName": "Test", "styleName": "Regular", "psName": "Test-Regular"})
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupHorizontalMetrics({
            ".notdef": (600, 0), "A": (600, 0), "a": (600, 0),
            "A_acute": (600, 0), "S_sharp": (600, 0), "acute_comb": (0, 0)
        })
        pen = TTGlyphPen(None)
        pen.moveTo((0,0)); pen.lineTo((100,0)); pen.lineTo((100,100)); pen.lineTo((0,100)); pen.closePath()
        glyph = pen.glyph()
        fb.setupGlyf({
            ".notdef": glyph, "A": glyph, "a": glyph,
            "A_acute": glyph, "S_sharp": glyph, "acute_comb": glyph
        })
        fb.setupOS2()
        fb.setupPost()
        fb.setupMaxp()
        fb.save(self.font_path)

        self.validator = GlyphCoverageValidator(self.registry_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validate_font_success_custom_points(self):
        missing = self.validator.validate_font(self.font_path, "Latn", [0x0041, 0x0061])
        self.assertEqual(missing, [])

    def test_validate_font_missing_custom_points(self):
        missing = self.validator.validate_font(self.font_path, "Latn", [0x0041, 0x0042])
        self.assertEqual(missing, [0x0042])

    def test_validate_font_full_script_fixture_success(self):
        # We mapped all Latn fixture code points in setUp, including combining mark
        missing = self.validator.validate_font(self.font_path, "Latn")
        self.assertEqual(missing, [])

    def test_validate_font_full_script_fixture_missing(self):
        # We only mapped 0x0627 for Arabic, but fixture requires more
        missing = self.validator.validate_font(self.font_path, "Arab")
        self.assertTrue(len(missing) > 0)
        self.assertIn(0x0628, missing)

    def test_generate_fallback_mapping(self):
        mapping = self.validator.generate_fallback_mapping(self.font_path, "Latn")
        self.assertTrue(mapping["is_supported"])
        self.assertEqual(mapping["script"], "Latn")
        self.assertIn("note", mapping)

        mapping_arab = self.validator.generate_fallback_mapping(self.font_path, "Arab")
        self.assertFalse(mapping_arab["is_supported"])
        self.assertTrue(len(mapping_arab["missing_code_points"]) > 0)

    def test_validate_font_fallback_not_approved(self):
        # Reject because not in approved list
        is_valid, msg = self.validator.validate_font_fallback(
            self.font_path, ["Latn"], approved_fonts_licenses={"SomeOtherFont.ttf"}
        )
        self.assertFalse(is_valid)
        self.assertIn("not approved", msg.lower())

    def test_validate_font_fallback_approved_and_supported(self):
        font_name = os.path.basename(self.font_path)
        is_valid, msg = self.validator.validate_font_fallback(
            self.font_path, ["Latn"], approved_fonts_licenses={font_name}
        )
        self.assertTrue(is_valid)
        self.assertIn("cmap only", msg)

    def test_validate_font_fallback_approved_but_missing_glyphs(self):
        font_name = os.path.basename(self.font_path)
        is_valid, msg = self.validator.validate_font_fallback(
            self.font_path, ["Latn", "Arab"], approved_fonts_licenses={font_name}
        )
        self.assertFalse(is_valid)
        self.assertIn("Missing basic glyph coverage", msg)

if __name__ == '__main__':
    unittest.main()
