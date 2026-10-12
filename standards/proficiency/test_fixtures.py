import unittest

from tools.proficiency_mapping.engine import ProficiencyCatalog, ValidationError, read_json, validate_curricula


class BundledStandardsTest(unittest.TestCase):
    def test_five_pilot_languages_are_unassessed(self):
        catalog = ProficiencyCatalog()
        fixtures = read_json("pilot_fixtures.json")
        catalog.validate_records(fixtures["records"])
        self.assertEqual([r["language"] for r in fixtures["records"]], ["de", "ar", "en", "es", "fr"])
        self.assertTrue(all(r["classification_status"] == "unassessed" for r in fixtures["records"]))

    def test_empty_curricula_have_six_real_stages_and_no_fake_courses(self):
        catalog = ProficiencyCatalog()
        tracks = read_json("curricula.json")
        validate_curricula(tracks, catalog)
        self.assertEqual(len(tracks["tracks"]), 5)
        for track in tracks["tracks"]:
            self.assertEqual(len(track["stages"]), 6)
            self.assertTrue(all(not stage["content_record_ids"] for stage in track["stages"]))

    def test_registered_frameworks_are_versioned(self):
        c = ProficiencyCatalog()
        for key in ["CEFR", "PEDAGOGICAL_BANDS", "JLPT", "HSK_3_0", "CHINESE_GRADING_STANDARD"]:
            self.assertTrue(c.frameworks[key]["version"])
            self.assertIn(c.frameworks[key]["source_id"], c.sources)


if __name__ == "__main__":
    unittest.main()
