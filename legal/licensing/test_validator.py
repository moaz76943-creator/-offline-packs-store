import unittest
from legal.licensing.validator import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()

    def test_missing_author_blocked(self):
        record = {
            "source_id": "test_001",
            "license": {"declared": "MIT", "evidence": "URL"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_missing_license_blocked(self):
        record = {
            "source_id": "test_001",
            "author": "Alice",
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_missing_source_identity_blocked(self):
        record = {
            "author": "Alice",
            "license": {"declared": "MIT", "evidence": "URL"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_inferred_public_domain_blocked(self):
        record = {
            "source_id": "test_002",
            "author": "Bob",
            "license": {"declared": "Public Domain"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_verified_public_domain(self):
        record = {
            "source_id": "test_002",
            "author": "Bob",
            "license": {"declared": "Public Domain", "evidence": "Link to PD dedication"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "VERIFIED")

    def test_incomplete_cc_by_sa_obligations(self):
        record = {
            "source_id": "test_003",
            "author": "Charlie",
            "license": {"declared": "CC BY-SA 4.0", "evidence": "Link"},
            "modification_status": "modified",
            "obligations_met": False
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_complete_cc_by_sa_obligations(self):
        record = {
            "source_id": "test_003",
            "author": "Charlie",
            "license": {"declared": "CC BY-SA 4.0", "evidence": "Link"},
            "modification_status": "modified",
            "obligations_met": True
        }
        self.assertEqual(self.validator.validate(record), "VERIFIED")

    def test_gfdl_provenance_missing(self):
        record = {
            "source_id": "test_004",
            "author": "Dave",
            "license": {"declared": "GFDL"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "BLOCKED")

    def test_gfdl_provenance_present(self):
        record = {
            "source_id": "test_004",
            "author": "Dave",
            "license": {"declared": "GFDL", "evidence": "History link"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "VERIFIED")

    def test_uncertain_combinations(self):
        record = {
            "source_id": "test_005",
            "author": "Eve",
            "license": {"declared": "MIT and CC BY-SA", "evidence": "Link"},
            "modification_status": "original",
            "obligations_met": True
        }
        self.assertEqual(self.validator.validate(record), "REVIEW_REQUIRED")

        record2 = {
            "source_id": "test_006",
            "author": "Eve",
            "license": {"declared": "GPL+MIT", "evidence": "Link"},
            "modification_status": "original",
            "obligations_met": True
        }
        self.assertEqual(self.validator.validate(record2), "REVIEW_REQUIRED")

    def test_valid_mit_record(self):
        record = {
            "source_id": "test_007",
            "author": "Frank",
            "license": {"declared": "MIT"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "VERIFIED")

    def test_valid_bsd_record(self):
        record = {
            "source_id": "test_008",
            "author": "Grace",
            "license": {"declared": "BSD"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "VERIFIED")

    def test_review_required_missing_evidence(self):
        record = {
            "source_id": "test_009",
            "author": "Heidi",
            "license": {"declared": "Apache 2.0"},
            "modification_status": "original"
        }
        self.assertEqual(self.validator.validate(record), "REVIEW_REQUIRED")

if __name__ == "__main__":
    unittest.main()
