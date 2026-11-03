"""Tests for the LicensingValidator."""
import unittest
from legal.licensing.validator import LicensingValidator

class TestLicensingValidator(unittest.TestCase):

    def setUp(self):
        self.validator = LicensingValidator()
        self.valid_record = {
            "source_id": "test_src_1",
            "url": "https://example.com/source",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license",
                "evidence_sha256": "a" * 64
            },
            "modification_status": "none",
            "artifact_hash": "b" * 64,
            "verified_evidence": True
        }

    def test_missing_attributions(self):
        # Missing author
        record = self.valid_record.copy()
        del record['author']
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

        # Missing license
        record = self.valid_record.copy()
        del record['license']
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

        # Missing source_id
        record = self.valid_record.copy()
        del record['source_id']
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

    def test_changed_source_versions(self):
        # Missing version (blocks it)
        record = self.valid_record.copy()
        del record['version']
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

    def test_incomplete_cc_by_sa(self):
        record = self.valid_record.copy()
        record['license'] = {'id': 'CC-BY-SA-4.0'} # Missing evidence
        record['verified_evidence'] = False
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

    def test_gfdl_provenance(self):
        record = self.valid_record.copy()
        record['license'] = {
            'id': 'GFDL-1.3-only',
            'evidence_url': 'https://example.com/gfdl',
            'evidence_sha256': 'c' * 64
        }
        self.assertEqual(self.validator.evaluate_record(record), 'verified')

        # Missing evidence
        record['license'] = {'id': 'GFDL-1.3-only'}
        record['verified_evidence'] = False
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')

    def test_no_inferred_public_domain(self):
        record = self.valid_record.copy()
        record['license'] = {} # Missing id

        # Validation should fail (and thus evaluation is 'blocked')
        self.assertEqual(self.validator.evaluate_record(record), 'blocked')
        with self.assertRaisesRegex(ValueError, "Public Domain cannot be inferred"):
            self.validator.validate_record(record)

    def test_uncertain_combinations(self):
        # In a single record, dual license string should require review
        record = self.valid_record.copy()
        record['license'] = {'id': 'GFDL-1.3-only and CC-BY-SA-4.0', 'evidence_url': 'url'}
        self.assertEqual(self.validator.evaluate_record(record), 'reviewRequired')

        # Across a release
        gfdl_record = self.valid_record.copy()
        gfdl_record['source_id'] = 'src2'
        gfdl_record['license'] = {'id': 'GFDL-1.3-only', 'evidence_url': 'url', 'evidence_sha256': 'c'*64}

        release = [self.valid_record, gfdl_record]
        self.assertEqual(self.validator.evaluate_release(release), 'reviewRequired')

    def test_verified_evidence_required_for_verified_status(self):
        record = self.valid_record.copy()
        record['verified_evidence'] = False
        # If it has evidence but not verified flag, it needs review
        self.assertEqual(self.validator.evaluate_record(record), 'reviewRequired')

        record['verified_evidence'] = True
        self.assertEqual(self.validator.evaluate_record(record), 'verified')

if __name__ == '__main__':
    unittest.main()
