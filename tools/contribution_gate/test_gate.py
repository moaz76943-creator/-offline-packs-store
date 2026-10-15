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
        import json
        grant = {
            "source_id": self.source["source_id"],
            "source_version": self.source["dataset_version"],
            "asset_id": "candidate-entry",
            "artifact_sha256": self.asset_sha,
            "license_id": "CC0-1.0",
            "rights_holder": "Fixture Rights Holder",
            "scope": "redistribution",
            "grant_url": "https://example.org/rights/fixture-grant",
            "revoked": False,
            "cc0_declaration": True
        }
        self.auth_sha = put(self.root, "evidence/auth.txt",
                            json.dumps(grant, sort_keys=True).encode("utf-8"))
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
    def _replace_authorization(self, data):
        import json
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        new_hash = put(self.root, "evidence/auth.txt", raw)
        self.manifest["contributor_authorization"]["sha256"] = new_hash

    def _authorization(self):
        return {
            "source_id": self.source["source_id"],
            "source_version": self.source["dataset_version"],
            "asset_id": self.manifest["asset_id"],
            "artifact_sha256": self.asset_sha,
            "license_id": self.manifest["license_id"],
            "rights_holder": "Fixture Rights Holder",
            "scope": "redistribution",
            "grant_url": "https://example.org/rights/fixture-grant",
            "revoked": False,
            "cc0_declaration": True
        }

    def test_unstructured_authorization_proof_not_admissible(self):
        self._replace_authorization("I grant redistribution")
        self.assertEqual(self.check()["status"], "REJECT")

    def test_unbound_source_identity_in_authorization_is_rejected(self):
        rights = self._authorization()
        rights["source_id"] = "unrelated-source"
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_unbound_artifact_hash_in_authorization_is_rejected(self):
        rights = self._authorization()
        rights["artifact_sha256"] = "f" * 64
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_with_revoked_permission_is_rejected(self):
        rights = self._authorization()
        rights["revoked"] = True
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_without_rights_holder_is_rejected(self):
        rights = self._authorization()
        rights["rights_holder"] = ""
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_wrong_source_version_rejected(self):
        rights = self._authorization()
        rights["source_version"] = "stale-version"
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_wrong_scope_rejected(self):
        rights = self._authorization()
        rights["scope"] = "view_only"
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_insecure_grant_url_rejected(self):
        rights = self._authorization()
        rights["grant_url"] = "http://example.org/rights"
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_authorization_large_snapshot_rejected(self):
        big = b"x" * 65537
        self.manifest["contributor_authorization"]["sha256"] = put(
            self.root, "evidence/auth.txt", big)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_evidence_pass_is_not_legal_clearance(self):
        r = self.check()
        self.assertEqual(r["status"], "ACCEPT", r)
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
        self.assertEqual(self.check()["status"], "REVIEW_REQUIRED")
    def test_source_rejected(self):
        self.source["status"] = "BLOCKED_LICENSE"
        save_ledger(self.root, self.ledger)
        self.assertEqual(self.check()["status"], "REJECT")
    def test_explicit_fixture_marker(self):
        self.manifest["is_fixture"] = True
        self.assertEqual(self.check()["status"], "REJECT")

    def test_false_cc0_declaration(self):
        rights = self._authorization()
        rights["cc0_declaration"] = False
        self._replace_authorization(rights)
        self.assertEqual(self.check()["status"], "REJECT")

    def test_incomplete_attribution(self):
        notice = ("case-source Example Test Publisher https://example.org/fixture-source")
        self.manifest["attribution_notice"]["sha256"] = put(self.root, "notices/notice.txt", notice.encode())
        self.assertEqual(self.check()["status"], "REJECT")

    def test_changed_hashes(self):
        self.manifest["sha256"] = "f" * 64
        self.assertEqual(self.check()["status"], "REJECT")

    def test_conflicting_obligations(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        self.manifest["license_id"] = "CC-BY-SA-4.0"
        rights = self._authorization()
        rights["license_id"] = "CC-BY-SA-4.0"
        self._replace_authorization(rights)

        notice = ("case-source Example Test Publisher https://example.org/fixture-source CC-BY-SA-4.0")
        self.manifest["attribution_notice"]["sha256"] = put(self.root, "notices/notice.txt", notice.encode())
        save_ledger(self.root, self.ledger)

        self.manifest["compliance"] = {"attribution": True} # Missing others
        self.assertEqual(self.check()["status"], "REJECT")

        self.manifest["compliance"] = {
            "attribution": True,
            "license_link": True,
            "changes_disclosed": True,
            "sharealike": True,
            "no_additional_restrictions": True
        }
        self.assertEqual(self.check()["status"], "ACCEPT")

    def test_valid_submissions(self):
        self.assertEqual(self.check()["status"], "ACCEPT")

if __name__ == "__main__":
    unittest.main()
