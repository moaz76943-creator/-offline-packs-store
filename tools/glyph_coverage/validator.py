import os
import json
from typing import Dict, List, Optional, Set
from fontTools.ttLib import TTFont
from dataclasses import dataclass
from legal.font_assets.registry import FontAsset, FontRightsRegistry, FONT_LICENSES

# Canonical deterministic Unicode sample sets for scripts
SCRIPT_SAMPLES = {
    "Latn": [0x0041, 0x0061, 0x00E4],
    "Arab": [0x0627, 0x0628, 0x064E],
    "Hebr": [0x05D0, 0x05D1, 0x05B8],
    "Deva": [0x0905, 0x0915, 0x093E],
    "Hani": [0x4E00, 0x4E8C, 0x4E09],
    "Hans": [0x4E00, 0x4E8C, 0x4E09],
    "Hant": [0x4E00, 0x4E8C, 0x4E09],
    "Jpan": [0x3042, 0x3044, 0x3046],
    "Kore": [0xAC00, 0xAC01, 0xAC02],
    "Thai": [0x0E01, 0x0E32, 0x0E48],
    "Cyrl": [0x0410, 0x0430, 0x0411],
    "Grek": [0x0391, 0x03B1, 0x0392],
    "Armn": [0x0531, 0x0561, 0x0532],
    "Geor": [0x10D0, 0x10D1, 0x10D2],
    "Beng": [0x0985, 0x0986, 0x0987],
    "Guru": [0x0A05, 0x0A06, 0x0A07],
    "Gujr": [0x0A85, 0x0A86, 0x0A87],
    "Taml": [0x0B85, 0x0B86, 0x0B87],
    "Telu": [0x0C05, 0x0C06, 0x0C07],
    "Knda": [0x0C85, 0x0C86, 0x0C87],
    "Mlym": [0x0D05, 0x0D06, 0x0D07],
    "Orya": [0x0B05, 0x0B06, 0x0B07],
    "Sinh": [0x0D85, 0x0D86, 0x0D87],
    "Laoo": [0x0E81, 0x0E82, 0x0E84],
    "Khmr": [0x1780, 0x1781, 0x1782],
    "Mymr": [0x1000, 0x1001, 0x1002],
    "Ethi": [0x1200, 0x1201, 0x1202],
    "Mong": [0x1820, 0x1821, 0x1822],
    "Thaa": [0x0780, 0x0781, 0x0782],
    "Nkoo": [0x07CA, 0x07CB, 0x07CC],
    "Adlm": [0x1E900, 0x1E901, 0x1E902],
    "Syrc": [0x0710, 0x0712, 0x0713],
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
        registry_path = os.path.join(repo_root, "catalog", "language_registry.v1.json")
        self.valid_scripts = set()
        if os.path.exists(registry_path):
            with open(registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.valid_scripts = set(data.get("scripts", {}).keys())

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

    def validate_coverage(self, script: str, font_path: str) -> Dict[str, List[int]]:
        if self.valid_scripts and script not in self.valid_scripts:
            raise ValueError(f"Script {script} not in canonical registry")
        samples = SCRIPT_SAMPLES.get(script, [])
        samples = samples.copy()

        # Include variation selectors to see if the font supports them
        samples.extend(VARIATION_SELECTORS)

        cmap = self.get_font_cmap(font_path)
        supported = [cp for cp in samples if cp in cmap]
        unsupported = [cp for cp in samples if cp not in cmap]
        return {"supported": supported, "unsupported": unsupported}

    def generate_fallback_mapping(self, script: str, assets: List[FontAsset]) -> FallbackMapping:
        if self.valid_scripts and script not in self.valid_scripts:
            raise ValueError(f"Script {script} not in canonical registry")
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
