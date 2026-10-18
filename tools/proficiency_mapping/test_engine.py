import copy
import unittest

from tools.proficiency_mapping.engine import ProficiencyCatalog, ValidationError, read_json


class ProficiencyTest(unittest.TestCase):
    def setUp(self):
        self.catalog = ProficiencyCatalog()
        self.pilot = read_json("pilot_fixtures.json")["records"][0]

    def test_all_six_cefr_values_are_distinct(self):
        framework = self.catalog.frameworks["CEFR"]
        self.assertEqual(framework["levels"], ["A1", "A2", "B1", "B2", "C1", "C2"])
        for level in framework["levels"]:
            with self.subTest(level=level):
                record = copy.deepcopy(self.pilot)
                record.update(classification_status="estimated", proficiency_framework_id="CEFR",
                              proficiency_level_id=level,
                              evidence=[{"source_id": "COE-CEFR-2020", "source_version": "2020 Companion volume",
                                         "source_url": self.catalog.sources["COE-CEFR-2020"]["url"],
                                         "locator": f"synthetic descriptor-guided test for {level}",
                                         "method": "descriptor_guided_review", "reviewer_id": "test-only"}])
                self.assertIs(self.catalog.validate_record(record), record)

    def test_unassessed_and_unknown_are_explicit(self):
        self.catalog.validate_record(self.pilot)
        copy_record = copy.deepcopy(self.pilot)
        copy_record["classification_status"] = "unknown"
        self.catalog.validate_record(copy_record)
        copy_record["proficiency_level_id"] = "A1"
        with self.assertRaises(ValidationError):
            self.catalog.validate_record(copy_record)

    def test_frequency_does_not_establish_level(self):
        record = copy.deepcopy(self.pilot)
        record["proficiency_framework_id"] = "CEFR"
        record["proficiency_level_id"] = "A1"
        with self.assertRaises(ValidationError):
            self.catalog.validate_record(record)

    def test_fake_evidence_identity_rejected(self):
        record = copy.deepcopy(self.pilot)
        record.update(classification_status="estimated", proficiency_framework_id="CEFR", proficiency_level_id="C2")
        record["evidence"] = [{"source_id": "COE-CEFR-2020", "source_version": "fabricated",
                               "source_url": "https://example.com/pretend", "locator": "x",
                               "method": "descriptor_guided_review", "reviewer_id": "x"}]
        with self.assertRaises(ValidationError):
            self.catalog.validate_record(record)

    def test_jlpt_score_condition_and_skill_scope(self):
        result = self.catalog.map_level("JLPT", "N3", "CEFR", passed=True, total_score=104, skill="reading")
        self.assertEqual(result["proficiency_level_id"], "B1")
        self.assertFalse(result["certifies_full_proficiency"])
        self.assertEqual(self.catalog.map_level("JLPT", "N3", "CEFR", passed=True, total_score=103, skill="listening")["proficiency_level_id"], "A2")
        for args in ({"passed": False, "total_score": 104, "skill": "reading"},
                     {"passed": True, "total_score": 104, "skill": "writing"},
                     {"passed": True, "total_score": 104},
                     {"passed": True, "total_score": 94, "skill": "reading"}):
            self.assertEqual(self.catalog.map_level("JLPT", "N3", "CEFR", **args)["status"], "unknown")

    def test_no_hsk_or_pedagogical_band_equivalence(self):
        self.assertEqual(self.catalog.map_level("HSK_3_0", "4", "CEFR", total_score=180)["status"], "unknown")
        self.assertEqual(self.catalog.map_level("PEDAGOGICAL_BANDS", "advanced", "CEFR", total_score=180)["status"], "unknown")

    def test_conflicting_mappings_rejected(self):
        maps = copy.deepcopy(self.catalog.mapping_data)
        row = copy.deepcopy(maps["published_reference_mappings"][0])
        row["to_level"] = "C2"
        maps["published_reference_mappings"].append(row)
        with self.assertRaises(ValidationError):
            ProficiencyCatalog(mappings=maps)

    def test_enrichment_is_idempotent_and_fails_on_conflict(self):
        merged = self.catalog.enrich([self.pilot], [copy.deepcopy(self.pilot)])
        self.assertEqual(len(merged), 1)
        changed = copy.deepcopy(self.pilot)
        changed["topic_domains"] = ["food"]
        with self.assertRaises(ValidationError):
            self.catalog.enrich([self.pilot], [changed])

    def test_enrich_can_reference_previously_curated_records(self):
        next_record = copy.deepcopy(self.pilot)
        next_record["record_id"] = "pilot:de:next"
        next_record["prerequisites"] = [self.pilot["record_id"]]
        merged = self.catalog.enrich([self.pilot], [next_record])
        self.assertEqual(len(merged), 2)

    def test_cycle_fails(self):
        a = copy.deepcopy(self.pilot)
        b = copy.deepcopy(a)
        a["record_id"], b["record_id"] = "a", "b"
        a["prerequisites"], b["prerequisites"] = ["b"], ["a"]
        with self.assertRaises(ValidationError):
            self.catalog.validate_records([a, b])

    def test_script_modes_and_unknown_skills(self):
        r = copy.deepcopy(self.pilot)
        r["skills"]["writing"]["mode"] = "receptive"
        with self.assertRaises(ValidationError):
            self.catalog.validate_record(r)
        with self.assertRaises(ValidationError):
            self.catalog.map_level("JLPT", "N5", "CEFR", skill="grammar")


if __name__ == "__main__":
    unittest.main()
