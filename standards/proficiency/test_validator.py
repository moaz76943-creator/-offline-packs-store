import unittest
from standards.proficiency.validator import ProficiencyValidator, ValidationError

class TestProficiencyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator()

    def test_positive_fixtures_all_levels(self):
        levels_and_difficulties = [
            ("A1", "beginner"),
            ("A2", "beginner"),
            ("B1", "intermediate"),
            ("B2", "intermediate"),
            ("C1", "advanced"),
            ("C2", "advanced"),
        ]

        for cefr, coarse in levels_and_difficulties:
            with self.subTest(cefr=cefr, coarse=coarse):
                record = {
                    "language": "en",
                    "entry_level_classification": {
                        "classification_status": "verified",
                        "cefr_level": cefr,
                        "coarse_difficulty": coarse,
                        "source_identity": "COE-CEFR-2020",
                        "evaluation_method": "descriptor_guided_review"
                    },
                    "example_level_classification": {
                        "classification_status": "verified",
                        "cefr_level": cefr,
                        "coarse_difficulty": coarse,
                        "source_identity": "COE-CEFR-2020",
                        "evaluation_method": "descriptor_guided_review"
                    }
                }
                validated = self.validator.validate_metadata(record)
                self.assertEqual(validated, record)

    def test_missing_source_evidence_for_verified(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner"
            },
            "example_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner"
            }
        }
        with self.assertRaisesRegex(ValidationError, "source_identity is required for verified CEFR levels"):
            self.validator.validate_metadata(record)

    def test_conflicting_labels(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "advanced",
                "source_identity": "COE-CEFR-2020",
                "evaluation_method": "descriptor_guided_review"
            },
            "example_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "advanced",
                "source_identity": "COE-CEFR-2020",
                "evaluation_method": "descriptor_guided_review"
            }
        }
        with self.assertRaisesRegex(ValidationError, "Conflicting difficulty labels: A1 does not match advanced"):
            self.validator.validate_metadata(record)

    def test_unknown_difficulty_incorrectly_specified(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "unknown",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner"
            },
            "example_level_classification": {
                "classification_status": "unknown",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner"
            }
        }
        with self.assertRaisesRegex(ValidationError, "Cannot claim difficulty for unknown status"):
            self.validator.validate_metadata(record)

    def test_wrong_language_metadata(self):
        record = {
            "language": "invalid_lang_code",
            "entry_level_classification": {
                "classification_status": "unknown",
                "cefr_level": "unknown",
                "coarse_difficulty": "unknown"
            },
            "example_level_classification": {
                "classification_status": "unknown",
                "cefr_level": "unknown",
                "coarse_difficulty": "unknown"
            }
        }
        with self.assertRaisesRegex(ValidationError, "Schema validation failed"):
            self.validator.validate_metadata(record)

    def test_invented_source_identity(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner",
                "source_identity": "MADE_UP_SOURCE",
                "evaluation_method": "descriptor_guided_review"
            },
            "example_level_classification": {
                "classification_status": "verified",
                "cefr_level": "A1",
                "coarse_difficulty": "beginner",
                "source_identity": "MADE_UP_SOURCE",
                "evaluation_method": "descriptor_guided_review"
            }
        }
        with self.assertRaisesRegex(ValidationError, "Invalid or invented source_identity: MADE_UP_SOURCE"):
            self.validator.validate_metadata(record)

    def test_unverified_status_with_difficulty(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "unverified",
                "cefr_level": "A1",
                "coarse_difficulty": "unknown"
            },
            "example_level_classification": {
                "classification_status": "unverified",
                "cefr_level": "A1",
                "coarse_difficulty": "unknown"
            }
        }
        with self.assertRaisesRegex(ValidationError, "Cannot claim difficulty for unverified status"):
            self.validator.validate_metadata(record)

    def test_unverified_status_clean(self):
        record = {
            "language": "en",
            "entry_level_classification": {
                "classification_status": "unverified",
                "cefr_level": "unknown",
                "coarse_difficulty": "unknown"
            },
            "example_level_classification": {
                "classification_status": "unverified",
                "cefr_level": "unknown",
                "coarse_difficulty": "unknown"
            }
        }
        validated = self.validator.validate_metadata(record)
        self.assertEqual(validated, record)

if __name__ == '__main__':
    unittest.main()
