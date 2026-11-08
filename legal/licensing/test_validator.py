import unittest
from validator import LicensingValidator

class TestLicensingValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingValidator()
        self.valid_record = {
            'source_id': 'dict-en-es',
            'url': 'https://example.com/dict',
            'author': 'Example Org',
            'version': '1.0',
            'license': 'CC BY-SA 4.0',
            'modification_status': 'modified',
            'verified_evidence': {
                'license_text_found': True,
                'attribution_found': True
            }
        }

    def test_valid_record(self):
        self.assertEqual(self.validator.validate_record(self.valid_record), 'verified')

    def test_missing_author(self):
        record = self.valid_record.copy()
        del record['author']
        self.assertEqual(self.validator.validate_record(record), 'blocked')

        record['author'] = ''
        self.assertEqual(self.validator.validate_record(record), 'blocked')

        record['author'] = '___MISSING_AUTHOR___'
        self.assertEqual(self.validator.validate_record(record), 'blocked')

    def test_missing_license(self):
        record = self.valid_record.copy()
        del record['license']
        self.assertEqual(self.validator.validate_record(record), 'blocked')

        record['license'] = ''
        self.assertEqual(self.validator.validate_record(record), 'blocked')

    def test_missing_source_id(self):
        record = self.valid_record.copy()
        del record['source_id']
        self.assertEqual(self.validator.validate_record(record), 'blocked')

    def test_unknown_license(self):
        record = self.valid_record.copy()
        record['license'] = 'Unknown License 1.0'
        self.assertEqual(self.validator.validate_record(record), 'blocked')

    def test_missing_verified_evidence(self):
        record = self.valid_record.copy()
        del record['verified_evidence']
        self.assertEqual(self.validator.validate_record(record), 'reviewRequired')

    def test_incomplete_verified_evidence(self):
        record = self.valid_record.copy()
        record['verified_evidence'] = {'license_text_found': True, 'attribution_found': False}
        self.assertEqual(self.validator.validate_record(record), 'reviewRequired')

        record['verified_evidence'] = {'license_text_found': False, 'attribution_found': True}
        self.assertEqual(self.validator.validate_record(record), 'reviewRequired')

    def test_evaluate_release_verified(self):
        self.assertEqual(self.validator.evaluate_release([self.valid_record]), 'verified')

    def test_evaluate_release_blocked(self):
        invalid_record = self.valid_record.copy()
        del invalid_record['author']
        self.assertEqual(self.validator.evaluate_release([self.valid_record, invalid_record]), 'blocked')

    def test_evaluate_release_review_required(self):
        review_record = self.valid_record.copy()
        del review_record['verified_evidence']
        self.assertEqual(self.validator.evaluate_release([self.valid_record, review_record]), 'reviewRequired')

    def test_mixed_cc_by_sa_and_gfdl(self):
        record2 = self.valid_record.copy()
        record2['source_id'] = 'dict2'
        record2['license'] = 'GFDL-1.3'
        self.assertEqual(self.validator.evaluate_release([self.valid_record, record2]), 'reviewRequired')

    def test_empty_release(self):
        self.assertEqual(self.validator.evaluate_release([]), 'blocked')

if __name__ == '__main__':
    unittest.main()

    def test_changed_source_version(self):
        record1 = self.valid_record.copy()
        record2 = self.valid_record.copy()
        record2['version'] = '2.0'
        # Both are valid, but testing version tracking
        self.assertEqual(self.validator.validate_record(record1), 'verified')
        self.assertEqual(self.validator.validate_record(record2), 'verified')
