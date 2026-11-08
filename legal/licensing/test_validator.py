import unittest
import sys
from pathlib import Path

# Ensure the root directory is in sys.path to resolve imports properly if run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from legal.licensing.validator import LicensingValidator

class TestLicensingValidatorBasic(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingValidator()
        self.valid_record = {
            "source_id": "test-1",
            "url": "https://example.com/test",
            "author": "Test Author",
            "version": "1.0",
            "modification_status": "unmodified",
            "artifact_hash": "a" * 64,
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "evidence": {
                    "attribution": True,
                    "share_alike": True
                }
            },
            "status": "verified"
        }

    def test_missing_author(self):
        record = dict(self.valid_record)
        record["author"] = ""
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_missing_license(self):
        record = dict(self.valid_record)
        del record["license"]
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_missing_source_identity(self):
        record = dict(self.valid_record)
        record["source_id"] = ""
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_never_infer_public_domain(self):
        record = dict(self.valid_record)
        record["license"] = {
            "declaration": "PUBLIC-DOMAIN",
            "evidence": {} # Missing explicit public domain proof
        }
        # It must not automatically assume PD, it needs review
        self.assertEqual(self.validator.evaluate_record(record), "reviewRequired")

class TestLicensingValidatorComplex(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingValidator()
        self.valid_record = {
            "source_id": "test-1",
            "url": "https://example.com/test",
            "author": "Test Author",
            "version": "1.0",
            "modification_status": "unmodified",
            "artifact_hash": "a" * 64,
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "evidence": {
                    "attribution": True,
                    "share_alike": True
                }
            },
            "status": "verified"
        }

    def test_incomplete_cc_by_sa_obligations(self):
        record = dict(self.valid_record)
        record["license"] = {
            "declaration": "CC-BY-SA-4.0",
            "evidence": {
                "attribution": True,
                "share_alike": False
            }
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

        record["license"]["evidence"] = {
            "attribution": False,
            "share_alike": True
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_missing_gfdl_provenance(self):
        record = dict(self.valid_record)
        record["license"] = {
            "declaration": "GFDL-1.3-only",
            "evidence": {} # Missing gfdl_history
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_changed_source_versions(self):
        old_record = dict(self.valid_record)
        new_record = dict(self.valid_record)
        new_record["version"] = "2.0"

        self.assertEqual(self.validator.evaluate_record(new_record, old_record), "reviewRequired")

        new_record = dict(self.valid_record)
        new_record["artifact_hash"] = "b" * 64
        self.assertEqual(self.validator.evaluate_record(new_record, old_record), "reviewRequired")

    def test_legally_uncertain_combinations(self):
        cc_record = dict(self.valid_record)
        gfdl_record = dict(self.valid_record)
        gfdl_record["source_id"] = "test-2"
        gfdl_record["license"] = {
            "declaration": "GFDL-1.3-only",
            "evidence": {
                "gfdl_history": True
            }
        }

        self.assertEqual(self.validator.evaluate_release([cc_record, gfdl_record]), "reviewRequired")

        cc_only_release = [cc_record]
        self.assertEqual(self.validator.evaluate_release(cc_only_release), "verified")

if __name__ == "__main__":
    unittest.main()
