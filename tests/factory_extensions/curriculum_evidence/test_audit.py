import copy
import unittest

from tools.factory_extensions.curriculum_evidence.audit import AuditError, audit


def fixture():
    languages = [{"id": "de", "scripts": ["Latn"], "proficiency": {"framework_ids": ["CEFR"]}},
                 {"id": "ko", "scripts": ["Kore"], "proficiency": {"framework_ids": ["TOPIK"]}}]
    frameworks = {"frameworks": [{"proficiency_framework_id": "CEFR", "version": "2020-companion", "levels": ["A1", "A2"]}], "sources": []}
    source = {"source_id": "approved", "dataset_version": "v1", "status": "APPROVED_FOR_REDISTRIBUTION",
              "retrieval": {"sha256": "a" * 64}, "license": {"id": "CC0-1.0"},
              "review": {"reviewer": "editor", "decision_url": "https://example.org/review"}}
    return languages, frameworks, {"sources": [source]}


def item(rid="r1", status="source_attested", kind="vocabulary"):
    return {"record_id": rid, "language": "de", "kind": kind,
            "source": {"source_id": "approved", "dataset_version": "v1", "artifact_sha256": "a" * 64},
            "proficiency": {"record_id": rid, "language": "de", "classification_status": status,
                            "proficiency_framework_id": "CEFR" if status in ("source_attested", "estimated") else None,
                            "proficiency_level_id": "A1" if status in ("source_attested", "estimated") else None,
                            "evidence": [{"source_id": "approved", "source_version": "v1", "locator": rid}] if status == "source_attested" else []},
            "curriculum": {"id": "manual-de", "source_id": "approved", "source_version": "v1", "locator": rid},
            "prerequisites": [], "taxonomy": []}


def validator(record):
    if record["classification_status"] == "source_attested" and not record["evidence"]:
        raise ValueError("missing attestation")


class CurriculumAuditTest(unittest.TestCase):
    def run_audit(self, rows, **kwargs):
        return audit(*fixture(), rows, validator, **kwargs)

    def test_100_language_shape_is_registry_driven(self):
        result = self.run_audit([])
        self.assertEqual(len(result["languages"]), 2)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)
        self.assertEqual(result["languages"]["ko"]["framework_gaps"], ["TOPIK"])
        self.assertEqual(result["admission_status"], "NO_APPROVED_CLASSIFICATIONS")

    def test_verified_separate_kinds_and_no_thresholds(self):
        a = self.run_audit([item(kind="vocabulary"), item("r2", kind="example")])
        stage = a["languages"]["de"]["curricula"]["manual-de"]["levels"]["A1"]
        self.assertEqual(stage["verified_counts"], {"vocabulary": 1, "grammar": 0, "example": 1, "exercise": 0})
        self.assertEqual(stage["sufficiency"], "unassessed_no_approved_targets")

    def test_estimates_never_count_as_verified(self):
        result = self.run_audit([item(status="estimated")])
        self.assertEqual(result["accepted_metadata"], 1)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_no_frequency_to_cefr_inference(self):
        row = item(status="unknown")
        row["frequency_rank"] = 1
        result = self.run_audit([row])
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_bad_legal_evidence_is_rejected(self):
        row = item()
        row["source"]["artifact_sha256"] = "b" * 64
        result = self.run_audit([row])
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_jlpt_not_automatically_cefr(self):
        row = item()
        row["proficiency"]["proficiency_framework_id"] = "JLPT"
        row["proficiency"]["proficiency_level_id"] = "N5"
        result = self.run_audit([row])
        self.assertEqual(result["rejected"], 1)

    def test_cross_curriculum_prerequisite_blocked(self):
        a, b = item(), item("r2")
        b["curriculum"]["id"] = "other"
        b["prerequisites"] = ["r1"]
        self.assertEqual(self.run_audit([a, b])["rejected"], 2)

    def test_cycle_is_reported_not_published(self):
        a, b = item(), item("r2")
        a["prerequisites"] = ["r2"]
        b["prerequisites"] = ["r1"]
        result = self.run_audit([a, b])
        self.assertEqual(result["rejected"], 2)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_taxonomy_requires_attested_source(self):
        row = item()
        row["taxonomy"] = [{"kind": "situation", "value": "travel"}]
        self.assertEqual(self.run_audit([row])["rejected"], 1)

    def test_rejects_claims_of_learner_assessment(self):
        row = item()
        row["kind"] = "learner_assessment"
        self.assertEqual(self.run_audit([row])["rejected"], 1)

    def test_thresholds_require_approval(self):
        criteria = {"source": {"source_id": "unknown"}, "minimums": {"vocabulary": 1}}
        with self.assertRaises(AuditError):
            self.run_audit([], criteria=criteria)

    def test_attested_skill_material_is_not_an_assessment(self):
        row = item()
        row["skill_material"] = [{"skill": "reading", "source_id": "approved", "source_version": "v1",
                                  "locator": "chapter-2", "reviewer_id": "editor"}]
        result = self.run_audit([row])
        stage = result["languages"]["de"]["curricula"]["manual-de"]["levels"]["A1"]
        self.assertEqual(stage["skill_material_counts"], {"reading": 1, "listening": 0, "writing": 0, "speaking": 0})

    def test_duplicate_identity_invalidates_both(self):
        result = self.run_audit([item(), item()])
        self.assertEqual(result["rejected"], 2)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_duplicate_invalidates_dependent(self):
        dependent = item("r2")
        dependent["prerequisites"] = ["r1"]
        result = self.run_audit([item(), dependent, item()])
        self.assertEqual(result["rejected"], 3)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)

    def test_100_distinct_registered_languages(self):
        langs, frameworks, ledger = fixture()
        langs = [{"id": f"x{i}", "scripts": ["Latn"], "proficiency": {"framework_ids": ["CEFR"]}} for i in range(100)]
        receipt = audit(langs, frameworks, ledger, [], validator)
        self.assertEqual(len(receipt["languages"]), 100)
        self.assertEqual(sum(x["verified_total"] for x in receipt["languages"].values()), 0)

    def test_approved_thresholds_are_noncertifying(self):
        source = {"source_id": "approved", "dataset_version": "v1", "artifact_sha256": "a" * 64}
        result = self.run_audit([item()], criteria={"source": source, "minimums": {"vocabulary": 1, "grammar": 0, "example": 0, "exercise": 0}, "reviewer": "editor"})
        stage = result["languages"]["de"]["curricula"]["manual-de"]["levels"]["A1"]
        self.assertEqual(stage["sufficiency"], "meets_editorial_targets_not_accreditation")

if __name__ == "__main__":
    unittest.main()
