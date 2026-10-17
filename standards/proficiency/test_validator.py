import unittest
from standards.proficiency.validator import ProficiencyValidator, ValidationError

class TestProficiencyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator()

    def test_valid_a1_beginner(self):
        instance = {
            "level": "A1",
            "coarse_difficulty": "beginner",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_valid_a2_beginner(self):
        instance = {
            "level": "A2",
            "coarse_difficulty": "beginner",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_valid_c2_advanced(self):
        instance = {
            "level": "C2",
            "coarse_difficulty": "advanced",
            "status": "unverified",
            "classification_type": "example-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_valid_b1_intermediate(self):
        instance = {
            "level": "B1",
            "coarse_difficulty": "intermediate",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_valid_b2_intermediate(self):
        instance = {
            "level": "B2",
            "coarse_difficulty": "intermediate",
            "status": "unverified",
            "classification_type": "example-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_valid_c1_advanced(self):
        instance = {
            "level": "C1",
            "coarse_difficulty": "advanced",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_invalid_level(self):
        instance = {
            "level": "D1",
            "coarse_difficulty": "beginner",
            "status": "unverified",
            "classification_type": "entry-level"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(instance)

    def test_invalid_coarse_difficulty(self):
        instance = {
            "level": "unknown",
            "coarse_difficulty": "easy",
            "status": "unverified",
            "classification_type": "entry-level"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(instance)

    def test_invalid_source_identity(self):
        instance = {
            "level": "A1",
            "coarse_difficulty": "beginner",
            "status": "unverified",
            "classification_type": "entry-level",
            "source_identity": "FAKE-SOURCE-ID"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(instance)

    def test_valid_source_identity(self):
        instance = {
            "level": "B1",
            "coarse_difficulty": "intermediate",
            "status": "unverified",
            "classification_type": "entry-level",
            "source_identity": "COE-CEFR-2020"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_conflicting_difficulty_a1_advanced(self):
        instance = {
            "level": "A1",
            "coarse_difficulty": "advanced",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(instance)
        self.assertIn("Conflicting difficulty", str(context.exception))

    def test_conflicting_difficulty_b2_beginner(self):
        instance = {
            "level": "B2",
            "coarse_difficulty": "beginner",
            "status": "estimated",
            "classification_type": "entry-level"
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(instance)
        self.assertIn("Conflicting difficulty", str(context.exception))

    def test_cefr_verified_without_local_evidence(self):
        instance = {
            "level": "C1",
            "coarse_difficulty": "advanced",
            "status": "verified",
            "classification_type": "entry-level",
            "evidence": {
                "local_evidence": False
            }
        }
        with self.assertRaises(ValidationError) as context:
            self.validator.validate(instance)
        self.assertIn("suitable local evidence", str(context.exception))

    def test_cefr_verified_with_local_evidence(self):
        instance = {
            "level": "C1",
            "coarse_difficulty": "advanced",
            "status": "verified",
            "classification_type": "entry-level",
            "evidence": {
                "local_evidence": True,
                "description": "Passed local C1 test"
            }
        }
        self.assertTrue(self.validator.validate(instance))

    def test_unknown_level_valid(self):
        instance = {
            "level": "unknown",
            "coarse_difficulty": "unknown",
            "status": "unverified",
            "classification_type": "entry-level"
        }
        self.assertTrue(self.validator.validate(instance))

    def test_wrong_language_metadata(self):
        instance = {
            "level": "A1",
            "coarse_difficulty": "beginner",
            "status": "unverified",
            "classification_type": "entry-level",
            "language": "invalid-lang-format!!!"
        }
        with self.assertRaises(ValidationError):
            self.validator.validate(instance)

if __name__ == '__main__':
    unittest.main()
