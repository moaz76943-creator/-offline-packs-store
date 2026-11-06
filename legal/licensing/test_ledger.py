import unittest
from legal.licensing.ledger import LicensingLedgerValidator

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()
        self.valid_record = {
            "source_id": "src-1",
            "url": "https://example.com/data",
            "author": "John Doe",
            "version": "1.0",
            "license": {
                "declared_id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license"
            }
        }
        self.valid_record_2 = {
            "source_id": "src-2",
            "url": "https://example.com/data2",
            "author": "Jane Doe",
            "version": "1.0",
            "license": {
                "declared_id": "GFDL-1.3-only",
                "evidence_url": "https://example.com/license2"
            }
        }

    def test_valid_record(self):
        result = self.validator.validate_record(self.valid_record)
        self.assertEqual(result["status"], "VERIFIED")

    def test_missing_author(self):
        record = self.valid_record.copy()
        del record["author"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

    def test_missing_license(self):
        record = self.valid_record.copy()
        del record["license"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

    def test_missing_source_identity(self):
        record = self.valid_record.copy()
        del record["source_id"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

    def test_unknown_license_id(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declared_id": "UNKNOWN",
            "evidence_url": "https://example.com/license"
        }
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

    def test_changed_source_version(self):
        # Changed source version triggers review/blocked in evaluation
        record1 = self.valid_record.copy()
        record2 = self.valid_record.copy()
        record2["version"] = "2.0"
        result = self.validator.evaluate_mixed_sources([record1, record2])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")

    def test_incomplete_obligations(self):
        # Missing evidence url for CC-BY-SA or GFDL
        record = self.valid_record.copy()
        del record["license"]["evidence_url"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

    def test_mixed_licenses_review_required(self):
        result = self.validator.evaluate_mixed_sources([self.valid_record, self.valid_record_2])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")

    def test_never_infer_public_domain(self):
        # A record with missing license is just blocked, never inferred PD.
        record = self.valid_record.copy()
        del record["license"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")

if __name__ == '__main__':
    unittest.main()
