"""Synthetic fixtures test a gate; they never constitute redistribution rights."""
import hashlib
import tempfile
import unittest
from pathlib import Path
import json

from legal.font_assets.registry import FontAsset, FontRightsRegistry

class FontEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        (self.root / "catalog").mkdir()
        catalog_data = {"scripts": {"Latn": {"name": "Latin"}, "Cyrl": {"name": "Cyrillic"}}}
        (self.root / "catalog" / "language_registry.v1.json").write_text(json.dumps(catalog_data))

        def put(rel, content):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            return hashlib.sha256(content).hexdigest()
        self.put = put
        self.font_hash = put("fonts/fixture.otf", b"fixture font test bytes ONLY")
        self.lic_hash = put("evidence/rights.txt", b"Fixture origin font SIL OPEN FONT LICENSE")
        self.notice_hash = put("notices/OFL.txt", b"SIL OPEN FONT LICENSE fixture")
        self.review_hash = put("evidence/review.txt", b"Fixture reviewer decision record")
        self.asset = FontAsset(
            id="fixture-font", family="Fixture Font", source="fixture-publisher",
            version="1.0", author="Fixture Author", license_id="OFL-1.1",
            scripts=["Latn"], embedded=True, sha256=self.font_hash,
            asset_path="fonts/fixture.otf", origin_url="https://example.org/font",
            license_evidence_url="https://example.org/font/license",
            license_evidence_path="evidence/rights.txt",
            license_evidence_sha256=self.lic_hash, license_text_included=True,
            distribution_notice_path="notices/OFL.txt",
            distribution_notice_sha256=self.notice_hash,
            review={"reviewer": "fixture-reviewer", "decision_url": "https://example.org/review/1"},
            review_evidence_path="evidence/review.txt",
            review_evidence_sha256=self.review_hash)
        self.gate = FontRightsRegistry()
    def check(self):
        return self.gate.validate_asset(self.asset, expected_hash=self.asset.sha256,
                                        repo_root=self.root)
    def test_verified_fixture_is_only_evidence_pass_not_legal_approval(self):
        result = self.check()
        self.assertEqual(result["status"], "EVIDENCE_PASS", result)
        self.assertFalse(result["publication_approved"])
    def test_forged_two_equal_hash_strings_cannot_substitute_for_bytes(self):
        self.asset.sha256 = "a" * 64
        self.assertEqual(self.check()["status"], "REJECT")
    def test_changed_bytes_rejected(self):
        (self.root / "fonts/fixture.otf").write_bytes(b"forged")
        self.assertEqual(self.check()["status"], "REJECT")
    def test_absent_font_bytes_rejected(self):
        (self.root / "fonts/fixture.otf").unlink()
        self.assertEqual(self.check()["status"], "REJECT")
    def test_missing_source_specific_license_rejected(self):
        self.asset.license_evidence_path = "../outside.txt"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_missing_distributed_license_rejected(self):
        self.asset.distribution_notice_path = "notices/missing.txt"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_missing_review_rejected(self):
        self.asset.review = None
        self.assertEqual(self.check()["status"], "REJECT")
    def test_no_license_guess_based_on_vendor_or_name(self):
        self.asset.license_id = "UNVERIFIED_RIGHTS"
        self.assertEqual(self.check()["status"], "REJECT")
    def test_metadata_only_is_not_embedded_redistribution(self):
        self.asset.embedded = False
        self.assertEqual(self.check()["status"], "REVIEW_REQUIRED")
    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "font.otf"
            outside_file.write_bytes(b"fixture font test bytes ONLY")
            (self.root / "fonts/fixture.otf").unlink()
            (self.root / "fonts/fixture.otf").symlink_to(outside_file)
            self.assertEqual(self.check()["status"], "REJECT")
    def test_unverified_distribution_notice_claim_is_not_proof(self):
        self.asset.distribution_notice_sha256 = "0" * 64
        self.assertEqual(self.check()["status"], "REJECT")

    def test_malformed_license_id_blocks_instead_of_crash(self):
        self.asset.license_id = []
        self.assertEqual(self.check()["status"], "REJECT")
    def test_malformed_hash_blocks_instead_of_crash(self):
        self.asset.sha256 = 123
        self.assertEqual(self.check()["status"], "REJECT")
    def test_malformed_license_url_blocks_instead_of_crash(self):
        self.asset.license_evidence_url = 123
        self.assertEqual(self.check()["status"], "REJECT")

    def test_unknown_source_rejected(self):
        self.asset.source = "unknown vendor"
        self.assertEqual(self.check()["status"], "REJECT")

    def test_mixed_families_rejected(self):
        self.asset.family = "Mixed Families"
        self.assertEqual(self.check()["status"], "REJECT")

    def test_unmixed_family_name_can_pass(self):
        self.asset.family = "Unmixed Sans"
        result = self.check()
        self.assertEqual(result["status"], "EVIDENCE_PASS", result)

    def test_source_name_containing_unknown_substring_can_pass(self):
        self.asset.source = "The Unknowns Collective"
        result = self.check()
        self.assertEqual(result["status"], "EVIDENCE_PASS", result)

    def test_script_not_in_canonical_registry_rejected(self):
        self.asset.scripts = ["Zzzz"]
        self.assertEqual(self.check()["status"], "REJECT")

    def test_generate_script_mapping(self):
        asset2 = FontAsset(
            id="fixture-font-2", family="Fixture Font 2", source="fixture-publisher",
            version="1.0", author="Fixture Author", license_id="OFL-1.1",
            scripts=["Latn", "Cyrl"], embedded=True, sha256=self.font_hash,
            asset_path="fonts/fixture.otf", origin_url="https://example.org/font",
            license_evidence_url="https://example.org/font/license",
            license_evidence_path="evidence/rights.txt",
            license_evidence_sha256=self.lic_hash, license_text_included=True,
            distribution_notice_path="notices/OFL.txt",
            distribution_notice_sha256=self.notice_hash,
            review={"reviewer": "fixture-reviewer", "decision_url": "https://example.org/review/1"},
            review_evidence_path="evidence/review.txt",
            review_evidence_sha256=self.review_hash)

        asset_rejected = FontAsset(
            id="fixture-font-bad", family="Fixture Font", source="unknown",
            version="1.0", author="Fixture Author", license_id="OFL-1.1",
            scripts=["Latn"], embedded=True, sha256=self.font_hash,
            asset_path="fonts/fixture.otf", origin_url="https://example.org/font",
            license_evidence_url="https://example.org/font/license",
            license_evidence_path="evidence/rights.txt",
            license_evidence_sha256=self.lic_hash, license_text_included=True,
            distribution_notice_path="notices/OFL.txt",
            distribution_notice_sha256=self.notice_hash,
            review={"reviewer": "fixture-reviewer", "decision_url": "https://example.org/review/1"},
            review_evidence_path="evidence/review.txt",
            review_evidence_sha256=self.review_hash)

        mapping = self.gate.generate_script_mapping([self.asset, asset2, asset_rejected], repo_root=self.root)
        self.assertEqual(mapping.get("Latn"), ["fixture-font", "fixture-font-2"])
        self.assertEqual(mapping.get("Cyrl"), ["fixture-font-2"])

    def test_repeated_script_is_mapped_once(self):
        self.asset.scripts = ["Latn", "Latn"]
        mapping = self.gate.generate_script_mapping([self.asset], repo_root=self.root)
        self.assertEqual(mapping.get("Latn"), ["fixture-font"])

    def test_duplicate_asset_ids_are_rejected(self):
        twin = FontAsset(**self.asset.__dict__)
        with self.assertRaises(ValueError):
            self.gate.generate_script_mapping([self.asset, twin], repo_root=self.root)

if __name__ == "__main__":
    unittest.main()
