import os
import json
from typing import Dict, List, Optional, Set, Any
from fontTools.ttLib import TTFont
from dataclasses import dataclass
from legal.font_assets.registry import FontAsset, FontRightsRegistry, FONT_LICENSES

# Canonical deterministic Unicode sample sets for scripts
SCRIPT_SAMPLES = {
    "Latn": [0x0041, 0x0061, 0x00E4],  # A, a, a-umlaut
    "Arab": [0x0627, 0x0628, 0x064E],  # Alef, Ba, Fatha (combining mark)
    "Hebr": [0x05D0, 0x05D1, 0x05B8],  # Alef, Bet, Qamats (combining mark)
    "Deva": [0x0905, 0x0915, 0x093E],  # A, Ka, Aa (combining mark)
    "Hani": [0x4E00, 0x4E8C, 0x4E09],  # One, Two, Three
    "Thai": [0x0E01, 0x0E32, 0x0E48],  # Ko Kai, Sara Aa, Mai Ek
    "Cyrl": [0x0410, 0x0430, 0x0411],  # A, a, Be
    "Grek": [0x0391, 0x03B1, 0x0392],  # Alpha, alpha, Beta
    "Armn": [0x0531, 0x0561, 0x0532],  # Ayb, ayb, Ben
}

# Variation selectors and combining marks (common)
VARIATION_SELECTORS = [0xFE0E, 0xFE0F]

@dataclass
class FallbackMapping:
    script: str
    supported_points: List[int]
    unsupported_points: List[int]
    cmap_coverage: bool
    shaping_guaranteed: bool
    device_rendering_guaranteed: bool
    valid_fallback_families: List[str]

class GlyphCoverageValidator:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.registry = FontRightsRegistry()
        self._cached_scripts: Optional[Set[str]] = None

    def _get_canonical_scripts(self) -> Set[str]:
        if self._cached_scripts is not None:
            return self._cached_scripts

        registry_path = os.path.join(self.repo_root, "catalog", "language_registry.v1.json")
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        scripts = set()

        # Read directly from the 'scripts' top-level object if present
        if "scripts" in data and isinstance(data["scripts"], dict):
            scripts.update(data["scripts"].keys())

        for lang in data.get("languages", []):
            if "scripts" in lang:
                scripts.update(lang["scripts"])
        for variant in data.get("locale_variants", []):
            if variant.get("script"):
                scripts.add(variant["script"])

        # Also statically add Hani if CJK (Hani) is implied by Hans/Hant/Jpan/Kore
        if any(s in scripts for s in ["Hans", "Hant", "Jpan", "Kore"]):
            scripts.add("Hani")

        self._cached_scripts = scripts
        return scripts

    def get_font_cmap(self, font_path: str) -> Set[int]:
        try:
            with TTFont(font_path) as font:
                cmap = set()
                for table in font['cmap'].tables:
                    if table.isUnicode():
                        cmap.update(table.cmap.keys())
                return cmap
        except Exception:
            return set()

    def validate_coverage(self, script: str, font_path: str) -> Dict[str, Any]:
        try:
            canonical_scripts = self._get_canonical_scripts()
        except FileNotFoundError:
            return {
                "status": "REJECT",
                "issues": ["Canonical registry missing"],
                "supported": [],
                "unsupported": SCRIPT_SAMPLES.get(script, []).copy() + VARIATION_SELECTORS
            }

        samples = SCRIPT_SAMPLES.get(script, [])
        samples = samples.copy()
        samples.extend(VARIATION_SELECTORS)

        if script not in canonical_scripts:
            return {
                "status": "REJECT",
                "issues": ["Script not in canonical registry"],
                "supported": [],
                "unsupported": samples
            }

        cmap = self.get_font_cmap(font_path)
        supported = [cp for cp in samples if cp in cmap]
        unsupported = [cp for cp in samples if cp not in cmap]
        return {"status": "EVIDENCE_PASS", "issues": [], "supported": supported, "unsupported": unsupported}

    def generate_fallback_mapping(self, script: str, assets: List[FontAsset]) -> FallbackMapping:
        samples = SCRIPT_SAMPLES.get(script, [])
        samples = samples.copy()
        samples.extend(VARIATION_SELECTORS)

        valid_families = []
        best_supported = []
        best_unsupported = samples.copy()
        cmap_coverage = False

        for asset in assets:
            res = self.registry.validate_asset(asset, repo_root=self.repo_root)
            if res.get("status") != "EVIDENCE_PASS":
                continue

            if not asset.embedded or not asset.asset_path:
                continue

            full_path = os.path.join(self.repo_root, asset.asset_path)
            if not os.path.isfile(full_path):
                continue

            if script not in asset.scripts:
                continue

            coverage = self.validate_coverage(script, full_path)

            if coverage.get("status") == "REJECT":
                continue

            if not coverage["unsupported"]:
                valid_families.append(asset.family)
                if not cmap_coverage:
                    best_supported = coverage["supported"]
                    best_unsupported = coverage["unsupported"]
                    cmap_coverage = True
            elif not cmap_coverage and len(coverage["supported"]) > len(best_supported):
                best_supported = coverage["supported"]
                best_unsupported = coverage["unsupported"]
                # DO NOT set cmap_coverage to true unless it's full coverage

        return FallbackMapping(
            script=script,
            supported_points=best_supported,
            unsupported_points=best_unsupported,
            cmap_coverage=cmap_coverage,
            shaping_guaranteed=False,
            device_rendering_guaranteed=False,
            valid_fallback_families=valid_families
        )
