import unittest
from legal.licensing.ledger import LedgerAPI

class TestLedgerAPI(unittest.TestCase):
    def setUp(self):
        self.api = LedgerAPI()

    def test_missing_author_is_blocked(self):
        record = {
            "source_id": "test-1",
            "license": "Public Domain",
            "public_domain_proof": {
                "jurisdiction": "US",
                "legal_basis": "zero_copyright",
                "work_date": "1900"
            }
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_missing_license_is_blocked(self):
        record = {
            "source_id": "test-1",
            "author": "Alice"
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_incomplete_cc_by_sa_blocked(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "CC BY-SA"
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_complete_cc_by_sa_verified(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "CC BY-SA",
            "license_evidence": "url/to/evidence"
        }
        self.assertEqual(self.api.validate_record(record), "verified")

    def test_gfdl_provenance_verified(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "GFDL",
            "license_evidence": "url/to/evidence"
        }
        self.assertEqual(self.api.validate_record(record), "verified")

    def test_missing_gfdl_provenance_blocked(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "GFDL"
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_missing_public_domain_proof_blocked(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "Public Domain"
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_incomplete_public_domain_proof_blocked(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "Public Domain",
            "public_domain_proof": {
                "jurisdiction": "US"
            }
        }
        self.assertEqual(self.api.validate_record(record), "blocked")

    def test_complete_public_domain_verified(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "Public Domain",
            "public_domain_proof": {
                "jurisdiction": "US",
                "legal_basis": "zero_copyright",
                "work_date": "1900"
            }
        }
        self.assertEqual(self.api.validate_record(record), "verified")

    def test_unknown_license_review_required(self):
        record = {
            "source_id": "test-1",
            "author": "Alice",
            "license": "Custom License"
        }
        self.assertEqual(self.api.validate_record(record), "reviewRequired")

    def test_mixed_provenance_cc_by_sa_and_gfdl_review_required(self):
        records = [
            {
                "source_id": "test-1",
                "author": "Alice",
                "license": "CC BY-SA",
                "license_evidence": "url"
            },
            {
                "source_id": "test-2",
                "author": "Bob",
                "license": "GFDL",
                "license_evidence": "url"
            }
        ]
        self.assertEqual(self.api.evaluate_mixed_provenance(records), "reviewRequired")

    def test_mixed_provenance_all_verified(self):
        records = [
            {
                "source_id": "test-1",
                "author": "Alice",
                "license": "CC BY-SA",
                "license_evidence": "url"
            },
            {
                "source_id": "test-2",
                "author": "Bob",
                "license": "CC BY-SA",
                "license_evidence": "url"
            }
        ]
        self.assertEqual(self.api.evaluate_mixed_provenance(records), "verified")

    def test_mixed_provenance_one_blocked(self):
        records = [
            {
                "source_id": "test-1",
                "author": "Alice",
                "license": "CC BY-SA",
                "license_evidence": "url"
            },
            {
                "source_id": "test-2",
                "author": "Bob"
            }
        ]
        self.assertEqual(self.api.evaluate_mixed_provenance(records), "blocked")

if __name__ == '__main__':
    unittest.main()
