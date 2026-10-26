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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Verified and estimated labels must have source evidence" in issue for issue in result["issues"]))

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Unverified status must have cefr_level as 'unknown'" in issue for issue in result["issues"]))

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["issues"], [])

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("CEFR level and coarse difficulty disagree" in issue for issue in result["issues"]))

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Schema validation failed" in issue for issue in result["issues"]))

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Source ID cannot be empty or whitespace" in issue for issue in result["issues"]))

    def test_verified_self_assertion_is_not_authority(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        result = ProficiencyValidator().validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Verified assignment lacks independently approved language/target/level evidence" in issue or "Language has no reviewed CEFR framework mapping" in issue for issue in result["issues"]))

    def test_wrong_language_with_valid_syntax_is_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "zz",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "unverified", "cefr_level": "unknown",
            "coarse_difficulty": {"beginner":False, "intermediate":False, "advanced":False}
        }
        result = self.validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("canonical registered" in issue for issue in result["issues"]))

    def test_no_automatic_japanese_cefr_equivalence(self):
        record = {
            "schema_version": "1.0.0", "language": "ja",
            "classification_target": "example", "target_id": "example.ja.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":True, "intermediate":False, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"TEST_SOURCE_02", "source_version":"1.0"}
        }
        result = self.validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("not registered" in issue for issue in result["issues"]))

    def test_wrong_coarse_level_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id":"COE-CEFR-2020", "source_version":"2020 Companion volume"}
        }
        result = self.validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("coarse difficulty" in issue for issue in result["issues"]))

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
        result = validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("A1-C2" in issue for issue in result["issues"]))

        record["label_status"] = "estimated"
        record["evaluation_method"] = "descriptor_guided_review"
        result2 = validator.validate(record)
        self.assertEqual(result2["status"], "REJECT")
        self.assertTrue(any("A1-C2" in issue for issue in result2["issues"]))

    def test_invented_estimated_source_rejected(self):
        record = {
            "schema_version": "1.0.0", "language": "es",
            "classification_target": "example", "target_id": "lex.demo",
            "label_status": "estimated", "cefr_level": "A1",
            "coarse_difficulty": {"beginner": True, "intermediate": False, "advanced": False},
            "evaluation_method": "descriptor_guided_review",
            "source_evidence": {"source_id": "TEST_SOURCE_02", "source_version": "2.0"}
        }
        result = self.validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("trusted catalog source" in issue or "independently approved evidence" in issue for issue in result["issues"]))

    def test_verified_assignment_cannot_cross_target(self):
        record = {
            "schema_version": "1.0.0", "language": "en",
            "classification_target": "entry", "target_id": "lex.other",
            "label_status": "verified", "cefr_level": "B2",
            "coarse_difficulty": {"beginner":False, "intermediate":True, "advanced":False},
            "evaluation_method": "published_content_assignment",
            "source_evidence": {"source_id":"TEST_SOURCE_01", "source_version":"1.0"}
        }
        result = self.validator.validate(record)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("independently approved" in issue for issue in result["issues"]))

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
        result = self.validator.validate(metadata)
        self.assertEqual(result["status"], "REJECT")
        self.assertTrue(any("Schema validation failed" in issue for issue in result["issues"]))

if __name__ == "__main__":
    unittest.main()
