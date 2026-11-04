import unittest
from legal.licensing.validator import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()
        self.valid_record_base = {
            "source_id": "test_src_01",
            "url": "https://example.com/data",
            "author": "Test Author",
            "version": "1.0",
            "modification_status": "unmodified",
            "artifact_hash": "a" * 64,
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence": {
                    "id": "CC-BY-SA-4.0",
                    "url": "https://example.com/license",
                    "path": "LICENSE.txt",
                    "sha256": "b" * 64
                }
            }
        }

    def test_missing_attributions(self):
        # Missing author
        record = self.valid_record_base.copy()
        record["author"] = ""
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("author cannot be empty" in issue for issue in result["issues"]))

        # Missing URL for CC-BY-SA
        record = self.valid_record_base.copy()
        record["url"] = ""
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("requires a source URL" in issue for issue in result["issues"]))

    def test_changed_source_versions(self):
        # While the validator checks single records, an external system would diff versions.
        # Ensure version is present and required.
        record = self.valid_record_base.copy()
        del record["version"]
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Missing required field: version" in issue for issue in result["issues"]))

    def test_incomplete_cc_by_sa_obligations(self):
        record = self.valid_record_base.copy()
        record["author"] = "Unknown"
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("requires explicit attribution (author)" in issue for issue in result["issues"]))

    def test_gfdl_provenance(self):
        record = self.valid_record_base.copy()
        record["license"]["evidence"]["id"] = "GFDL-1.3-only"
        record["url"] = ""
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("GFDL requires a source URL" in issue for issue in result["issues"]))

    def test_mixed_source_provenance(self):
        record1 = self.valid_record_base.copy()
        record2 = self.valid_record_base.copy()
        record2["source_id"] = "test_src_02"
        record2["license"] = {
            "declared": "GFDL 1.3",
            "evidence": {
                "id": "GFDL-1.3-only"
            }
        }

        result = self.validator.evaluate_mixed_provenance([record1, record2])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn("reason", result)
        self.assertEqual(result["reason"], "Legally uncertain combinations are treated as review required.")
        self.assertTrue(any("Mixed copyleft licenses detected" in issue for issue in result["issues"]))

    def test_missing_license(self):
        record = self.valid_record_base.copy()
        record["license"]["declared"] = ""
        record["license"]["evidence"]["id"] = "PUBLIC-DOMAIN"
        result = self.validator.validate_record(record)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Public Domain status cannot be inferred from a missing declared license" in issue for issue in result["issues"]))

    def test_valid_record(self):
        result = self.validator.validate_record(self.valid_record_base)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(len(result["issues"]), 0)

if __name__ == '__main__':
    unittest.main()
