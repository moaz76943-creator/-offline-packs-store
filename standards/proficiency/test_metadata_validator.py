import unittest
from standards.proficiency.validator import ProficiencyValidator

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

    def assertAccept(self, result):
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

    def assertReject(self, result, expected_message):
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any(expected_message in issue for issue in result["issues"]), f"Expected issue with '{expected_message}', but got: {result['issues']}")

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertReject(self.validator.validate(metadata), "Verified and estimated labels must have source evidence")

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertReject(self.validator.validate(metadata), "Unverified status must have cefr_level as 'unknown'")

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertAccept(self.validator.validate(metadata))

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
        self.assertReject(self.validator.validate(metadata), "CEFR level and coarse difficulty disagree")

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
        self.assertReject(self.validator.validate(metadata), "Schema validation failed")

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
        self.assertReject(self.validator.validate(metadata), "Source ID cannot be empty or whitespace")

    def test_verified_self_assertion_is_not_authority(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        self.assertReject(ProficiencyValidator().validate(record), "Language has no reviewed CEFR framework mapping")

    def test_wrong_language_with_valid_syntax_is_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "zz",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "unverified", "cefr_level": "unknown",
            "coarse_difficulty": {"beginner":False, "intermediate":False, "advanced":False}
        }
        self.assertReject(self.validator.validate(record), "canonical registered")

    def test_no_automatic_japanese_cefr_equivalence(self):
        record = {
            "schema_version": "1.0.0", "language": "ja",
            "classification_target": "example", "target_id": "example.ja.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":True, "intermediate":False, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"TEST_SOURCE_02", "source_version":"1.0"}
        }
        self.assertReject(self.validator.validate(record), "not registered")

    def test_wrong_coarse_level_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"COE-CEFR-2020", "source_version":"2020 Companion volume"}
        }
        self.assertReject(self.validator.validate(record), "coarse difficulty")

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
        self.assertReject(validator.validate(record), "A1-C2")
        record["label_status"] = "estimated"
        record["evaluation_method"] = "descriptor_guided_review"
        self.assertReject(validator.validate(record), "A1-C2")

    def test_invented_estimated_source_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "es",
            "classification_target": "example", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner": True, "intermediate": False, "advanced": False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id": "TEST_SOURCE_02", "source_version": "2.0"}
        }
        self.assertReject(self.validator.validate(record), "trusted catalog source")

    def test_verified_assignment_cannot_cross_target(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.other",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        self.assertReject(self.validator.validate(record), "independently approved")

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
        self.assertReject(self.validator.validate(metadata), "Schema validation failed")

if __name__ == "__main__":
    unittest.main()
