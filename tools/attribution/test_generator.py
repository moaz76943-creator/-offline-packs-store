import json
import tempfile
import unittest
from pathlib import Path
from tools.attribution.generator import generate_attribution
from tools.contribution_gate.test_fixture import fixture, ref, save_ledger

class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger, self.source = fixture(self.root)
        self.ledger_file = save_ledger(self.root, self.ledger)
        self.refs_file = self.root / "refs.json"
        self.out = self.root / "out"
    def run_gate(self, refs=None):
        self.ledger_file.write_text(json.dumps(self.ledger), encoding="utf-8")
        self.refs_file.write_text(json.dumps(refs if refs is not None else [ref(self.source)]),
                                  encoding="utf-8")
        return generate_attribution(self.ledger_file, self.refs_file, self.out,
                                    repo_root=self.root)
    def test_caller_supplied_approved_ledger_cannot_override_canonical_empty_ledger(self):
        injected = self.root / "injected_sources.json"
        injected.write_text(json.dumps(self.ledger), encoding="utf-8")
        save_ledger(self.root, {"schema_version": "1.0.0", "sources": []})
        self.refs_file.write_text(json.dumps([ref(self.source)]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "canonical"):
            generate_attribution(injected, self.refs_file, self.out, repo_root=self.root)
        self.assertFalse(self.out.exists())

    def test_exact_source_notice_and_deterministic_manifest(self):
        result = self.run_gate()
        self.assertEqual(result[0]["source_id"], "case-source")
        self.assertEqual(result[0]["license_evidence_url"],
                         "https://example.org/fixture-source/rights")
        first = (self.out / "attribution.json").read_bytes()
        self.run_gate()
        self.assertEqual(first, (self.out / "attribution.json").read_bytes())
    def test_unknown_ref_has_no_output(self):
        bad = ref(self.source)
        bad["source_id"] = "unknown"
        with self.assertRaises(ValueError):
            self.run_gate([bad])
        self.assertFalse(self.out.exists())
    def test_hash_conflict_has_no_output(self):
        bad = ref(self.source)
        bad["artifact_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.run_gate([bad])
        self.assertFalse(self.out.exists())
    def test_version_mismatch(self):
        bad = ref(self.source)
        bad["dataset_version"] = "old"
        with self.assertRaises(ValueError):
            self.run_gate([bad])
    def test_missing_rights_snapshot(self):
        self.source["license"]["evidence_path"] = "missing.txt"
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_revoked_approval_blocks_notice(self):
        self.source["status"] = "REVIEW_REQUIRED"
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_unsafe_notice_filename_identity_blocked(self):
        self.source["source_id"] = "../escape"
        with self.assertRaises(ValueError):
            self.run_gate()
    def test_missing_publisher(self):
        self.source["publisher"] = ""
        with self.assertRaises(ValueError):
            self.run_gate()

if __name__ == "__main__":
    unittest.main()
