import unittest
from standards.proficiency.validator import ProficiencyValidator, ProficiencyValidationError

class TestProficiencyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator()

    def test_valid_verified_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "label_status": "verified",
            "cefr_level": "B2",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": True,
                "advanced": False
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_01",
                "source_version": "1.0"
            }
        }
        # Should not raise
        self.validator.validate(metadata)

    def test_valid_estimated_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "es",
            "classification_target": "example",
            "label_status": "estimated",
            "cefr_level": "A1",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            },
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {
                "source_id": "TEST_SOURCE_02",
                "source_version": "2.0"
            }
        }
        self.validator.validate(metadata)

    def test_valid_unverified_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "fr",
            "classification_target": "entry",
            "label_status": "unverified",
            "cefr_level": "unknown",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": False
            }
        }
        self.validator.validate(metadata)

    def test_missing_source_evidence(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "label_status": "verified",
            "cefr_level": "C1",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": True
            },
            "evaluation_method": "published_content_assignment"
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("Verified and estimated labels must have source evidence", str(ctx.exception))

    def test_c2_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "label_status": "verified",
            "cefr_level": "C2",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": True
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_03",
                "source_version": "1.0"
            }
        }
        self.validator.validate(metadata)

    def test_conflicting_labels(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "de",
            "classification_target": "entry",
            "label_status": "unverified",
            "cefr_level": "B1",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": True,
                "advanced": False
            }
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("Unverified status must have cefr_level as 'unknown'", str(ctx.exception))

    def test_wrong_language_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "InvalidLang123",
            "classification_target": "entry",
            "label_status": "unverified",
            "cefr_level": "unknown",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": False
            }
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("Schema validation failed", str(ctx.exception))

    def test_invented_source_identity(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "label_status": "verified",
            "cefr_level": "A2",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "   ",
                "source_version": "1.0"
            }
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("Source ID cannot be empty or whitespace", str(ctx.exception))

    def test_invalid_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "label_status": "unverified",
            "cefr_level": "Z9",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": False
            }
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("Schema validation failed", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
