import unittest
import json
from legal.licensing.validator import LicensingLedgerValidator
import os

class TestLicensingLedgerValidator(unittest.TestCase):
    def setUp(self):
        # We need to construct a robust validator
        self.validator = LicensingLedgerValidator()

    def test_missing_attribution(self):
        record = {
            "source_id": "test_1",
            "url": "https://example.com/test",
            "version": "1.0",
            "license": {
                "declared": "CC BY 4.0",
                "evidence": "CC BY 4.0"
            },
            "modification_status": "unmodified"
            # Missing author
        }
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_changed_source_version(self):
        # Let's say a schema requires version and it's omitted
        record = {
            "source_id": "test_2",
            "url": "https://example.com/test",
            "author": "Alice",
            "license": {
                "declared": "CC BY 4.0",
                "evidence": "CC BY 4.0"
            },
            "modification_status": "unmodified"
            # Missing version
        }
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

    def test_incomplete_cc_by_sa(self):
        record = {
            "source_id": "test_3",
            "url": "https://example.com/test",
            "author": "Bob",
            "version": "1.0",
            "license": {
                "declared": "CC BY-SA 3.0",
                "evidence": "CC BY 3.0" # Evidence differs from declaration
            },
            "modification_status": "derivative"
        }
        self.assertEqual(self.validator.validate_record(record), "REVIEW_REQUIRED")

    def test_gfdl_provenance(self):
        record = {
            "source_id": "test_4",
            "url": "https://example.com/test",
            "author": "Charlie",
            "version": "1.0",
            "license": {
                "declared": "GFDL",
                "evidence": "GFDL"
            },
            "modification_status": "derivative"
        }
        # In a real scenario, this might be valid or REVIEW_REQUIRED if complex
        self.assertEqual(self.validator.validate_record(record), "VERIFIED")

    def test_inferred_public_domain(self):
        record = {
            "source_id": "test_5",
            "url": "https://example.com/test",
            "author": "Dave",
            "version": "1.0",
            "license": {
                "declared": "Public Domain",
                "evidence": "" # No evidence!
            },
            "modification_status": "unmodified"
        }
        self.assertEqual(self.validator.validate_record(record), "BLOCKED")

        record2 = {
            "source_id": "test_6",
            "url": "https://example.com/test",
            "author": "Dave",
            "version": "1.0",
            "license": {
                "declared": "Public Domain",
                "evidence": "Public Domain"
            },
            "modification_status": "unmodified"
        }
        self.assertEqual(self.validator.validate_record(record2), "VERIFIED")

    def test_valid_record(self):
        record = {
            "source_id": "test_7",
            "url": "https://example.com/test",
            "author": "Eve",
            "version": "1.0",
            "license": {
                "declared": "MIT",
                "evidence": "MIT"
            },
            "modification_status": "unmodified"
        }
        self.assertEqual(self.validator.validate_record(record), "VERIFIED")

    def test_uncertain_copyleft(self):
        record = {
            "source_id": "test_8",
            "url": "https://example.com/test",
            "author": "Eve",
            "version": "1.0",
            "license": {
                "declared": "CC BY-SA",
                "evidence": "CC BY-SA" # Same, but is derivative so might require review
            },
            "modification_status": "derivative"
        }
        self.assertEqual(self.validator.validate_record(record), "REVIEW_REQUIRED")

if __name__ == '__main__':
    unittest.main()
