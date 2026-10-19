import unittest
import os
import json
from legal.licensing.ledger import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()

    def get_valid_base_record(self):
        return {
            "source_id": "test_src_1",
            "url": "https://example.com/data",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "id": "CC0-1.0"
            },
            "modification_status": "unmodified"
        }

    def test_valid_record(self):
        record = self.get_valid_base_record()
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "verified")

    def test_missing_author(self):
        record = self.get_valid_base_record()
        del record["author"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Schema validation failed", result["reason"])

    def test_missing_license(self):
        record = self.get_valid_base_record()
        del record["license"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "blocked")

    def test_missing_source_id(self):
        record = self.get_valid_base_record()
        del record["source_id"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "blocked")

    def test_changed_source_version(self):
        record = self.get_valid_base_record()
        # the schema ensures this is tracked, but for the sake of the test, let's just make sure
        # a record is still valid if version changes to something else
        record["version"] = "2.0"
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "verified")

    def test_incomplete_cc_by_sa_obligations(self):
        record = self.get_valid_base_record()
        record["license"] = {"id": "CC-BY-SA-4.0"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("CC-BY-SA-4.0 requires explicit evidence", result["reason"])

        record["license"] = {"id": "CC-BY-SA-4.0", "evidence_url": "https://example.com/license"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "verified")

    def test_incomplete_gfdl_provenance(self):
        record = self.get_valid_base_record()
        record["license"] = {"id": "GFDL-1.3-only"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "reviewRequired")

        record["license"] = {"id": "GFDL-1.3-only", "evidence_url": "https://example.com/license"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("gfdl_copy_path", result["reason"])

        record["license"] = {"id": "GFDL-1.3-only", "evidence_url": "https://example.com/license", "gfdl_copy_path": "/path/to/copy"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "verified")

    def test_never_infer_public_domain(self):
        record = self.get_valid_base_record()
        record["license"] = {"id": "PUBLIC-DOMAIN"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("Public domain requires explicit proof", result["reason"])

        record["license"] = {
            "id": "PUBLIC-DOMAIN",
            "public_domain_proof": {
                "jurisdiction": "US",
                "legal_basis": "Expired",
                "work_date": "1920"
            }
        }
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "verified")

    def test_legal_uncertainty_review_required(self):
        record = self.get_valid_base_record()
        record["license"] = {"id": "UNVERIFIED"}
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("unverified", result["reason"])

if __name__ == '__main__':
    unittest.main()
