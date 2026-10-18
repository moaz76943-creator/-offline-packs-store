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
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"] = {"other": {"pack_sha256": "a" * 64, "validation_method": "manual_review"}}
        self.assertTrue(any("independent evidence" in s for s in validate(r,c,m)))

    def test_manifest_removal_requires_migration(self):
        r, c, m = fixture()
        m["languages"].pop()
        self.assertTrue(any("published manifest ID mismatch" in s for s in validate(r,c,m)))

    def test_well_formed_hash_is_not_independent_pack_evidence(self):
        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {
            "pack_sha256": "a" * 64, "validation_method": "automated_quality_gate",
            "source_ids": ["source.synthetic"]
        }
        failures = validate(r, c, m, source_ledger={"sources":[]})
        self.assertTrue(any("verified published pack" in item for item in failures))
        self.assertTrue(any("independently admitted sources" in item for item in failures))

    def test_release_readiness_rejects_unverified_legacy_manifest(self):
        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {
            "pack_sha256": "a" * 64, "validation_method": "manual_review",
            "source_ids": ["source.synthetic"]
        }
        m["languages"][0].update({
            "sha256":"a" * 64, "content_available":True,
            "pack_verified":True, "production_ready":True, "is_active":True,
            "schemaVersion":"legacy", "format":"legacy-json-gzip"
        })
        failures = validate(r, c, m)
        self.assertTrue(any("automated quality gate" in item for item in failures))
        self.assertTrue(any("pack hash/schema" in item for item in failures))

    def test_readiness_rejects_hash_type_without_crash(self):
        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {
            "pack_sha256": 42, "validation_method": "automated_quality_gate"
        }
        self.assertTrue(any("independent evidence" in x for x in validate(r, c, m)))

    def test_source_identity_list_must_be_valid(self):
        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {
            "pack_sha256": "a" * 64, "validation_method": "automated_quality_gate",
            "source_ids": [["invalid"]]
        }
        failures = validate(r, c, m, source_ledger={"sources":[]})
        self.assertTrue(any("independently admitted sources" in x for x in failures))

    def test_real_public_registry_integrity(self):
        registry = json.loads((HERE / "language_registry.v1.json").read_text(encoding="utf-8"))
        readiness = json.loads((HERE / "content_readiness.v1.json").read_text(encoding="utf-8"))
        manifest = json.loads((HERE.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([], validate(registry, readiness, manifest))
        self.assertEqual(100, len(registry["languages"]))
        self.assertTrue(all(value != "releaseReady" for value in readiness["states"].values()))

if __name__ == "__main__":
    unittest.main()
