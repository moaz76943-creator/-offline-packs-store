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
    def run_gate(self, sources=None, output="CC0-1.0", derivative=True):
        return check_compatibility([ref(s) for s in sources] if sources is not None else [ref(self.source)],
                                   output, derivative, repo_root=self.tmp.name)
    def test_injected_approved_source_cannot_override_empty_canonical_ledger(self):
        save_ledger(self.tmp.name, {"schema_version": "1.0.0", "sources": []})
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")

    def test_injected_changed_version_cannot_override_canonical_record(self):
        save_ledger(self.tmp.name, self.ledger)
        self.source["dataset_version"] = "999.0"
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")

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
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
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


    def test_public_domain_sources(self):
        # Using two CC0 sources. Relicensing CC0 to PUBLIC-DOMAIN should fail according to earlier rule, but CC0 to CC0 is fine.
        # Wait, if source is actually PUBLIC-DOMAIN, we can relicense to PUBLIC-DOMAIN.
        self.source["license"]["id"] = "PUBLIC-DOMAIN"
        self.source["license"]["public_domain_proof"] = {"legal_basis": "Expired", "work_date": "1900", "jurisdiction": "US"}
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        self.ledger["sources"].append(source2)
        save_ledger(self.tmp.name, self.ledger)
        res = self.run_gate([self.source, source2], output="PUBLIC-DOMAIN")
        self.assertEqual(res["status"], "COMPATIBLE")

    def test_conflicting_share_alike_obligations(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        source2["license"]["id"] = "GFDL-1.3-only"
        self.ledger["sources"].append(source2)
        save_ledger(self.tmp.name, self.ledger)
        # Should conflict because len(copyleft) > 1
        res = self.run_gate([self.source, source2], output="CC-BY-SA-4.0", derivative=True)
        self.assertEqual(res["status"], "INCOMPATIBLE")
        self.assertIn("GFDL and CC BY-SA derivative conflict", res["reason"])

    def test_missing_attribution(self):
        # We test that attribution requirements are correctly exposed when present.
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        save_ledger(self.tmp.name, self.ledger)
        res = self.run_gate(output="CC-BY-SA-4.0")
        self.assertEqual(res["status"], "COMPATIBLE")
        # Should have attribution obligations
        self.assertIn("attribution", res["obligations"]["attribution"])

    def test_unknown_licenses(self):
        self.source["license"]["id"] = "UNKNOWN-LICENSE"
        save_ledger(self.tmp.name, self.ledger)
        # verified_sources relies on evaluate() which validates against LICENSES
        res = self.run_gate()
        self.assertEqual(res["status"], "REVIEW_REQUIRED")

if __name__ == "__main__":
    unittest.main()
