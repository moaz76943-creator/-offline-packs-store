import unittest
from standards.proficiency.validator import ProficiencyValidator, ValidationError

class TestProficiencyMetadata(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator()

    def test_valid_a1_verified(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "verified",
            "level": "A1",
            "coarse_difficulty": "beginner",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        self.validator.validate(record)

    def test_valid_a2_estimated(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "estimated",
            "level": "A2",
            "coarse_difficulty": "beginner",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        self.validator.validate(record)

    def test_valid_b1_verified(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "verified",
            "level": "B1",
            "coarse_difficulty": "intermediate",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        self.validator.validate(record)

    def test_valid_b2_verified(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "verified",
            "level": "B2",
            "coarse_difficulty": "intermediate",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        self.validator.validate(record)

    def test_valid_c1_verified(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "verified",
            "level": "C1",
            "coarse_difficulty": "advanced",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        self.validator.validate(record)

    def test_valid_c2_estimated(self):
        record = {
            "schema_version": "1.0.0",
            "language": "fr",
            "classification_type": "entry-level",
            "status": "estimated",
            "level": "C2",
            "coarse_difficulty": "advanced",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "expert_review",
            "confidence": 0.85
        }
        self.validator.validate(record)

    def test_valid_unverified_unknown(self):
        record = {
            "schema_version": "1.0.0",
            "language": "ar",
            "classification_type": "example-level",
            "status": "unverified",
            "level": "unknown",
            "coarse_difficulty": "unknown"
        }
        self.validator.validate(record)

    def test_missing_source_for_verified(self):
        record = {
            "schema_version": "1.0.0",
            "language": "de",
            "classification_type": "entry-level",
            "status": "verified",
            "level": "B1",
            "coarse_difficulty": "intermediate"
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(record)
        self.assertIn("source_identity and evaluation_method are required", str(context.exception))

    def test_invented_source_identity(self):
        record = {
            "schema_version": "1.0.0",
            "language": "es",
            "classification_type": "example-level",
            "status": "verified",
            "level": "B2",
            "coarse_difficulty": "intermediate",
            "source_identity": "FAKE-SOURCE-999",
            "evaluation_method": "expert_review"
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(record)
        self.assertIn("Invented source identity", str(context.exception))

    def test_wrong_language_format(self):
        record = {
            "schema_version": "1.0.0",
            "language": "ENGLISH",
            "classification_type": "example-level",
            "status": "unverified",
            "level": "unknown",
            "coarse_difficulty": "unknown"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(record)

    def test_invalid_level(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "unverified",
            "level": "Z9",
            "coarse_difficulty": "unknown"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(record)

    def test_conflicting_labels(self):
        record = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_type": "example-level",
            "status": "verified",
            "level": "A1",
            "coarse_difficulty": "advanced",
            "source_identity": "COE-CEFR-2020",
            "evaluation_method": "descriptor_guided_review"
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(record)
        self.assertIn("Conflicting labels", str(context.exception))

if __name__ == '__main__':
    unittest.main()
