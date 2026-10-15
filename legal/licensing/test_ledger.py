import unittest
from copy import deepcopy
from legal.licensing.ledger import LedgerAPI

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.api = LedgerAPI()
        self.valid_record = {
            "source_id": "src-1",
            "url": "https://example.com/src1",
            "author": "Alice",
            "version": "1.0",
            "modification_status": "unmodified",
            "artifact_sha256": "a"*64,
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence": {
                    "has_evidence": True,
                    "url": "https://example.com/license"
                },
                "obligations_met": [
                    "attribution", "license_link", "changes_disclosed",
                    "sharealike", "no_additional_restrictions"
                ]
            }
        }
        self.valid_ledger = {
            "schema_version": "1.0.0",
            "records": [self.valid_record]
        }

    def test_valid_ledger_schema(self):
        self.assertTrue(self.api.validate_ledger(self.valid_ledger))

    def test_missing_author_blocked(self):
        record = deepcopy(self.valid_record)
        del record["author"]
        self.assertEqual(self.api.check_eligibility(record), "blocked")

    def test_missing_license_blocked(self):
        record = deepcopy(self.valid_record)
        del record["license"]
        self.assertEqual(self.api.check_eligibility(record), "blocked")

    def test_missing_source_id_blocked(self):
        record = deepcopy(self.valid_record)
        del record["source_id"]
        self.assertEqual(self.api.check_eligibility(record), "blocked")

    def test_no_public_domain_inference(self):
        record = deepcopy(self.valid_record)
        del record["license"]["declared"]
        # If no license is declared, it should be blocked, not assumed public domain
        self.assertEqual(self.api.check_eligibility(record), "blocked")

    def test_incomplete_cc_by_sa_obligations_blocked(self):
        record = deepcopy(self.valid_record)
        record["license"]["obligations_met"] = ["attribution"] # Missing others
        self.assertEqual(self.api.check_eligibility(record), "blocked")

    def test_changed_source_version_review_required(self):
        canonical = deepcopy(self.valid_record)
        canonical["version"] = "0.9"
        self.assertEqual(self.api.check_eligibility(self.valid_record, canonical), "reviewRequired")

    def test_changed_hash_review_required(self):
        canonical = deepcopy(self.valid_record)
        canonical["artifact_sha256"] = "b"*64
        self.assertEqual(self.api.check_eligibility(self.valid_record, canonical), "reviewRequired")

    def test_mixed_provenance_uncertainty(self):
        cc_record = deepcopy(self.valid_record)

        gfdl_record = {
            "source_id": "src-2",
            "url": "https://example.com/src2",
            "author": "Bob",
            "version": "2.0",
            "modification_status": "unmodified",
            "license": {
                "declared": "GFDL-1.3-only",
                "evidence": {"has_evidence": True},
                "obligations_met": [
                    "license_copy", "copyright_notices", "history",
                    "invariant_sections_checked", "cover_texts_checked",
                    "transparent_copy_checked"
                ]
            }
        }

        result = self.api.evaluate_mixed_provenance([cc_record, gfdl_record])
        self.assertEqual(result["status"], "reviewRequired")

    def test_mixed_provenance_valid(self):
        pd_record = deepcopy(self.valid_record)
        pd_record["source_id"] = "src-3"
        pd_record["license"] = {
            "declared": "PUBLIC-DOMAIN",
            "evidence": {"has_evidence": True},
            "obligations_met": []
        }

        result = self.api.evaluate_mixed_provenance([self.valid_record, pd_record])
        self.assertEqual(result["status"], "verified")
        self.assertIn("CC-BY-SA-4.0", result["licenses"])
        self.assertIn("PUBLIC-DOMAIN", result["licenses"])

    def test_gfdl_provenance_handling(self):
        gfdl_record = {
            "source_id": "src-2",
            "url": "https://example.com/src2",
            "author": "Bob",
            "version": "2.0",
            "modification_status": "unmodified",
            "license": {
                "declared": "GFDL-1.3-only",
                "evidence": {"has_evidence": True},
                "obligations_met": [
                    "license_copy", "copyright_notices", "history",
                    "invariant_sections_checked", "cover_texts_checked",
                    "transparent_copy_checked"
                ]
            }
        }
        self.assertEqual(self.api.check_eligibility(gfdl_record), "verified")

if __name__ == '__main__':
    unittest.main()
