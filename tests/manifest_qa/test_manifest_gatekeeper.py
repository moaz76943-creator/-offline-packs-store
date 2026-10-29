import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.manifest_gatekeeper import validate_production_pack_eligibility

class TestManifestGatekeeper(unittest.TestCase):
    def setUp(self):
        self.approved_sources = {'kaikki_de_approved', 'tatoeba_cc0_sample'}

    def test_compliant_production_pack_qualifies(self):
        valid_pack = {
            'pack_id': 'de_ar_a1',
            'production_ready': True,
            'status': 'production',
            'sha256': 'a' * 64,
            'source_id': 'kaikki_de_approved',
            'size_bytes': 1048576,
            'vocabulary_count': 500,
        }
        ok, msg = validate_production_pack_eligibility(valid_pack, self.approved_sources)
        self.assertTrue(ok)
        self.assertEqual(msg, "PRODUCTION_QUALIFIED")

    def test_missing_sha256_is_blocked(self):
        pack = {
            'pack_id': 'de_bad_hash',
            'production_ready': True,
            'sha256': '',
            'source_id': 'kaikki_de_approved',
            'size_bytes': 1000,
            'vocabulary_count': 100,
        }
        ok, msg = validate_production_pack_eligibility(pack, self.approved_sources)
        self.assertFalse(ok)
        self.assertIn("REJECTED_PRODUCTION", msg)
        self.assertIn("SHA256", msg)

    def test_unapproved_source_is_blocked(self):
        pack = {
            'pack_id': 'de_unlicensed',
            'production_ready': True,
            'sha256': 'b' * 64,
            'source_id': 'random_unapproved_scrape',
            'size_bytes': 1000,
            'vocabulary_count': 100,
        }
        ok, msg = validate_production_pack_eligibility(pack, self.approved_sources)
        self.assertFalse(ok)
        self.assertIn("not APPROVED in legal ledger", msg)

if __name__ == "__main__":
    unittest.main()
