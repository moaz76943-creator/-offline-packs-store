import unittest
import os
import sys

# Ensure the repository root is in the path to allow absolute imports
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from legal.licensing.ledger import LicensingLedger

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.ledger = LicensingLedger()
        self.valid_source = {
            'source_id': 'test-src-1',
            'url': 'https://example.com',
            'author': 'Test Author',
            'version': '1.0',
            'modification_status': 'none',
            'license': {
                'id': 'CC0-1.0',
                'evidence_url': 'https://example.com/license',
                'evidence_hash': 'a' * 64,
            }
        }
        self.valid_copyleft = {
            'source_id': 'test-src-2',
            'url': 'https://example.com',
            'author': 'Test Author',
            'version': '1.0',
            'modification_status': 'none',
            'license': {
                'id': 'CC-BY-SA-4.0',
                'evidence_url': 'https://example.com/license',
                'evidence_hash': 'b' * 64,
            },
            'compliance': {
                'attribution': True,
                'license_link': True,
                'changes_disclosed': True,
                'sharealike': True,
                'no_additional_restrictions': True
            }
        }

    def test_schema_missing_fields(self):
        # Missing author
        invalid_source = self.valid_source.copy()
        del invalid_source['author']
        is_valid, msg = self.ledger.validate_schema(invalid_source)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: author", msg)

        # Missing license
        invalid_source = self.valid_source.copy()
        del invalid_source['license']
        is_valid, msg = self.ledger.validate_schema(invalid_source)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: license", msg)

        # Missing source_id
        invalid_source = self.valid_source.copy()
        del invalid_source['source_id']
        is_valid, msg = self.ledger.validate_schema(invalid_source)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field: source_id", msg)

    def test_missing_attributions(self):
        # Missing author tests evaluating sources
        invalid_source = self.valid_source.copy()
        invalid_source['author'] = ''
        status, issues = self.ledger.evaluate_sources([invalid_source])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Empty required field: author" in issue for issue in issues))

    def test_incomplete_cc_by_sa_obligations(self):
        invalid_source = self.valid_copyleft.copy()
        invalid_source['compliance'] = {
            'attribution': True,
            # Missing other obligations
        }
        status, issues = self.ledger.evaluate_sources([invalid_source])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Incomplete obligation sharealike" in issue for issue in issues))

    def test_invalid_copyleft_mixtures(self):
        source_gfdl = {
            'source_id': 'test-src-gfdl',
            'url': 'https://example.com',
            'author': 'Test Author',
            'version': '1.0',
            'modification_status': 'none',
            'license': {
                'id': 'GFDL-1.3-only',
                'evidence_url': 'https://example.com/license',
                'evidence_hash': 'c' * 64,
            },
            'compliance': {
                'license_copy': True,
                'copyright_notices': True,
                'history': True,
                'invariant_sections_checked': True,
                'cover_texts_checked': True,
                'transparent_copy_checked': True
            }
        }
        status, issues = self.ledger.evaluate_sources([self.valid_copyleft, source_gfdl])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Invalid copyleft mixture" in issue for issue in issues))

    def test_gfdl_provenance(self):
        source_gfdl = {
            'source_id': 'test-src-gfdl',
            'url': 'https://example.com',
            'author': 'Test Author',
            'version': '1.0',
            'modification_status': 'none',
            'license': {
                'id': 'GFDL-1.3-only',
                'evidence_url': 'https://example.com/license',
                'evidence_hash': 'c' * 64,
            },
            'compliance': {
                'license_copy': True,
                'copyright_notices': True,
                'history': True,
                'invariant_sections_checked': True,
                'cover_texts_checked': True,
                # Missing transparent_copy_checked
            }
        }
        status, issues = self.ledger.evaluate_sources([source_gfdl])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Incomplete obligation transparent_copy_checked" in issue for issue in issues))

    def test_no_public_domain_inference(self):
        invalid_source = self.valid_source.copy()
        # Invalid missing license id inside the license object
        invalid_source['license'] = {
            'evidence_url': 'https://example.com/license',
            'evidence_hash': 'a' * 64,
        }
        # evaluate_sources will schema fail it first, but let's test specifically the public domain explicitly
        status, issues = self.ledger.evaluate_sources([invalid_source])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Missing required license field: id" in issue for issue in issues))

        invalid_source2 = self.valid_source.copy()
        invalid_source2['license'] = {
            'id': 'PUBLIC-DOMAIN',
            'evidence_url': 'https://example.com/license',
            'evidence_hash': 'a' * 64,
        }
        status, issues = self.ledger.evaluate_sources([invalid_source2])
        self.assertEqual(status, 'blocked')
        self.assertTrue(any("Missing public domain proof" in issue for issue in issues))

    def test_changed_source_versions(self):
        source1 = self.valid_source.copy()
        source2 = self.valid_source.copy()
        source2['source_id'] = 'test-src-2'
        source2['version'] = '2.0'
        # Just verifying valid mixed versions
        status, issues = self.ledger.evaluate_sources([source1, source2])
        self.assertEqual(status, 'verified')
        self.assertEqual(len(issues), 0)

    def test_unknown_license_review_required(self):
        source = self.valid_source.copy()
        source['license'] = {
            'id': 'UNKNOWN-LICENSE',
            'evidence_url': 'https://example.com/license',
            'evidence_hash': 'a' * 64,
        }
        status, issues = self.ledger.evaluate_sources([source])
        self.assertEqual(status, 'reviewRequired')
        self.assertTrue(any("Unknown license UNKNOWN-LICENSE" in issue for issue in issues))

if __name__ == '__main__':
    unittest.main()
