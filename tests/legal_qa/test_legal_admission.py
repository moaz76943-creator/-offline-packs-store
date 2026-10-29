import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.admission.legal_admission_validator import validate_source_entry

class TestLegalSourceAdmission(unittest.TestCase):
    def test_complete_approved_source_is_admitted(self):
        valid_source = {
            'source_id': 'kaikki_de_ar_sample',
            'canonical_url': 'https://kaikki.org/dictionary/German/',
            'publisher': 'Tatu Ylonen',
            'license_id': 'CC-BY-SA-4.0',
            'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
            'allowed_uses': ['educational', 'commercial', 'derivative'],
            'attribution_required': True,
            'source_sha256': 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
            'license_evidence_sha256': 'f9e8d7c6b5a40312918273645564738291029384756102938475610293847561',
            'review_decision': 'APPROVED',
            'retrieval_date': '2026-10-25',
        }
        admitted, msg = validate_source_entry(valid_source)
        self.assertTrue(admitted)
        self.assertEqual(msg, "ADMITTED")

    def test_missing_evidence_hash_quarantined(self):
        invalid_source = {
            'source_id': 'unverified_data',
            'canonical_url': 'https://example.org',
            'license_id': 'CC-BY-4.0',
            'review_decision': 'APPROVED',
            # Missing source_sha256, license_evidence_sha256, etc.
        }
        admitted, msg = validate_source_entry(invalid_source)
        self.assertFalse(admitted)
        self.assertIn("QUARANTINED", msg)

    def test_non_approved_review_quarantined(self):
        pending_source = {
            'source_id': 'pending_candidate',
            'canonical_url': 'https://example.org',
            'publisher': 'Unknown',
            'license_id': 'CC0-1.0',
            'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
            'allowed_uses': ['all'],
            'attribution_required': False,
            'source_sha256': '1111111111111111111111111111111111111111111111111111111111111111',
            'license_evidence_sha256': '2222222222222222222222222222222222222222222222222222222222222222',
            'review_decision': 'PENDING_REVIEW',
            'retrieval_date': '2026-10-28',
        }
        admitted, msg = validate_source_entry(pending_source)
        self.assertFalse(admitted)
        self.assertIn("QUARANTINED", msg)

if __name__ == "__main__":
    unittest.main()
