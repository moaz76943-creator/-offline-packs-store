import unittest
from standards.proficiency.validator import ProficiencyValidator

class TestProficiencyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator()
        self.base_valid_record = {
            "proficiency_level": "A1",
            "coarse_difficulty": "beginner",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review",
            "status": "estimated",
            "language_applicability": ["en", "fr"],
            "assessment_policy": "strict"
        }

    def test_valid_record(self):
        self.assertTrue(self.validator.validate(self.base_valid_record))

    def test_all_levels(self):
        levels_and_diffs = [
            ("A1", "beginner"),
            ("A2", "beginner"),
            ("B1", "intermediate"),
            ("B2", "intermediate"),
            ("C1", "advanced"),
            ("C2", "advanced"),
            ("unknown", "unknown")
        ]

        for level, diff in levels_and_diffs:
            record = self.base_valid_record.copy()
            record["proficiency_level"] = level
            record["coarse_difficulty"] = diff
            self.assertTrue(self.validator.validate(record))

    def test_invalid_source_identity(self):
        record = self.base_valid_record.copy()
        record["source_identity"] = "FAKE-SOURCE-99"
        with self.assertRaises(ValueError):
            self.validator.validate(record)

    def test_conflicting_labels(self):
        record = self.base_valid_record.copy()
        record["proficiency_level"] = "A1"
        record["coarse_difficulty"] = "advanced"
        with self.assertRaises(ValueError):
            self.validator.validate(record)

    def test_missing_source_evidence(self):
        record = self.base_valid_record.copy()
        del record["source_identity"]
        with self.assertRaises(ValueError):
            self.validator.validate(record)

    def test_wrong_language_metadata(self):
        record = self.base_valid_record.copy()
        record["language_applicability"] = ["invalid_lang_code_123"]
        with self.assertRaises(ValueError):
            self.validator.validate(record)

    def test_unknown_difficulty(self):
        record = self.base_valid_record.copy()
        record["proficiency_level"] = "unknown"
        record["coarse_difficulty"] = "unknown"
        self.assertTrue(self.validator.validate(record))

    def test_cefr_verified(self):
        record = self.base_valid_record.copy()
        record["status"] = "verified"
        with self.assertRaises(ValueError):
            self.validator.validate(record)

if __name__ == '__main__':
    unittest.main()
