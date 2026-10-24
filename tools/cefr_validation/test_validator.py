import unittest
from pathlib import Path

from tools.cefr_validation.validator import CEFRValidator

class CEFRValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = CEFRValidator()

    def create_record(self, record_id, lang, status, framework=None, level=None, evidence=None):
        rec = {
            "record_id": record_id,
            "language": lang,
            "classification_status": status,
            "proficiency_framework_id": framework,
            "proficiency_level_id": level,
            "skills": {
                "reading": {"mode": "receptive", "status": "unknown"},
                "writing": {"mode": "productive", "status": "unknown"},
                "listening": {"mode": "receptive", "status": "unknown"},
                "speaking": {"mode": "productive", "status": "unknown"}
            },
            "complexity": {
                "word_difficulty": "unknown",
                "sentence_complexity": "unknown",
                "grammar_complexity": "unknown",
                "reading_competence": "unknown"
            },
            "script_literacy": {
                "script_codes": ["Latn"],
                "status": "not_required"
            },
            "topic_domains": [],
            "prerequisites": [],
            "evidence": evidence or []
        }
        return rec

    def get_valid_evidence(self):
        return [{
            "source_id": "COE-CEFR-2020",
            "source_version": "2020 Companion volume",
            "source_url": "https://www.coe.int/en/web/common-european-framework-reference-languages/introduction-and-context",
            "locator": "page 10",
            "method": "descriptor_guided_review",
            "reviewer_id": "reviewer-1"
        }]

    def test_all_six_levels(self):
        levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
        coarse_maps = ["beginner", "beginner", "intermediate", "intermediate", "advanced", "advanced"]

        for idx, (level, coarse) in enumerate(zip(levels, coarse_maps)):
            rec = self.create_record(f"word-{idx}", "en", "estimated", "CEFR", level, self.get_valid_evidence())
            accepted, rejected = self.validator.process_dataset([rec])
            self.assertEqual(len(rejected), 0)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0]["_resolution"], "inferred")
            self.assertEqual(accepted[0]["_coarse_difficulty"], coarse)

    def test_missing_lexical_id(self):
        rec = self.create_record("", "en", "unknown")
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Missing lexical entry", rejected[0]["reason"])

    def test_mismatched_language_id(self):
        rec = self.create_record("word-1", "xx", "unknown") # xx is not in registry
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Unsupported language ID", rejected[0]["reason"])

    def test_unknown_case(self):
        rec = self.create_record("word-1", "en", "unknown")
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(rejected), 0)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["_resolution"], "unknown")

    def test_invalid_source_and_expired_evidence(self):
        evidence = self.get_valid_evidence()
        evidence[0]["source_id"] = "FAKE-SOURCE"
        rec = self.create_record("word-1", "en", "estimated", "CEFR", "A1", evidence)
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Validation error", rejected[0]["reason"])

        evidence = self.get_valid_evidence()
        evidence[0]["source_version"] = "outdated version"
        rec = self.create_record("word-2", "en", "estimated", "CEFR", "A1", evidence)
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Validation error", rejected[0]["reason"])

    def test_contradictory_classifications(self):
        # A1 and C2 for the same lexical entry should conflict
        rec1 = self.create_record("word-conflict", "en", "estimated", "CEFR", "A1", self.get_valid_evidence())
        rec2 = self.create_record("word-conflict", "en", "estimated", "CEFR", "C2", self.get_valid_evidence())

        # New validator instance for clear history
        validator = CEFRValidator()
        accepted, rejected = validator.process_dataset([rec1, rec2])
        self.assertEqual(len(accepted), 1) # First one goes through
        self.assertEqual(len(rejected), 1) # Second one is rejected due to conflict
        self.assertIn("Substantial source conflict", rejected[0]["reason"])

        # In the rejection flow we keep source dataset immutable so the input is wrapped.
        # But for conflicts we actually did set `_resolution` in the code, let's just check the wrapper reason here
        # or we can verify that the rejected item has "conflicting" somewhere.
        # Since original_record is returned we won't see _resolution on it, but the reason has it.


    def test_preserves_independent_sources_without_conflict(self):
        # A1 and A2 for the same word is not a "substantial" conflict
        rec1 = self.create_record("word-no-conflict", "en", "estimated", "CEFR", "A1", self.get_valid_evidence())
        rec2 = self.create_record("word-no-conflict", "en", "estimated", "CEFR", "A2", self.get_valid_evidence())

        validator = CEFRValidator()
        accepted, rejected = validator.process_dataset([rec1, rec2])
        self.assertEqual(len(rejected), 0)
        self.assertEqual(len(accepted), 2)

    def test_unsupported_framework(self):
        rec = self.create_record("word-1", "en", "estimated", "PEDAGOGICAL_BANDS", "beginner", self.get_valid_evidence())
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("Only CEFR is supported by this gate", rejected[0]["reason"])

    def test_certified_cefr_corpora(self):
        # We need a source_attested valid record. We bypass static framework limits
        # by manually adding a valid source to the catalog sources for testing.
        self.validator.catalog.sources["TEST-CORPUS"] = {
            "version": "1.0",
            "url": "https://test.com",
            "scope": "content_classification",
            "sha256": "abcdef"
        }

        evidence = [{
            "source_id": "TEST-CORPUS",
            "source_version": "1.0",
            "source_url": "https://test.com",
            "locator": "id-1",
            "method": "published_content_assignment",
            "reviewer_id": "auto"
        }]

        # 'en' supports CEFR corpora
        rec_en = self.create_record("word-en", "en", "source_attested", "CEFR", "B1", evidence)

        # 'zh' does not support CEFR corpora in the registry
        rec_zh = self.create_record("word-zh", "zh", "source_attested", "CEFR", "B1", evidence)

        accepted, rejected = self.validator.process_dataset([rec_en, rec_zh])

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(accepted[0]["language"], "en")
        self.assertIn("lacks certified CEFR corpora", rejected[0]["reason"])

if __name__ == '__main__':
    unittest.main()
