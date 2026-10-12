"""Focused contract tests plus real-manifest integration checks (no network)."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate_registry import validate


def fixture():
    codes = [chr(97 + x // 26) + chr(97 + x % 26) for x in range(100)]
    langs = [dict(id=code, native_name=code, display_names={"en":code, "ar":code},
                  family="Test", scripts=["Latn"], default_script="Latn",
                  regions=[], dialects=[], morphology={"features":["number"],"review_status":"provisional"},
                  proficiency={"framework_ids":[], "mapping_status":"not_mapped"}) for code in codes]
    registry = dict(schema_version="1.0.0", scripts={"Latn":{"name":"Latin","direction":"ltr"},
                    "Arab":{"name":"Arabic","direction":"rtl"}, "Hebr":{"name":"Hebrew","direction":"rtl"}},
                    frameworks={}, languages=langs, aliases=[], locale_variants=[])
    readiness = dict(schema_version="1.0.0",registry_version="1.0.0", states={x:"unverified" for x in codes},validation_evidence={})
    manifest = dict(languages=[dict(code=l["id"],family=l["family"],native_name=l["native_name"]) for l in langs])
    return registry, readiness, manifest


class TaxonomyValidationTests(unittest.TestCase):
    def test_fresh_registry_passes(self):
        self.assertEqual([], validate(*fixture()))

    def test_duplicate_id(self):
        r, c, m = fixture()
        r["languages"][1]["id"] = r["languages"][0]["id"]
        self.assertTrue(any("duplicate language id" in s for s in validate(r,c,m)))

    def test_invalid_bcp47_locale_tag(self):
        r, c, m = fixture()
        r["locale_variants"].append(dict(tag="aa--Arab",language_id="aa",script="Arab",region=None,dialect=None))
        self.assertTrue(any("invalid locale tag" in s for s in validate(r,c,m)))

    def test_script_driven_rtl(self):
        r, c, m = fixture()
        r["scripts"]["Arab"]["direction"] = "ltr"
        self.assertTrue(any("RTL script-direction mismatch: Arab" in s for s in validate(r,c,m)))

    def test_hebrew_script_is_not_forced_ltr(self):
        r, c, m = fixture()
        self.assertEqual("rtl", r["scripts"]["Hebr"]["direction"])
        self.assertEqual([], validate(r,c,m))

    def test_mongolian_script_has_vertical_primary_direction(self):
        r, c, m = fixture()
        r["scripts"]["Mong"] = {"name":"Mongolian","direction":"ttb-ltr"}
        self.assertEqual([], validate(r,c,m))
        r["scripts"]["Mong"]["direction"] = "ltr"
        self.assertTrue(any("vertical script-direction mismatch: Mong" in s for s in validate(r,c,m)))

    def test_alias_and_variant_collision(self):
        r, c, m = fixture()
        r["aliases"].append({"from":"aa-Latn","to":"aa","lossy":True,"status":"migration_review_required"})
        r["locale_variants"].append(dict(tag="aa-Latn",language_id="aa",script="Latn",region=None,dialect=None))
        self.assertTrue(any("alias/variant collision: aa-Latn" in s for s in validate(r,c,m)))

    def test_family_against_published_manifest(self):
        r, c, m = fixture()
        r["languages"][0]["family"] = "Unrelated"
        self.assertTrue(any("inconsistent family" in s for s in validate(r,c,m)))

    def test_content_not_implicitly_ready(self):
        r, c, m = fixture()
        c["states"]["aa"] = "validated"
        self.assertTrue(any("independent evidence" in s for s in validate(r,c,m)))

    def test_manifest_removal_requires_migration(self):
        r, c, m = fixture()
        m["languages"].pop()
        self.assertTrue(any("published manifest ID mismatch" in s for s in validate(r,c,m)))

    def test_real_public_registry_integrity(self):
        registry = json.loads((HERE / "language_registry.v1.json").read_text(encoding="utf-8"))
        readiness = json.loads((HERE / "content_readiness.v1.json").read_text(encoding="utf-8"))
        manifest = json.loads((HERE.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([], validate(registry, readiness, manifest))
        self.assertEqual(100, len(registry["languages"]))
        self.assertTrue(all(value != "validated" for value in readiness["states"].values()))

if __name__ == "__main__":
    unittest.main()
