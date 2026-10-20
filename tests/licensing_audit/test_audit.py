"""Focused no-network tests for source-specific rights evidence preflight."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.licensing_audit.audit import audit_ledger, audit_source


class LicensingAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "proof").mkdir()
        self.bytes = b'{"word":"Haus","lang":"de"}\n'
        self.notice = b"Wiktionary texts: Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0)."
        (self.root / "proof/source.jsonl").write_bytes(self.bytes)
        (self.root / "proof/rights.txt").write_bytes(self.notice)
        self.source = {
            "source_id": "test-wiktionary", "kind": "dictionary", "publisher": "TEST ONLY",
            "origin_url": "https://de.wiktionary.org/", "dataset_version": "test-v1",
            "retrieval": {"identity": "test-fixture-immutable", "url": "https://example.org/2026/source.jsonl",
                          "date": "2026-10-14", "artifact_path": "proof/source.jsonl",
                          "sha256": self.digest(self.bytes)},
            "license": {"id": "CC-BY-SA-4.0", "evidence_url": "https://de.wiktionary.org/wiki/Wiktionary:Copyright",
                        "evidence_path": "proof/rights.txt", "evidence_sha256": self.digest(self.notice)},
            "alterations": ["none"], "status": "APPROVED_FOR_REDISTRIBUTION",
            "review": {"reviewer": "TEST ONLY", "decision_url": "https://example.org/test-approval"},
        }

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def result(self, source=None):
        return audit_source(source if source is not None else self.source, self.root)

    def codes(self, source=None):
        return {f["code"] for f in self.result(source)["findings"]}

    def test_genuine_test_bytes_hash_is_checked_not_just_declared(self):
        self.assertEqual(self.result()["decision"], "APPROVED")
        (self.root / "proof/source.jsonl").write_bytes(b"changed")
        self.assertEqual(self.result()["decision"], "BLOCKED")
        self.assertIn("ARTIFACT_HASH_MISMATCH", self.codes())

    def test_missing_source_or_notice_is_never_approved(self):
        (self.root / "proof/source.jsonl").unlink()
        self.assertNotEqual(self.result()["decision"], "APPROVED")
        (self.root / "proof/source.jsonl").write_bytes(self.bytes)
        (self.root / "proof/rights.txt").unlink()
        self.assertIn("NOTICE_MISSING", self.codes())

    def test_notice_mismatch_is_blocked(self):
        (self.root / "proof/rights.txt").write_bytes(b"changed")
        self.assertIn("NOTICE_HASH_MISMATCH", self.codes())
        self.assertEqual(self.result()["decision"], "BLOCKED")

    def test_noncommercial_prohibition_beats_claimed_license(self):
        nc = b"Creative Commons Attribution-NonCommercial-ShareAlike 4.0 CC BY-NC-SA 4.0"
        (self.root / "proof/rights.txt").write_bytes(nc)
        self.source["license"]["evidence_sha256"] = self.digest(nc)
        self.assertIn("NONCOMMERCIAL_RESTRICTION", self.codes())
        self.assertEqual(self.result()["decision"], "BLOCKED")

    def test_unknown_license_is_not_assumed_cc0(self):
        self.source["license"]["id"] = "UNKNOWN"
        self.assertEqual(self.result()["decision"], "UNKNOWN")

    def test_cc0_claim_conflicting_with_by_sa_notice_blocks(self):
        self.source["license"]["id"] = "CC0-1.0"
        self.assertIn("NOTICE_LICENSE_CONFLICT", self.codes())
        self.assertEqual(self.result()["decision"], "BLOCKED")

    def test_dual_license_requires_human_review_not_automatic_rejection(self):
        dual = b"Copyright under Creative Commons Attribution-ShareAlike 4.0 and GNU Free Documentation License."
        (self.root / "proof/rights.txt").write_bytes(dual)
        self.source["license"]["evidence_sha256"] = self.digest(dual)
        self.assertEqual(self.result()["decision"], "REVIEW_REQUIRED")

    def test_approval_requires_separate_human_review(self):
        self.source.pop("review")
        self.assertEqual(self.result()["decision"], "REVIEW_REQUIRED")
        self.assertIn("MANUAL_REVIEW_MISSING", self.codes())

    def test_unsafe_url_and_mutable_latest_are_not_approved(self):
        self.source["retrieval"]["url"] = "https://127.0.0.1/data?token=secret"
        self.assertEqual(self.result()["decision"], "BLOCKED")
        self.assertIn("UNSAFE_URL", self.codes())
        self.source["retrieval"]["url"] = "https://example.org/latest.jsonl"
        self.assertIn("MUTABLE_SOURCE_URL", self.codes())
        self.assertEqual(self.result()["decision"], "REVIEW_REQUIRED")

    def test_path_traversal_and_symlinks_cannot_escape_root(self):
        self.source["retrieval"]["artifact_path"] = "../elsewhere"
        self.assertIn("UNSAFE_PATH", self.codes())
        self.source["retrieval"]["artifact_path"] = "proof/source-link"
        (self.root / "proof/source-link").symlink_to(self.root / "proof/source.jsonl")
        self.assertIn("UNSAFE_PATH", self.codes())

    def test_image_or_audio_are_independent_from_dictionary_rights(self):
        self.source["kind"] = "pronunciation"
        self.assertIn("MEDIA_RIGHTS_REVIEW", self.codes())
        self.assertEqual(self.result()["decision"], "REVIEW_REQUIRED")
        self.source["kind"] = "visual_asset"
        self.assertIn("MEDIA_RIGHTS_REVIEW", self.codes())

    def test_hostile_array_fields_fail_closed_instead_of_crashing(self):
        source = dict(self.source)
        source["kind"] = ["dictionary"]
        source["license"] = {"id": ["CC0-1.0"]}
        self.assertEqual(self.result(source)["decision"], "BLOCKED")

    def test_empty_registry_is_unknown_and_never_release_ready(self):
        report = audit_ledger({"schema_version": "1.0.0", "sources": []}, self.root)
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["sources"], [])

    def test_report_has_source_level_findings_and_no_production_claim(self):
        report = audit_ledger({"schema_version": "1.0.0", "sources": [self.source]}, self.root)
        self.assertEqual(report["sources"][0]["source_id"], "test-wiktionary")
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["counts"]["APPROVED"], 1)


if __name__ == "__main__":
    unittest.main()
