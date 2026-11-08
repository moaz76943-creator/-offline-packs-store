import unittest
from validator import LicensingValidator

class TestLicensingValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingValidator()
        self.valid_record = {
            "source_id": "src-123",
            "url": "http://example.com",
            "author": "Alice",
            "version": "1.0",
            "license": {
                "declaration": "CC BY-SA 4.0",
                "verified_evidence": "URL to CC BY-SA license page",
                "obligations": {
                    "attribution_met": True,
                    "share_alike_met": True
                }
            },
            "modification_status": "unmodified"
        }

    def test_valid_record(self):
        self.assertEqual(self.validator.evaluate(self.valid_record), "verified")

    def test_artifact_hash_optional(self):
        # The schema shouldn't strictly require artifact hash.
        # Here we don't have it and it's valid.
        record = self.valid_record.copy()
        self.assertEqual(self.validator.evaluate(record), "verified")

    def test_missing_author(self):
        record = self.valid_record.copy()
        del record["author"]
        self.assertEqual(self.validator.evaluate(record), "blocked")

    def test_empty_author(self):
        record = self.valid_record.copy()
        record["author"] = "  "
        self.assertEqual(self.validator.evaluate(record), "blocked")

    def test_missing_license(self):
        record = self.valid_record.copy()
        del record["license"]
        self.assertEqual(self.validator.evaluate(record), "blocked")

    def test_gfdl_cc_by_sa_combination(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declaration": "GFDL and CC BY-SA 4.0",
            "verified_evidence": "Link to GFDL and CC BY-SA 4.0"
        }
        self.assertEqual(self.validator.evaluate(record), "reviewRequired")

    def test_unknown_license(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declaration": "Some Weird License",
            "verified_evidence": "Trust me"
        }
        self.assertEqual(self.validator.evaluate(record), "reviewRequired")

    def test_changed_source_versions(self):
        record = self.valid_record.copy()
        record["version"] = ""
        self.assertEqual(self.validator.evaluate(record), "blocked")

    def test_incomplete_cc_by_sa_obligations(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declaration": "CC BY-SA 4.0",
            "verified_evidence": "URL",
            "obligations": {
                "attribution_met": False,
                "share_alike_met": True
            }
        }
        self.assertEqual(self.validator.evaluate(record), "reviewRequired")

    def test_gfdl_provenance(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declaration": "GFDL",
            "verified_evidence": "GFDL provenance verified",
            "obligations": {
                "history_preserved": True
            }
        }
        self.assertEqual(self.validator.evaluate(record), "verified")

    def test_never_infer_public_domain(self):
        record = self.valid_record.copy()
        record["license"] = {
            "declaration": "",
            "verified_evidence": ""
        }
        # If no license is specified, it should block. It does not default to public domain.
        self.assertEqual(self.validator.evaluate(record), "blocked")

if __name__ == '__main__':
    unittest.main()
