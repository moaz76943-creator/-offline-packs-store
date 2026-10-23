import copy
import tempfile
import unittest
from legal.license_compatibility.compatibility import check_compatibility
from tools.contribution_gate.test_fixture import fixture, save_ledger

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger, self.source = fixture(self.tmp.name)
    def run_gate(self, sources=None, output="CC0-1.0", derivative=True):
        return check_compatibility(sources if sources is not None else [self.source],
                                   output, derivative, repo_root=self.tmp.name)
    def test_injected_approved_source_cannot_override_empty_canonical_ledger(self):
        save_ledger(self.tmp.name, {"schema_version": "1.0.0", "sources": []})
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")

    def test_injected_changed_origin_cannot_override_canonical_record(self):
        save_ledger(self.tmp.name, self.ledger)
        self.source["origin_url"] = "https://example.org/forged"
        self.assertEqual(self.run_gate()["status"], "REVIEW_REQUIRED")

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
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate(output="CC0-1.0")["status"], "INCOMPATIBLE")
    def test_aggregation_without_collection_rights_stays_review(self):
        self.source["license"]["id"] = "CC-BY-SA-4.0"
        save_ledger(self.tmp.name, self.ledger)
        self.assertEqual(self.run_gate(output="CC-BY-SA-4.0", derivative=False)["status"],
                         "REVIEW_REQUIRED")

    def test_multiple_sources_with_categorized_obligations(self):
        source1 = copy.deepcopy(self.source)
        source1["source_id"] = "src1"
        source1["license"]["id"] = "CC-BY-SA-4.0"

        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "src2"
        source2["license"]["id"] = "CC0-1.0"

        self.ledger["sources"] = [source1, source2]
        save_ledger(self.tmp.name, self.ledger)

        r = self.run_gate(sources=[source1, source2], output="CC-BY-SA-4.0")
        self.assertEqual(r["status"], "COMPATIBLE")
        self.assertTrue(r["obligations"]["share_alike"])
        self.assertTrue(r["obligations"]["attribution"])
        self.assertTrue(r["obligations"]["modification"])
        self.assertTrue(r["obligations"]["redistribution"])

    def test_public_domain_sources_explicitly(self):
        self.source["license"]["id"] = "PUBLIC-DOMAIN"
        self.source["license"]["public_domain_proof"] = {
            "jurisdiction": "US",
            "legal_basis": "zero_copyright",
            "work_date": "1900-01-01"
        }
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(output="PUBLIC-DOMAIN")
        self.assertEqual(r["status"], "COMPATIBLE")
        self.assertFalse(r["obligations"]["share_alike"])
        self.assertFalse(r["obligations"]["attribution"])
        self.assertFalse(r["obligations"]["modification"])
        self.assertFalse(r["obligations"]["redistribution"])

    def test_conflicting_share_alike_obligations(self):
        source1 = copy.deepcopy(self.source)
        source1["source_id"] = "src1"
        source1["license"]["id"] = "CC-BY-SA-4.0"

        source2 = copy.deepcopy(self.source)
        source2["source_id"] = "src2"
        source2["license"]["id"] = "GFDL-1.3-only"

        self.ledger["sources"] = [source1, source2]
        save_ledger(self.tmp.name, self.ledger)

        r = self.run_gate(sources=[source1, source2], output="CC-BY-SA-4.0")
        self.assertEqual(r["status"], "INCOMPATIBLE")
        self.assertEqual(r["reason"], "GFDL and CC BY-SA derivative conflict")

    def test_attribution_only_source_cannot_downgrade_copyleft_conflict(self):
        sources = []
        for index, license_id in enumerate(('CC-BY-2.0-FR', 'CC-BY-SA-4.0', 'GFDL-1.3-only')):
            source = copy.deepcopy(self.source)
            source['source_id'] = 'src-' + str(index)
            source['license']['id'] = license_id
            sources.append(source)
        self.ledger['sources'] = sources
        save_ledger(self.tmp.name, self.ledger)
        result = self.run_gate(sources=sources, output='CC-BY-SA-4.0')
        self.assertEqual(result['status'], 'INCOMPATIBLE')
        self.assertEqual(result['reason'], 'GFDL and CC BY-SA derivative conflict')

    def test_gfdl_copyleft_reports_share_alike(self):
        self.source["license"]["id"] = "GFDL-1.3-only"
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(output="GFDL-1.3-only")
        self.assertEqual(r["status"], "COMPATIBLE", r)
        self.assertTrue(r["obligations"]["share_alike"])

    def test_public_domain_does_not_cancel_copyleft_redistribution(self):
        source_sa = copy.deepcopy(self.source)
        source_sa["source_id"] = "src-sa"
        source_sa["license"]["id"] = "CC-BY-SA-4.0"
        source_pd = copy.deepcopy(self.source)
        source_pd["source_id"] = "src-pd"
        source_pd["license"]["id"] = "PUBLIC-DOMAIN"
        source_pd["license"]["public_domain_proof"] = {
            "jurisdiction": "US",
            "legal_basis": "zero_copyright",
            "work_date": "1900-01-01",
        }
        self.ledger["sources"] = [source_sa, source_pd]
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(sources=[source_sa, source_pd], output="CC-BY-SA-4.0")
        self.assertEqual(r["status"], "COMPATIBLE", r)
        self.assertTrue(r["obligations"]["redistribution"])
        self.assertTrue(r["obligations"]["share_alike"])

    def test_public_domain_does_not_cancel_gfdl_redistribution(self):
        source_gfdl = copy.deepcopy(self.source)
        source_gfdl["source_id"] = "src-gfdl"
        source_gfdl["license"]["id"] = "GFDL-1.3-only"
        source_pd = copy.deepcopy(self.source)
        source_pd["source_id"] = "src-pd"
        source_pd["license"]["id"] = "PUBLIC-DOMAIN"
        source_pd["license"]["public_domain_proof"] = {
            "jurisdiction": "US",
            "legal_basis": "zero_copyright",
            "work_date": "1900-01-01",
        }
        self.ledger["sources"] = [source_gfdl, source_pd]
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(sources=[source_gfdl, source_pd], output="GFDL-1.3-only")
        self.assertEqual(r["status"], "COMPATIBLE", r)
        self.assertTrue(r["obligations"]["redistribution"])
        self.assertTrue(r["obligations"]["share_alike"])

    def test_permissive_with_obligations_conversion_requires_review(self):
        self.source["license"]["id"] = "CC-BY-2.0-FR"
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(output="CC-BY-SA-4.0")
        self.assertEqual(r["status"], "REVIEW_REQUIRED", r)
        self.assertFalse(r["publication_approved"])

    def test_permissive_to_gfdl_requires_independent_conversion_review(self):
        self.source['license']['id'] = 'CC-BY-2.0-FR'
        save_ledger(self.tmp.name, self.ledger)
        for derivative in (True, False):
            result = self.run_gate(output='GFDL-1.3-only', derivative=derivative)
            self.assertEqual(result['status'], 'REVIEW_REQUIRED')
            self.assertFalse(result['publication_approved'])
            self.assertTrue(result['obligations']['attribution'])

    def test_permissive_with_obligations_to_cc0_blocks(self):
        self.source["license"]["id"] = "CC-BY-2.0-FR"
        save_ledger(self.tmp.name, self.ledger)
        r = self.run_gate(output="CC0-1.0")
        self.assertEqual(r["status"], "INCOMPATIBLE", r)
        self.assertEqual(r["reason"], "cannot drop obligations for CC0-1.0")

if __name__ == "__main__":
    unittest.main()
