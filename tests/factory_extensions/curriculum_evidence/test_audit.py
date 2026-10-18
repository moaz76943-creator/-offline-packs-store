import copy
import hashlib
from pathlib import Path
import unittest

from tools.factory_extensions.curriculum_evidence.audit import AuditError, audit


EVIDENCE_PATH = "tests/factory_extensions/curriculum_evidence/test_audit.py"
EVIDENCE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def fixture():
    languages = [{"id": "de", "scripts": ["Latn"], "proficiency": {"framework_ids": ["CEFR"]}},
                 {"id": "ko", "scripts": ["Kore"], "proficiency": {"framework_ids": ["TOPIK"]}}]
    frameworks = {"frameworks": [{"proficiency_framework_id": "CEFR", "version": "2020-companion", "levels": ["A1", "A2"]}], "sources": []}
    source = {"source_id": "approved", "kind": "dictionary", "dataset_version": "v1",
              "status": "APPROVED_FOR_REDISTRIBUTION", "origin_url": "https://example.org/origin",
              "publisher": "Fixture Publisher", "alterations": ["none"],
              "retrieval": {"sha256": EVIDENCE_HASH, "artifact_path": EVIDENCE_PATH,
                            "url": "https://example.org/artifact", "identity": "fixed-test-only", "date": "2026-10-13"},
              "license": {"id": "CC0-1.0", "evidence_path": EVIDENCE_PATH,
                          "evidence_sha256": EVIDENCE_HASH, "evidence_url": "https://example.org/licenses/dataset"},
              "review": {"reviewer": "editor", "decision_url": "https://example.org/review"}}
    return languages, frameworks, {"sources": [source]}


def item(rid="r1", status="source_attested", kind="vocabulary"):
    return {"record_id": rid, "language": "de", "kind": kind,
            "source": {"source_id": "approved", "dataset_version": "v1", "artifact_sha256": EVIDENCE_HASH},
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
        b["prerequisite_evidence"] = [{"record_id": "r1", "source_id": "approved", "source_version": "v1", "locator": "relation-1", "reviewer_id": "editor"}]
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

    def test_large_invalid_dependency_chain_fails_closed(self):
        rows = [item(f"r{i}") for i in range(1200)]
        for i in range(1, 1200):
            rows[i]["prerequisites"] = [f"r{i-1}"]
        rows[0]["prerequisites"] = ["missing"]
        report = self.run_audit(rows)
        self.assertEqual(report["rejected"], len(rows))
        self.assertEqual(report["languages"]["de"]["verified_total"], 0)

    def test_unknown_and_unassessed_remain_separate(self):
        result = self.run_audit([item("r1", status="unknown"), item("r2", status="unassessed")])
        self.assertEqual(result["languages"]["de"]["unknown_total"], 1)
        self.assertEqual(result["languages"]["de"]["unassessed_total"], 1)

    def test_approval_requires_actual_source_bytes(self):
        languages, standards, ledger = fixture()
        ledger["sources"][0]["retrieval"]["sha256"] = "b" * 64
        fake = item()
        fake["source"]["artifact_sha256"] = "b" * 64
        result = audit(languages, standards, ledger, [fake], validator)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)
        self.assertEqual(result["rejection_reasons"].get("source_not_approved"), 1)

    def test_bad_license_evidence_blocks_claim(self):
        languages, standards, ledger = fixture()
        ledger["sources"][0]["license"]["evidence_sha256"] = "b" * 64
        result = audit(languages, standards, ledger, [item()], validator)
        self.assertEqual(result["rejection_reasons"].get("source_not_approved"), 1)

    def test_attested_prerequisite_edge_requires_its_own_proof(self):
        child = item("r2")
        child["prerequisites"] = ["r1"]
        result = self.run_audit([item(), child])
        self.assertEqual(result["languages"]["de"]["verified_total"], 1)
        self.assertEqual(result["rejected"], 1)

    def test_edge_proof_must_be_exact_parent(self):
        child = item("r2")
        child["prerequisites"] = ["r1"]
        child["prerequisite_evidence"] = [{"record_id": "no-such-parent", "source_id": "approved",
                                           "source_version": "v1", "locator": "chapter-1", "reviewer_id": "editor"}]
        result = self.run_audit([item(), child])
        self.assertEqual(result["languages"]["de"]["verified_total"], 1)
        self.assertEqual(result["rejected"], 1)

    def test_forged_retrieval_date_is_not_approval(self):
        languages, standards, ledger = fixture()
        ledger["sources"][0]["retrieval"]["date"] = "not-an-iso-date"
        result = audit(languages, standards, ledger, [item()], validator)
        self.assertEqual(result["rejection_reasons"].get("source_not_approved"), 1)

    def test_symlink_escape_not_accepted_as_source(self):
        import tempfile
        from tools.factory_extensions.curriculum_evidence.audit import _file_digest
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "escape"
            link.symlink_to(Path(__file__).resolve())
            self.assertIsNone(_file_digest(Path(directory), "escape", limit=10_000_000))

    def test_framework_collision_is_rejected_per_record(self):
        languages, standards, ledger = fixture()
        languages[0]["proficiency"]["framework_ids"].append("ALT")
        standards["frameworks"].append({"proficiency_framework_id": "ALT", "version": "1.0", "levels": ["1"]})
        other = item("r2")
        other["proficiency"]["proficiency_framework_id"] = "ALT"
        other["proficiency"]["proficiency_level_id"] = "1"
        result = audit(languages, standards, ledger, [item(), other], validator)
        self.assertEqual(result["languages"]["de"]["verified_total"], 0)
        self.assertEqual(result["rejected"], 2)

    def test_approved_thresholds_are_noncertifying(self):
        source = {"source_id": "approved", "dataset_version": "v1", "artifact_sha256": EVIDENCE_HASH}
        result = self.run_audit([item()], criteria={"source": source, "minimums": {"vocabulary": 1, "grammar": 0, "example": 0, "exercise": 0}, "reviewer": "editor"})
        stage = result["languages"]["de"]["curricula"]["manual-de"]["levels"]["A1"]
        self.assertEqual(stage["sufficiency"], "meets_editorial_targets_not_accreditation")

if __name__ == "__main__":
    unittest.main()
