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

    def test_symlink_output_directory_is_rejected_without_external_writes(self):
        with tempfile.TemporaryDirectory() as external:
            target = Path(external)
            (target / "keep.txt").write_text("untouched")
            self.out.symlink_to(target, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                self.run_gate()
            self.assertEqual((target / "keep.txt").read_text(), "untouched")
            self.assertFalse((target / "attribution.json").exists())

    def test_symlink_notice_target_is_rejected_without_external_writes(self):
        self.out.mkdir()
        target = self.root / "outside-notice.txt"
        target.write_text("unchanged")
        (self.out / "case-source_notice.txt").symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.run_gate()
        self.assertEqual(target.read_text(), "unchanged")
        self.assertFalse((self.out / "attribution.json").exists())

    def test_symlink_manifest_target_is_rejected_before_notices(self):
        self.out.mkdir()
        target = self.root / "outside-attribution.json"
        target.write_text("unchanged")
        (self.out / "attribution.json").symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.run_gate()
        self.assertEqual(target.read_text(), "unchanged")
        self.assertFalse((self.out / "case-source_notice.txt").exists())

    def test_symlink_output_parent_cannot_redirect_output(self):
        with tempfile.TemporaryDirectory() as external:
            parent = self.root / "linked-parent"
            parent.symlink_to(external, target_is_directory=True)
            self.out = parent / "notices"
            with self.assertRaises((ValueError, OSError)):
                self.run_gate()
            self.assertFalse((Path(external) / "notices").exists())

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

    def test_missing_author(self):
        self.source["publisher"] = ""
        if "author" in self.source:
            del self.source["author"]
        with self.assertRaisesRegex(ValueError, "publisher and exact dataset version required|Missing author or publisher"):
            self.run_gate()

    def test_changed_source_versions(self):
        # Different version
        bad = ref(self.source)
        bad["dataset_version"] = "2.0"
        with self.assertRaisesRegex(ValueError, "Missing or stale dataset_version"):
            self.run_gate([bad])

    def test_combined_source_packages(self):
        import copy
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "case-source-2"
        self.ledger["sources"].append(source2)
        refs = [ref(self.source), ref(source2)]

        result = self.run_gate(refs)
        self.assertEqual(len(result), 2)

        manifest_path = self.out / "attribution.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 2)

        notice1 = self.out / "case-source_notice.txt"
        notice2 = self.out / "case-source-2_notice.txt"
        self.assertTrue(notice1.exists())
        self.assertTrue(notice2.exists())

    def test_invalid_notices(self):
        self.source["license"]["id"] = "PUBLIC-DOMAIN"
        # Removing public_domain_proof should raise an error
        if "public_domain_proof" in self.source["license"]:
            del self.source["license"]["public_domain_proof"]

        with self.assertRaisesRegex(ValueError, "jurisdiction, legal basis and work date required|Missing public_domain_proof"):
            self.run_gate()

if __name__ == "__main__":
    unittest.main()
