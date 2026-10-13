import copy
import tempfile
import unittest
from pathlib import Path
from tools.contribution_gate.evidence import verified_sources
from tools.contribution_gate.gate import validate_contribution
from tools.contribution_gate.test_fixture import fixture, ref, put, save_ledger

class ContributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger, self.source = fixture(self.root)
        self.ledger_file = save_ledger(self.root, self.ledger)
        self.asset_sha = put(self.root, "staging/entry.json", b'{"a":1}')
        self.auth_sha = put(self.root, "evidence/auth.txt", b"reviewable fixture authorization")
        notice = ("case-source Example Test Publisher https://example.org/fixture-source CC0-1.0")
        self.notice_sha = put(self.root, "notices/notice.txt", notice.encode())
        self.manifest = {
            "asset_id": "candidate-entry", "kind": "dictionary",
            "source_ref": ref(self.source), "license_id": "CC0-1.0",
            "source_identity": "case-source", "origin_url": self.source["origin_url"],
            "artifact_path": "staging/entry.json", "sha256": self.asset_sha,
            "contributor_authorization": {"artifact_path": "evidence/auth.txt",
                                          "sha256": self.auth_sha},
            "review": {"reviewer": "fixture-reviewer",
                       "decision_url": "https://example.org/fixture-source/review"},
            "attribution_notice": {"artifact_path": "notices/notice.txt",
                                   "sha256": self.notice_sha},
            "source_verification": "verified", "permission_revoked": False
        }
    def check(self):
        return validate_contribution(self.manifest, self.root)
    def test_evidence_pass_is_not_legal_clearance(self):
        r = self.check()
        self.assertEqual(r["status"], "EVIDENCE_PASS", r)
        self.assertFalse(r["publication_approved"])
        self.assertTrue(r["receipt"]["evidence_only"])
    def test_forged_asset_hash(self):
        self.manifest["sha256"] = "e" * 64
        self.assertEqual(self.check()["status"], "REJECT")
    def test_missing_license(self):
        self.manifest["license_id"] = "UNVERIFIED_RIGHTS"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_no_reviewer(self):
        self.manifest.pop("review")
        self.assertEqual(self.check()["status"], "REJECT")
    def test_no_authorization_bytes(self):
        self.manifest["contributor_authorization"]["artifact_path"] = "missing"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_forged_contributor_permission_string(self):
        self.manifest["contributor_authorization"] = "I hereby authorize"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_revocation(self):
        self.manifest["permission_revoked"] = True
        self.assertEqual(self.check()["status"], "REJECT")
    def test_unknown_source(self):
        self.manifest["source_ref"]["source_id"] = "missing"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_stale_source_version(self):
        self.manifest["source_ref"]["dataset_version"] = "0"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_path_traversal(self):
        self.manifest["artifact_path"] = "../entry.json"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_missing_attribution(self):
        self.manifest["attribution_notice"]["artifact_path"] = "missing"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_source_not_approved(self):
        self.source["status"] = "REVIEW_REQUIRED"
        save_ledger(self.root, self.ledger)
        self.assertEqual(self.check()["status"], "REJECT")
    def test_explicit_fixture_marker(self):
        self.manifest["is_fixture"] = True
        self.assertEqual(self.check()["status"], "REJECT")

if __name__ == "__main__":
    unittest.main()
