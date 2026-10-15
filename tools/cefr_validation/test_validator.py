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

    def get_valid_attested_evidence(self):
        return [{
            "source_id": "COE-CEFR-2020", # Note: need a content_classification source, actually COE is framework. Let's use a mocked or different source if needed. But in engine.py:
            # if source["scope"] != "content_classification"
            # wait, let me look at sources in frameworks.json
            "source_id": "LOCAL-BANDS-1", # Wait, LOCAL-BANDS-1 has scope local_taxonomy
            # actually we don't need it to pass engine validate_record for the "certified corpora" test if we bypass engine or just use an estimated one.
            # wait! The certified CEFR corpora check happens AFTER engine.validate_record() !
            # BUT it checks: `if status == "source_attested" and "CEFR" not in lang_prof.get("framework_ids", []):`
            # To reach this check, it must PASS `self.catalog.validate_record(record)`.
            "source_version": "1.0.0",
            "source_url": "https://example.com",
            "locator": "page 10",
            "method": "published_content_assignment",
            "reviewer_id": "reviewer-1",
            "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
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
        # To avoid the engine validatior failing, we can mock the validate_record or dynamically inject a source.
        # Actually since we have full access, let's inject a dummy source into the catalog.

        # When language lacks certified CEFR corpora
        unsupported_lang = None
        for lang_id, lang_data in self.validator.supported_languages.items():
            frameworks = lang_data.get("proficiency", {}).get("framework_ids", [])
            if "CEFR" not in frameworks:
                unsupported_lang = lang_id
                break

        if not unsupported_lang:
            unsupported_lang = "zza"

        # Dynamically inject dummy source into catalog to pass validate_record
        dummy_source_id = "DUMMY-CORPUS"
        self.validator.catalog.sources[dummy_source_id] = {
            "source_id": dummy_source_id,
            "publisher": "Dummy",
            "version": "1.0",
            "url": "https://dummy.com",
            "scope": "content_classification",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        }

        evidence = [{
            "source_id": dummy_source_id,
            "source_version": "1.0",
            "source_url": "https://dummy.com",
            "locator": "page 10",
            "method": "published_content_assignment",
            "reviewer_id": "reviewer-1"
        }]

        rec = self.create_record("word-1", unsupported_lang, "source_attested", "CEFR", "A1", evidence)
        accepted, rejected = self.validator.process_dataset([rec])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("lacks certified CEFR corpora", rejected[0]["reason"])

if __name__ == '__main__':
    unittest.main()
