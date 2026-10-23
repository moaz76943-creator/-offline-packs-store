import unittest
from legal.licensing.ledger import LicensingLedger, LEDGER_SCHEMA

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.ledger = LicensingLedger()

    def test_missing_attributions(self):
        with self.assertRaises(ValueError):
            self.ledger.add({
                "source_id": "s1", "url": "http", "version": "1",
                "author": "", "license": {"id": "CC0-1.0", "verified_evidence": True}
            })

    def test_changed_source_versions(self):
        self.ledger.add({
            "source_id": "s1", "url": "http", "version": "1", "modification_status": "changed",
            "author": "a", "license": {"id": "CC-BY-SA-4.0", "verified_evidence": True, "obligations_met": True}
        })
        self.assertEqual(self.ledger.evaluate(["s1"]), "verified")

    def test_incomplete_cc_by_sa_obligations(self):
        self.ledger.add({
            "source_id": "s1", "url": "http", "version": "1",
            "author": "a", "license": {"id": "CC-BY-SA-4.0", "verified_evidence": True, "obligations_met": False}
        })
        self.assertEqual(self.ledger.evaluate(["s1"]), "blocked")

    def test_gfdl_provenance(self):
        self.ledger.add({
            "source_id": "s1", "url": "http", "version": "1",
            "author": "a", "license": {"id": "GFDL-1.3-only", "verified_evidence": True, "obligations_met": True}
        })
        self.assertEqual(self.ledger.evaluate(["s1"]), "verified")

    def test_mixed_copyleft(self):
        self.ledger.add({
            "source_id": "s1", "url": "http", "version": "1",
            "author": "a", "license": {"id": "CC-BY-SA-4.0", "verified_evidence": True, "obligations_met": True}
        })
        self.ledger.add({
            "source_id": "s2", "url": "http", "version": "1",
            "author": "a", "license": {"id": "GFDL-1.3-only", "verified_evidence": True, "obligations_met": True}
        })
        self.assertEqual(self.ledger.evaluate(["s1", "s2"]), "reviewRequired")

    def test_public_domain_inference(self):
        with self.assertRaises(ValueError):
            self.ledger.add({
                "source_id": "s1", "url": "http", "version": "1",
                "author": "a", "license": {"id": "PUBLIC-DOMAIN", "verified_evidence": False}
            })

    def test_missing_license(self):
        with self.assertRaises(ValueError):
            self.ledger.add({
                "source_id": "s1", "url": "http", "version": "1",
                "author": "a"
            })

    def test_unknown_license(self):
        with self.assertRaises(ValueError):
            self.ledger.add({
                "source_id": "s1", "url": "http", "version": "1",
                "author": "a", "license": {"id": "UNKNOWN", "verified_evidence": True}
            })

if __name__ == '__main__':
    unittest.main()
