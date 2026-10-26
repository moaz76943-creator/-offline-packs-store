import unittest
from standards.proficiency.validator import ProficiencyValidator, ProficiencyValidationError

class TestProficiencyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = ProficiencyValidator(
            trusted_framework_mappings={"en":"CEFR"},
            approved_assignments={
                "TEST_SOURCE_01": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"B2", "review_status":"approved"},
                                "TEST_SOURCE_A1": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"A1", "review_status":"approved"},
                "TEST_SOURCE_A2": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"A2", "review_status":"approved"},
                "TEST_SOURCE_B1": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"B1", "review_status":"approved"},
                "TEST_SOURCE_C1": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"C1", "review_status":"approved"},
                "TEST_SOURCE_03": {"language":"en", "target_id":"lex.demo", "classification_target":"entry",
                                   "source_version":"1.0", "cefr_level":"C2", "review_status":"approved"}
            })

    def test_valid_verified_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
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
            "target_id": "lex.demo",
            "label_status": "estimated",
            "cefr_level": "A1",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            },
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {
                "source_id": "COE-CEFR-2020",
                "source_version": "2020 Companion volume"
            }
        }
        self.validator.validate(metadata)

    def test_valid_unverified_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "fr",
            "classification_target": "entry",
            "target_id": "lex.demo",
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
            "target_id": "lex.demo",
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
            "target_id": "lex.demo",
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
            "target_id": "lex.demo",
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

    def test_a1_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
            "label_status": "verified",
            "cefr_level": "A1",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_A1",
                "source_version": "1.0"
            }
        }
        self.validator.validate(metadata)

    def test_a2_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
            "label_status": "verified",
            "cefr_level": "A2",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_A2",
                "source_version": "1.0"
            }
        }
        self.validator.validate(metadata)

    def test_b1_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
            "label_status": "verified",
            "cefr_level": "B1",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": True,
                "advanced": False
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_B1",
                "source_version": "1.0"
            }
        }
        self.validator.validate(metadata)

    def test_c1_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
            "label_status": "verified",
            "cefr_level": "C1",
            "coarse_difficulty": {
                "beginner": False,
                "intermediate": False,
                "advanced": True
            },
            "evaluation_method": "published_content_assignment",
            "source_evidence": {
                "source_id": "TEST_SOURCE_C1",
                "source_version": "1.0"
            }
        }
        self.validator.validate(metadata)

    def test_unknown_difficulty(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
            "label_status": "unverified",
            "cefr_level": "unknown",
            "coarse_difficulty": {
                "beginner": True,
                "intermediate": False,
                "advanced": False
            }
        }
        with self.assertRaises(ProficiencyValidationError) as ctx:
            self.validator.validate(metadata)
        self.assertIn("CEFR level and coarse difficulty disagree", str(ctx.exception))

    def test_wrong_language_metadata(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "InvalidLang123",
            "classification_target": "entry",
            "target_id": "lex.demo",
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
            "target_id": "lex.demo",
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

    def test_verified_self_assertion_is_not_authority(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        with self.assertRaises(ProficiencyValidationError):
            ProficiencyValidator().validate(record)

    def test_wrong_language_with_valid_syntax_is_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "zz",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "unverified", "cefr_level": "unknown",
            "coarse_difficulty": {"beginner":False, "intermediate":False, "advanced":False}
        }
        with self.assertRaisesRegex(ProficiencyValidationError, "canonical registered"):
            self.validator.validate(record)

    def test_no_automatic_japanese_cefr_equivalence(self):
        record = {
            "schema_version": "1.0.0", "language": "ja",
            "classification_target": "example", "target_id": "example.ja.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":True, "intermediate":False, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"TEST_SOURCE_02", "source_version":"1.0"}
        }
        with self.assertRaisesRegex(ProficiencyValidationError, "not registered"):
            self.validator.validate(record)

    def test_wrong_coarse_level_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"COE-CEFR-2020", "source_version":"2020 Companion volume"}
        }
        with self.assertRaisesRegex(ProficiencyValidationError, "coarse difficulty"):
            self.validator.validate(record)

    def test_classified_unknown_level_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "verified", "cefr_level": "unknown",
            "coarse_difficulty": {"beginner": False, "intermediate": False, "advanced": False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id": "TEST_SOURCE_01", "source_version": "1.0"}
        }
        unknown_proof = dict(self.validator.approved_assignments["TEST_SOURCE_01"], cefr_level="unknown")
        validator = ProficiencyValidator(
            trusted_framework_mappings={"en": "CEFR"},
            approved_assignments={"TEST_SOURCE_01": unknown_proof})
        with self.assertRaisesRegex(ProficiencyValidationError, "A1-C2"):
            validator.validate(record)
        record["label_status"] = "estimated"
        record["evaluation_method"] = "descriptor_guided_review"
        with self.assertRaisesRegex(ProficiencyValidationError, "A1-C2"):
            validator.validate(record)

    def test_invented_estimated_source_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "es",
            "classification_target": "example", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner": True, "intermediate": False, "advanced": False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id": "TEST_SOURCE_02", "source_version": "2.0"}
        }
        with self.assertRaisesRegex(ProficiencyValidationError, "trusted catalog source"):
            self.validator.validate(record)

    def test_verified_assignment_cannot_cross_target(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.other",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        with self.assertRaisesRegex(ProficiencyValidationError, "independently approved"):
            self.validator.validate(record)

    def test_invalid_level(self):
        metadata = {
            "schema_version": "1.0.0",
            "language": "en",
            "classification_target": "entry",
            "target_id": "lex.demo",
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
