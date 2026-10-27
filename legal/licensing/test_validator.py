import unittest
from pathlib import Path
from legal.licensing.validator import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()

    def get_valid_record(self):
        return {
            "source_id": "src_01",
            "url": "https://example.com/src",
            "author": "John Doe",
            "version": "1.0",
            "modification_status": "unchanged",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence": {
                    "licenses": ["CC-BY-SA-4.0"],
                    "obligations_met": {
                        "attribution": True,
                        "share_alike": True,
                        "notice": True
                    }
                }
            }
        }

    def test_missing_attributions(self):
        record = self.get_valid_record()
        record["license"]["evidence"]["obligations_met"]["attribution"] = False
        result = self.validator.validate_record(record)
        self.assertEqual(result, "BLOCKED")

    def test_changed_missing_source_versions(self):
        record = self.get_valid_record()
        del record["version"]
        result = self.validator.validate_record(record)
        self.assertEqual(result, "BLOCKED")

    def test_incomplete_cc_by_sa_obligations(self):
        record = self.get_valid_record()
        record["license"]["evidence"]["obligations_met"]["share_alike"] = False
        result = self.validator.validate_record(record)
        self.assertEqual(result, "BLOCKED")

    def test_gfdl_provenance(self):
        record = self.get_valid_record()
        record["license"]["declared"] = "GFDL-1.3-only"
        record["license"]["evidence"]["licenses"] = ["GFDL-1.3-only"]
        result = self.validator.validate_record(record)
        self.assertEqual(result, "VERIFIED")

    def test_legally_uncertain_combinations(self):
        record = self.get_valid_record()
        record["license"]["declared"] = "GFDL-1.3-only"
        record["license"]["evidence"]["licenses"] = ["GFDL-1.3-only", "CC-BY-SA-4.0"]
        result = self.validator.validate_record(record)
        self.assertEqual(result, "REVIEW_REQUIRED")

    def test_inferred_public_domain_blocked(self):
        record = self.get_valid_record()
        del record["license"]["declared"]
        record["license"]["evidence"]["licenses"] = ["PUBLIC-DOMAIN"]
        result = self.validator.validate_record(record)
        self.assertEqual(result, "BLOCKED")

    def test_successfully_verified_record(self):
        record = self.get_valid_record()
        result = self.validator.validate_record(record)
        self.assertEqual(result, "VERIFIED")

if __name__ == '__main__':
    unittest.main()
