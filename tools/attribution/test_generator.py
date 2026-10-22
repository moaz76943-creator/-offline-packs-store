import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.attribution.generator import generate_attribution
from tools.contribution_gate.test_fixture import fixture, ref, save_ledger

class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger, self.source = fixture(self.root)
        self.source["author"] = "Test Author"
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
        self.source["author"] = ""
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_multi_source_combined_package(self):
        # We need another source to combine.
        import copy
        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "source-2"
        source2["author"] = "Another Author"
        self.ledger["sources"].append(source2)
        save_ledger(self.root, self.ledger)
        refs = [ref(self.source), ref(source2)]
        result = self.run_gate(refs)
        self.assertEqual(len(result), 2)
        # Check files are generated
        self.assertTrue((self.out / "case-source_notice.txt").exists())
        self.assertTrue((self.out / "source-2_notice.txt").exists())
        manifest = json.loads((self.out / "attribution.json").read_text())
        self.assertEqual(len(manifest), 2)

    def test_repeated_generation_is_stable(self):
        self.run_gate()
        first_manifest = (self.out / "attribution.json").read_text()
        first_notice = (self.out / "case-source_notice.txt").read_text()

        self.run_gate()
        second_manifest = (self.out / "attribution.json").read_text()
        second_notice = (self.out / "case-source_notice.txt").read_text()

        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_notice, second_notice)

    def test_changed_source_version(self):
        bad = ref(self.source)
        bad["dataset_version"] = "99.0"
        with self.assertRaises(ValueError):
            self.run_gate([bad])

    def test_canonical_schema_requires_author(self):
        schema = json.loads((Path(__file__).resolve().parents[2] / "legal/ledger/schema.json").read_text(encoding="utf-8"))
        source = schema["$defs"]["source"]
        self.assertIn("author", source["required"])
        self.assertEqual(source["properties"]["author"]["type"], "string")
        self.assertFalse(source["additionalProperties"])

    def test_nondirectory_component_closes_traversal_descriptor(self):
        blocker = self.root / "file-not-dir"
        blocker.write_text("x", encoding="utf-8")
        self.out = blocker / "notices"
        before = set(os.listdir("/proc/self/fd"))
        with self.assertRaises(OSError):
            self.run_gate()
        self.assertEqual(before, set(os.listdir("/proc/self/fd")))

    def test_execute_only_ancestor_still_receives_notices(self):
        locked = self.root / "locked-ok"
        locked.mkdir()
        out = locked / "notices"
        out.mkdir()
        os.chmod(locked, 0o111)
        self.out = out
        try:
            result = self.run_gate()
            self.assertEqual(result[0]["author"], "Test Author")
            self.assertTrue((out / "attribution.json").is_file())
        finally:
            os.chmod(locked, 0o755)

    def test_permission_fallback_does_not_follow_replaced_ancestor(self):
        external = self.root / "external"
        external.mkdir()
        (external / "marker.txt").write_text("untouched", encoding="utf-8")
        locked = self.root / "locked"
        locked.mkdir()
        (locked / "via").symlink_to(external, target_is_directory=True)
        os.chmod(locked, 0o111)
        self.out = locked / "via" / "notices"
        try:
            with patch.object(Path, "is_symlink", lambda _self: False):
                with self.assertRaises((ValueError, OSError)):
                    self.run_gate()
            self.assertFalse((external / "notices").exists())
            self.assertFalse((external / "attribution.json").exists())
            self.assertEqual((external / "marker.txt").read_text(encoding="utf-8"), "untouched")
        finally:
            os.chmod(locked, 0o755)

    def test_invalid_notice_format_rejected(self):
        # Test case: we want to verify invalid notices. The generation itself enforces format,
        # but let's test a case where attribution generation fails because of missing metadata
        # which would result in an invalid notice.
        self.source["origin_url"] = ""
        with self.assertRaises(ValueError):
            self.run_gate()

    def test_co_offered_licenses_included(self):
        self.source["license"]["co_offered_licenses"] = ["GFDL-1.3-only"]
        result = self.run_gate()
        self.assertEqual(result[0]["co_offered_licenses"], ["GFDL-1.3-only"])
        notice = (self.out / "case-source_notice.txt").read_text()
        self.assertIn("Co-offered licenses: GFDL-1.3-only", notice)

if __name__ == "__main__":
    unittest.main()
