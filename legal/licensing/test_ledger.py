import unittest
from legal.licensing.ledger import LicensingLedger

class TestLicensingLedger(unittest.TestCase):
    def test_missing_author(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            # missing author
            "version": "1.0",
            "license": {"declared": "CC-BY-SA-4.0", "evidence_verified": True},
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_missing_license(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_missing_source_identity(self):
        ledger = LicensingLedger()
        source = {
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {"declared": "CC-BY-SA-4.0", "evidence_verified": True},
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_incomplete_cc_by_sa_obligations(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence_verified": True,
                "obligations": ["attribution"] # missing sharealike, etc
            },
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_public_domain_inference(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "PUBLIC-DOMAIN",
                "evidence_verified": False, # Never infer Public Domain status from a missing license.
            },
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_gfdl_provenance(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "GFDL-1.3-only",
                "evidence_verified": True,
                "obligations": ['license_copy', 'copyright_notices', 'history', 'invariant_sections_checked', 'cover_texts_checked', 'transparent_copy_checked']
            },
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "verified")

    def test_mixed_source_conflict(self):
        ledger = LicensingLedger()
        source1 = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "GFDL-1.3-only",
                "evidence_verified": True,
                "obligations": ['license_copy', 'copyright_notices', 'history', 'invariant_sections_checked', 'cover_texts_checked', 'transparent_copy_checked']
            },
            "modification_status": "unchanged"
        }
        source2 = {
            "source_id": "test2",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence_verified": True,
                "obligations": ['attribution', 'license_link', 'changes_disclosed', 'sharealike', 'no_additional_restrictions']
            },
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_combination([source1, source2]), "blocked")

    def test_review_required(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence_verified": False,
                "obligations": ['attribution', 'license_link', 'changes_disclosed', 'sharealike', 'no_additional_restrictions']
            },
            "modification_status": "unchanged"
        }
        # Legally uncertain combinations/sources should be reviewRequired
        self.assertEqual(ledger.evaluate_source(source), "reviewRequired")

    def test_artifact_hash(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC0-1.0",
                "evidence_verified": True,
                "obligations": []
            },
            "modification_status": "unchanged",
            "artifact_hash": "deadbeef"
        }
        self.assertEqual(ledger.evaluate_source(source), "verified")

    def test_changed_source_versions(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "2.0",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence_verified": True,
                "obligations": ['attribution', 'license_link', 'changes_disclosed', 'sharealike', 'no_additional_restrictions']
            },
            "modification_status": "modified"
        }
        self.assertEqual(ledger.evaluate_source(source), "verified")

    def test_missing_attributions(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "http://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC-BY-2.0-FR",
                "evidence_verified": True,
                "obligations": ['license_link'] # missing attribution
            },
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")


if __name__ == '__main__':
    unittest.main()
