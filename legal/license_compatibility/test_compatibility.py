import copy
import tempfile
import unittest
from legal.license_compatibility.compatibility import check_compatibility
from tools.contribution_gate.test_fixture import fixture

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger, self.source = fixture(self.tmp.name)
    def run_gate(self, sources=None, output="CC0-1.0", derivative=True):
        return check_compatibility(sources if sources is not None else [self.source],
                                   output, derivative, repo_root=self.tmp.name)
    def test_valid_documented_fixture_is_not_legal_approval(self):
        r = self.run_gate()
        self.assertEqual(r["status"], "COMPATIBLE", r)
        self.assertFalse(r["publication_approved"])
    def test_missing_source_rejected(self):
        self.assertEqual(self.run_gate([])["status"], "REVIEW_REQUIRED")
    def test_unverified_rights_fail_closed(self):
        self.source["status"] = "UNVERIFIED_RIGHTS"
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
    def test_missing_source_license_proof_blocks(self):
        self.source["license"]["evidence_path"] = "evidence/not-there"
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
    def test_forged_original_hash_blocks(self):
        self.source["retrieval"]["sha256"] = "1" * 64
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")
    def test_cc0_cannot_be_relabelled_public_domain(self):
        self.assertEqual(self.run_gate(output="PUBLIC-DOMAIN")["status"], "INCOMPATIBLE")
    def test_unknown_output_license_blocks(self):
        self.assertEqual(self.run_gate(output="OFL-1.1")["status"], "REVIEW_REQUIRED")
    def test_copyleft_relicense_conflict(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        self.assertEqual(self.run_gate(output="CC0-1.0")["status"], "INCOMPATIBLE")
    def test_aggregation_without_collection_rights_stays_review(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        self.assertEqual(self.run_gate(output="CC-BY-SA-4.0", derivative=False)["status"],
                         "REVIEW_REQUIRED")

if __name__ == "__main__":
    unittest.main()
