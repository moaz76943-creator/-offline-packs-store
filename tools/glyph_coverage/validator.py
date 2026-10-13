import json
import os
from fontTools.ttLib import TTFont
from tools.glyph_coverage.fixtures import SCRIPT_SAMPLES

class GlyphCoverageValidator:
    """
    Verifies actual font coverage against script samples.
    Important: cmap support does not guarantee correct text shaping (e.g. contextual ligatures, complex scripts).
    This only validates that a font claims support for a base code point in its character map.
    """

    def __init__(self, registry_path):
        self.registry_path = registry_path
        if os.path.exists(registry_path):
            with open(registry_path, 'r', encoding='utf-8') as f:
                self.registry = json.load(f)
            self.scripts = list(self.registry.get('scripts', {}).keys())
        else:
            self.registry = {}
            self.scripts = []

    def get_font_cmap(self, font_path):
        """Extracts font character-map support from actual font data."""
        font = TTFont(font_path)
        return font.getBestCmap()

    def check_coverage(self, cmap, code_points):
        """Detect unsupported code points."""
        if not cmap:
            return list(code_points)

        missing = []
        for cp in code_points:
            if cp not in cmap:
                missing.append(cp)
        return missing

    def generate_fallback_mapping(self, font_path, script, sample_code_points=None):
        """Generates actionable fallback mapping data if a font supports the script."""
        if sample_code_points is None:
            sample_code_points = SCRIPT_SAMPLES.get(script, [])

        missing = self.validate_font(font_path, script, sample_code_points)

        # We will consider it a valid fallback if it has full coverage of the core points.
        is_supported = len(missing) == 0
        return {
            "font_path": font_path,
            "script": script,
            "is_supported": is_supported,
            "missing_code_points": missing,
            "note": "Coverage is based on cmap presence, not text shaping or device-rendering verification."
        }

    def validate_font(self, font_path, script, sample_code_points=None):
        """Validates if a font has basic glyph coverage for a given script."""
        if sample_code_points is None:
            sample_code_points = SCRIPT_SAMPLES.get(script, [])

        cmap = self.get_font_cmap(font_path)
        missing = self.check_coverage(cmap, sample_code_points)
        return missing

    def validate_font_fallback(self, font_path, required_scripts, approved_fonts_licenses=None):
        """
        Reject fallback families that are not available or licensed.
        approved_fonts_licenses: set of approved fonts (if provided, we check if font is in it)
        """
        if not os.path.exists(font_path):
            return False, "Font file not available."

        font_name = os.path.basename(font_path)
        if approved_fonts_licenses is not None and font_name not in approved_fonts_licenses:
            return False, "Font not approved or licensed."

        for script in required_scripts:
            missing = self.validate_font(font_path, script)
            if missing:
                return False, f"Missing basic glyph coverage for script {script}: {missing}"

        return True, "Valid fallback mapping (cmap only, no shaping guarantees)"
