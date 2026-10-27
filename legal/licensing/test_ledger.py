import unittest
from legal.licensing.ledger import LicensingLedgerValidator

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.validator = LicensingLedgerValidator()

    def test_valid_record(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": True
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "verified")

    def test_missing_author_blocks(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": True
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_missing_license_evidence_blocks(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": False
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_incomplete_cc_by_sa(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": False  # Missing share_alike
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_incomplete_gfdl(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "GFDL-1.3-only",
                "verified_evidence": {
                    "id": "GFDL-1.3-only",
                    "obligations_met": True,
                    "history_preserved": False  # Missing history
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_mixed_sources_uncertain(self):
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": True
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified",
            "mixed_sources": ["src-2-gfdl"]
        }
        self.assertEqual(self.validator.evaluate_record(record), "reviewRequired")

    def test_public_domain_inference_prevented(self):
        # Public domain missing evidence
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "PUBLIC-DOMAIN",
                "verified_evidence": {
                    "id": "PUBLIC-DOMAIN",
                    "obligations_met": True
                    # Missing public_domain_evidence
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "verified"
        }
        self.assertEqual(self.validator.evaluate_record(record), "blocked")

    def test_review_required_preserved(self):
        # Even if currently verifiable, if it was manually marked reviewRequired, keep it
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "1.0",
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": True
                }
            },
            "modification_status": "unmodified",
            "redistribution_eligibility": "reviewRequired"
        }

        ledger_data = {"records": [record]}
        processed = self.validator.process_ledger(ledger_data)
        self.assertEqual(processed[0]["redistribution_eligibility"], "reviewRequired")

    def test_invalid_schema(self):
        ledger_data = {
            "records": [
                {
                    "source_id": "src-1"
                    # Missing all other required fields
                }
            ]
        }
        with self.assertRaises(ValueError):
            self.validator.process_ledger(ledger_data)

if __name__ == '__main__':
    unittest.main()

    def test_changed_source_versions(self):
        # Even if verifiable, if version changed significantly or artifact_hash implies a drift,
        # it should be handled. For now, testing schema validation of version.
        record = {
            "source_id": "src-1",
            "url": "https://example.com",
            "author": "Author One",
            "version": "", # Missing version
            "license": {
                "declaration": "CC-BY-SA-4.0",
                "verified_evidence": {
                    "id": "CC-BY-SA-4.0",
                    "obligations_met": True,
                    "attribution_provided": True,
                    "share_alike_preserved": True
                }
            },
            "modification_status": "changed",
            "redistribution_eligibility": "verified"
        }
        ledger_data = {"records": [record]}
        with self.assertRaises(ValueError):
            self.validator.process_ledger(ledger_data)
