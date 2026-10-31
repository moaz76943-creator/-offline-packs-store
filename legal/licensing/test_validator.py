import unittest
from legal.licensing.validator import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()
        self.valid_record = {
            "source_id": "test-123",
            "author": "John Doe",
            "declared_license": "CC-BY-SA-4.0",
            "verified_evidence": True,
            "url": "https://example.com",
            "version": "1.0",
            "modification_status": "unmodified"
        }

    def test_missing_attributions(self):
        record = self.valid_record.copy()
        record["author"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

        record["author"] = "John Doe"
        record["source_id"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_missing_license(self):
        record = self.valid_record.copy()
        record["declared_license"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_changed_source_versions(self):
        record = self.valid_record.copy()
        record["version"] = "2.0"
        record["verified_evidence"] = False
        self.assertEqual(self.validator.validate_record(record), "REVIEW_REQUIRED")

    def test_incomplete_cc_by_sa(self):
        record = self.valid_record.copy()
        record["declared_license"] = "CC-BY-SA-4.0"
        record["url"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_gfdl_provenance(self):
        record = self.valid_record.copy()
        record["declared_license"] = "GFDL-1.3-only"
        record["version"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

        record["version"] = "1.0"
        record["modification_status"] = ""
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_uncertain_combinations(self):
        record = self.valid_record.copy()
        record["declared_license"] = "CC-BY-SA-4.0"
        record["co_offered_licenses"] = ["GFDL-1.3-only"]
        self.assertEqual(self.validator.validate_record(record), "REVIEW_REQUIRED")

    def test_inferred_public_domain(self):
        record = self.valid_record.copy()
        record["declared_license"] = "PUBLIC-DOMAIN"
        record["verified_evidence"] = False
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_verified_record(self):
        self.assertEqual(self.validator.validate_record(self.valid_record), "VERIFIED")

if __name__ == "__main__":
    unittest.main()
