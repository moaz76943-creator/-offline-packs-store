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
                    source={
                        "repository": "offline-packs-store",
                        "manifest_path": "manifest.json",
                        "reviewed_head_sha": "bb15e9f02b216bbcb62a254d4a5bd695d405e9d5",
                        "selection_policy": "preserve_all_100_published_stable_ids"
                    },
                    frameworks={}, languages=langs, aliases=[], locale_variants=[])
    readiness = dict(schema_version="1.0.0",registry_version="1.0.0", states={x:"unverified" for x in codes},validation_evidence={})
    manifest = dict(languages=[dict(code=l["id"],family=l["family"],native_name=l["native_name"]) for l in langs])
    return registry, readiness, manifest


class TaxonomyValidationTests(unittest.TestCase):
    def test_all_100_ids_have_negative_fixtures(self):
        r, c, m = fixture()
        # Verify 100 languages exist
        self.assertEqual(100, len(r["languages"]))
        # Negative test for each language
        for i in range(100):
            with self.subTest(i=i):
                r_copy, c_copy, m_copy = fixture()
                r_copy["languages"][i]["id"] = "invalid_id_!!!"
                failures = validate(r_copy, c_copy, m_copy)
                self.assertTrue(len(failures) > 0, f"Expected validation failure for invalid ID at index {i}")

                r_copy, c_copy, m_copy = fixture()
                r_copy["languages"][i]["native_name"] = ""
                failures = validate(r_copy, c_copy, m_copy)
                self.assertTrue(len(failures) > 0, f"Expected validation failure for missing native_name at index {i}")

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


    def test_schema_versions(self):
        r, c, m = fixture()
        r["schema_version"] = "2.0.0"
        self.assertTrue(any("unsupported registry schema_version" in s for s in validate(r, c, m)))
        r["schema_version"] = "1.0.0"
        c["schema_version"] = "2.0.0"
        self.assertTrue(any("unsupported readiness schema_version" in s for s in validate(r, c, m)))
        c["schema_version"] = "1.0.0"
        c["registry_version"] = "2.0.0"
        self.assertTrue(any("readiness registry_version mismatch" in s for s in validate(r, c, m)))

    def test_invalid_types(self):
        r, c, m = fixture()
        r["scripts"] = []
        self.assertEqual(validate(r, c, m)[-1], "scripts/languages/frameworks have invalid container types")
        r["scripts"] = {}
        r["languages"] = {}
        self.assertEqual(validate(r, c, m)[-1], "scripts/languages/frameworks have invalid container types")

    def test_wrong_language_count(self):
        r, c, m = fixture()
        r["languages"].pop()
        self.assertTrue(any("expected 100 languages, found 99" in s for s in validate(r, c, m)))

    def test_invalid_script_spec(self):
        r, c, m = fixture()
        r["scripts"]["invalid"] = {"direction": "ltr"}
        self.assertTrue(any("invalid ISO 15924 script syntax" in s for s in validate(r, c, m)))
        r["scripts"]["Latn"] = "not_a_dict"
        self.assertTrue(any("invalid script direction" in s for s in validate(r, c, m)))
        r["scripts"]["Latn"] = {"direction": "up"}
        self.assertTrue(any("invalid script direction" in s for s in validate(r, c, m)))
        r["scripts"]["Arab"]["direction"] = "ttb-ltr"
        self.assertTrue(any("RTL script-direction mismatch: Arab" in s for s in validate(r, c, m)))

    def test_invalid_language_fields(self):
        r, c, m = fixture()
        r["languages"][0] = "not_a_dict"
        m = None # Do not run manifest check since lang is invalid
        self.assertTrue(any("non-object language record" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["id"] = "invalid_id!"
        self.assertTrue(any("invalid stable language id: invalid_id!" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["native_name"] = ""
        self.assertTrue(any("missing native name" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["display_names"] = "not_a_dict"
        self.assertTrue(any("missing localized display name" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["display_names"]["en"] = ""
        self.assertTrue(any("missing localized display name" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["family"] = ""
        self.assertTrue(any("missing linguistic family" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["scripts"] = "not_a_list"
        self.assertTrue(any("unknown or duplicated script" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["scripts"] = ["Latn", "Latn"]
        self.assertTrue(any("unknown or duplicated script" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["scripts"] = ["Latn", "Unknown"]
        self.assertTrue(any("unknown or duplicated script" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["default_script"] = "Arab"
        self.assertTrue(any("default script not supported" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["regions"] = ["invalid"]
        self.assertTrue(any("invalid region list" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["dialects"] = "not_list"
        self.assertTrue(any("invalid dialect list" in s for s in validate(r, c, m)))

    def test_invalid_morphology_proficiency(self):
        r, c, m = fixture()
        r["languages"][0]["morphology"] = {"review_status": "invalid"}
        self.assertTrue(any("invalid morphology classification" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["morphology"]["features"] = ["invalid_feature"]
        self.assertTrue(any("invalid morphology features" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["proficiency"]["mapping_status"] = "invalid"
        self.assertTrue(any("invalid proficiency state" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["proficiency"]["framework_ids"] = ["unknown_fw"]
        self.assertTrue(any("unknown proficiency framework" in s for s in validate(r, c, m)))

    def test_invalid_frameworks(self):
        r, c, m = fixture()
        r["frameworks"]["test"] = {"scale_type": "invalid", "levels": []}
        self.assertTrue(any("invalid framework: test" in s for s in validate(r, c, m)))
        r["frameworks"]["test"] = {"scale_type": "general", "levels": []}
        self.assertTrue(any("invalid framework: test" in s for s in validate(r, c, m)))

    def test_invalid_aliases(self):
        r, c, m = fixture()
        r["aliases"].append("not_dict")
        self.assertTrue(any("invalid alias record" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["aliases"].append({"from": "invalid_tag!", "to": "aa"})
        self.assertTrue(any("invalid alias tag: invalid_tag!" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["aliases"].append({"from": "aa-Latn", "to": "unknown"})
        self.assertTrue(any("alias target missing" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["aliases"].append({"from": "aa-Latn", "to": "aa", "lossy": False, "status": "migration_review_required"})
        self.assertTrue(any("unsafe unreviewed fallback alias" in s for s in validate(r, c, m)))

    def test_invalid_locale_variants(self):
        r, c, m = fixture()
        r["locale_variants"].append("not_dict")
        self.assertTrue(any("invalid locale variant record" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["locale_variants"].append({"tag": "invalid_tag!", "language_id": "aa"})
        self.assertTrue(any("invalid locale tag: invalid_tag!" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["locale_variants"].append({"tag": "ab-Latn", "language_id": "unknown"})
        self.assertTrue(any("variant language missing" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["locale_variants"].append({"tag": "ab-Latn", "language_id": "aa"})
        self.assertTrue(any("variant primary language mismatch" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["locale_variants"].append({"tag": "aa-Arab", "language_id": "aa", "script": "Arab"})
        self.assertTrue(any("variant script mismatch" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["languages"][0]["regions"] = ["US"]
        r["locale_variants"].append({"tag": "aa-US", "language_id": "aa", "region": "US"})
        self.assertEqual([], validate(r, c, m))

        r["locale_variants"][0]["region"] = "GB"
        self.assertTrue(any("variant region mismatch" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        r["locale_variants"].append({"tag": "aa-Latn", "language_id": "aa"})
        self.assertTrue(any("undifferentiated variant" in s for s in validate(r, c, m)))

    def test_invalid_readiness(self):
        r, c, m = fixture()
        c["states"] = []
        self.assertTrue(any("readiness states must match all and only canonical IDs" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        c["states"]["aa"] = "invalid_state"
        self.assertTrue(any("invalid content readiness state" in s for s in validate(r, c, m)))

        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {"pack_sha256": "invalid_hash", "validation_method": "automated_quality_gate"}
        self.assertTrue(any("independent evidence" in s for s in validate(r, c, m)))

    def test_release_ready_edge_cases(self):
        r, c, m = fixture()
        c["states"]["aa"] = "releaseReady"
        c["validation_evidence"]["aa"] = {"pack_sha256": "a"*64, "validation_method": "automated_quality_gate"}
        self.assertTrue(any("lacks verified published pack state" in s for s in validate(r, c, m)))

        m["languages"][0].update({"content_available": True, "pack_verified": True, "production_ready": True, "is_active": True})
        self.assertTrue(any("pack hash/schema does not match" in s for s in validate(r, c, m)))

        m["languages"][0].update({"sha256": "a"*64, "schemaVersion": "2.0", "format": "jsonl"})
        self.assertTrue(any("independently admitted sources" in s for s in validate(r, c, m)))

        c["validation_evidence"]["aa"]["source_ids"] = ["source1"]
        self.assertTrue(any("independently admitted sources" in s for s in validate(r, c, m)))

        m["release_status"] = "BLOCKED_DEPENDENCY"
        self.assertTrue(any("blocked by global release state" in s for s in validate(r, c, m)))

    def test_changed_native_name(self):
        r, c, m = fixture()
        r["languages"][0]["native_name"] = "Changed"
        self.assertTrue(any("changed native name versus published manifest" in s for s in validate(r, c, m)))

    def test_alias_collision_with_existing(self):
        r, c, m = fixture()
        # Create an alias that collides with an existing language tag
        r["aliases"].append({"from": "aa", "to": "ab", "lossy": True, "status": "migration_review_required"})
        self.assertTrue(any("alias/variant collision: aa" in s for s in validate(r, c, m)))

    def test_main(self):
        import tempfile
        import json
        from pathlib import Path
        from catalog.validate_registry import main
        r, c, m = fixture()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "r.json").write_text(json.dumps(r), encoding="utf-8")
            (tdp / "c.json").write_text(json.dumps(c), encoding="utf-8")
            (tdp / "m.json").write_text(json.dumps(m), encoding="utf-8")
            import catalog.validate_registry as vr
            orig_here = vr.HERE
            try:
                vr.HERE = tdp / "catalog"
                (tdp / "catalog").mkdir()
                (tdp / "legal" / "ledger").mkdir(parents=True)
                (tdp / "legal" / "ledger" / "sources.json").write_text(json.dumps({"sources":[]}), encoding="utf-8")
                self.assertEqual(0, main(["--registry", str(tdp/"r.json"), "--readiness", str(tdp/"c.json"), "--manifest", str(tdp/"m.json")]))
                r["schema_version"] = "invalid"
                (tdp / "r.json").write_text(json.dumps(r), encoding="utf-8")
                self.assertEqual(1, main(["--registry", str(tdp/"r.json"), "--readiness", str(tdp/"c.json"), "--manifest", str(tdp/"m.json")]))
            finally:
                vr.HERE = orig_here

    def test_missing_file_handled_gracefully(self):
        from catalog.validate_registry import main
        import tempfile
        import json
        from pathlib import Path
        import catalog.validate_registry as vr
        r, c, m = fixture()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "c.json").write_text(json.dumps(c), encoding="utf-8")
            (tdp / "m.json").write_text(json.dumps(m), encoding="utf-8")
            orig_here = vr.HERE
            try:
                vr.HERE = tdp / "catalog"
                (tdp / "catalog").mkdir()
                (tdp / "legal" / "ledger").mkdir(parents=True)
                (tdp / "legal" / "ledger" / "sources.json").write_text(json.dumps({"sources":[]}), encoding="utf-8")

                # Missing registry
                self.assertEqual(1, main(["--registry", str(tdp/"nonexistent.json"), "--readiness", str(tdp/"c.json"), "--manifest", str(tdp/"m.json")]))
            finally:
                vr.HERE = orig_here

if __name__ == "__main__":
    unittest.main()
