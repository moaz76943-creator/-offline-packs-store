import unittest
from legal.licensing.validator import LicensingLedgerValidator

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()

    def test_missing_attributions(self):
        # Missing author
        record = {
            "source_id": "src-001",
            "declared_license": "MIT"
        }
        self.assertEqual(self.validator.validate(record), 'BLOCKED')

        # Missing source_id
        record2 = {
            "author": "Alice",
            "declared_license": "MIT"
        }
        self.assertEqual(self.validator.validate(record2), 'BLOCKED')

        # Missing declared_license
        record3 = {
            "source_id": "src-001",
            "author": "Alice"
        }
        self.assertEqual(self.validator.validate(record3), 'BLOCKED')

    def test_valid_record(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "MIT"
        }
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

    def test_inferred_public_domain_blocked(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "Public Domain"
        }
        # Blocked without verified_evidence
        self.assertEqual(self.validator.validate(record), 'BLOCKED')

        record['verified_evidence'] = "https://example.com/pd-proof"
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

    def test_gfdl_provenance(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "GFDL"
        }
        # Blocked without version
        self.assertEqual(self.validator.validate(record), 'BLOCKED')

        record['version'] = "1.3"
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

    def test_incomplete_cc_bysa_obligations(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "CC BY-SA 4.0"
        }
        # Blocked without url or verified_evidence
        self.assertEqual(self.validator.validate(record), 'BLOCKED')

        record['url'] = "https://example.com/source"
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

        del record['url']
        record['verified_evidence'] = "https://example.com/evidence"
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

    def test_uncertain_license_combinations(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "CC BY-SA 4.0",
            "url": "https://example.com/source",
            "mixed_sources": [
                {"source_id": "src-002", "license": "GFDL"}
            ]
        }
        # Mixing CC BY-SA and GFDL should require review
        self.assertEqual(self.validator.validate(record), 'REVIEW_REQUIRED')

    def test_uncertain_copyleft(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "Some copyleft license"
        }
        # Uncertain copyleft without verified evidence
        self.assertEqual(self.validator.validate(record), 'REVIEW_REQUIRED')

    def test_mixed_source_provenance_preservation(self):
        record = {
            "source_id": "src-001",
            "author": "Alice",
            "declared_license": "MIT",
            "mixed_sources": [
                {"source_id": "src-002", "license": "MIT"}
            ]
        }
        self.assertEqual(self.validator.validate(record), 'VERIFIED')

if __name__ == '__main__':
    unittest.main()
