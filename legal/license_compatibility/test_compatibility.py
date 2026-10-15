import copy
import tempfile
import unittest
from legal.license_compatibility.compatibility import check_compatibility
from tools.contribution_gate.test_fixture import fixture, save_ledger, ref

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger, self.source = fixture(self.tmp.name)
    def run_gate(self, source_refs=None, output="CC0-1.0", derivative=True):
        refs = source_refs if source_refs is not None else [ref(self.source)]
        return check_compatibility(refs, output, derivative, repo_root=self.tmp.name)
    def test_injected_approved_source_cannot_override_empty_canonical_ledger(self):
        save_ledger(self.tmp.name, {"schema_version": "1.0.0", "sources": []})
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")

    def test_injected_stale_reference_rejected(self):
        save_ledger(self.tmp.name, self.ledger)
        bad_ref = ref(self.source)
        bad_ref["dataset_version"] = "99.9"
        self.assertEqual(self.run_gate([bad_ref])["status"], "REVIEW_REQUIRED")

    def test_valid_documented_fixture_is_not_legal_approval(self):
        r = self.run_gate()
        self.assertEqual(r["status"], "COMPATIBLE", r)
        self.assertFalse(r["publication_approved"])
    def test_missing_source_rejected(self):
        self.assertEqual(self.run_gate([])["status"], "REVIEW_REQUIRED")
    def test_unverified_rights_fail_closed(self):
        self.source["status"] = "UNVERIFIED_RIGHTS"
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
    def test_missing_source_license_proof_blocks(self):
        self.source["license"]["evidence_path"] = "evidence/not-there"
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
    def test_forged_original_hash_blocks(self):
        self.source["retrieval"]["sha256"] = "1" * 64
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate([ref(self.source)])["status"], "REVIEW_REQUIRED")
    def test_cc0_cannot_be_relabelled_public_domain(self):
        self.assertEqual(self.run_gate(output="PUBLIC-DOMAIN")["status"], "INCOMPATIBLE")
    def test_unknown_output_license_blocks(self):
        self.assertEqual(self.run_gate(output="OFL-1.1")["status"], "REVIEW_REQUIRED")
    def test_copyleft_relicense_conflict(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate(output="CC0-1.0")["status"], "INCOMPATIBLE")
    def test_aggregation_without_collection_rights_stays_review(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate(output="CC-BY-SA-4.0", derivative=False)["status"],
                         "REVIEW_REQUIRED")

    def test_public_domain_sources_compatible(self):
        self.source["license"]["id"] = "PUBLIC-DOMAIN"
        self.source["license"]["public_domain_proof"] = {"jurisdiction": "US", "legal_basis": "Expired", "work_date": "1900"}
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        self.ledger["sources"].append(source2)
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate([ref(self.source), ref(source2)], output="PUBLIC-DOMAIN")["status"], "COMPATIBLE")

    def test_public_domain_with_cc0_incompatible_as_public_domain_output(self):
        self.source["license"]["id"] = "PUBLIC-DOMAIN"
        self.source["license"]["public_domain_proof"] = {"jurisdiction": "US", "legal_basis": "Expired", "work_date": "1900"}
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        source2["license"]["id"] = "CC0-1.0"
        del source2["license"]["public_domain_proof"]
        self.ledger["sources"].append(source2)
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate([ref(self.source), ref(source2)], output="PUBLIC-DOMAIN")["status"], "INCOMPATIBLE")

    def test_share_alike_conflicts(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        source2["license"]["id"] = "GFDL-1.3-only"
        self.ledger["sources"].append(source2)
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate([ref(self.source), ref(source2)], output="CC-BY-SA-4.0")["status"], "INCOMPATIBLE")

    def test_unknown_source_ref_fails_closed(self):
        bad_ref = {"source_id": "unknown-source", "dataset_version": "1.0", "artifact_sha256": "1" * 64}
        self.assertEqual(self.run_gate([bad_ref])["status"], "REVIEW_REQUIRED")

    def test_missing_attribution_is_implicit_via_missing_source(self):
        # In this implementation, a missing attribution or source in the ledger causes REVIEW_REQUIRED
        bad_ref = {"source_id": "missing-attribution", "dataset_version": "1.0", "artifact_sha256": "1" * 64}
        self.assertEqual(self.run_gate([bad_ref])["status"], "REVIEW_REQUIRED")

    def test_unknown_license_in_ledger_fails_ledger_validation(self):
        self.source["license"]["id"] = "UNKNOWN-LICENSE"
        save_ledger(self.tmp.name, self.ledger)
        # Assuming evaluate fails unknown licenses, or check_compatibility throws REVIEW_REQUIRED
        self.assertEqual(self.run_gate([ref(self.source)])["status"], "REVIEW_REQUIRED")

if __name__ == "__main__":
    unittest.main()
