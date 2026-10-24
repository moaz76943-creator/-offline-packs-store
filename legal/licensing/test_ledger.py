import unittest
from legal.licensing.ledger import LicensingLedger

class TestLicensingLedger(unittest.TestCase):
    def test_missing_author(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "https://example.com",
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
            "url": "https://example.com",
            "author": "Author",
            "version": "1.0",
            "modification_status": "unchanged"
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_missing_source_identity(self):
        ledger = LicensingLedger()
        source = {
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
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
            "url": "https://example.com",
            "author": "Author",
            "version": "1.0",
            "license": {
                "declared": "CC0-1.0",
                "evidence_verified": True,
                "obligations": []
            },
            "modification_status": "unchanged",
            "artifact_hash": "a" * 64
        }
        self.assertEqual(ledger.evaluate_source(source), "verified")

    def test_changed_source_versions(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "test1",
            "url": "https://example.com",
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
            "url": "https://example.com",
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


    def test_invalid_artifact_hash_is_blocked(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged", "artifact_hash": "deadbeef",
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

    def test_malformed_obligations_fail_closed_without_exception(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True,
                        "obligations": [{"not": "a string"}]},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")
        self.assertEqual(ledger.evaluate_combination([source]), "blocked")

    def test_conflicting_reused_source_id_cannot_overwrite_provenance(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org",
            "author": "Original", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.add_source(source), "verified")
        changed = dict(source, author="Other")
        self.assertEqual(ledger.add_source(changed), "blocked")
        self.assertEqual(ledger.sources["s1"]["author"], "Original")

    def test_stored_license_is_not_aliased_to_mutable_caller_data(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True,
                        "obligations": []},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.add_source(source), "verified")
        source["license"]["declared"] = "UNKNOWN"
        source["license"]["obligations"].append("forged")
        self.assertEqual(ledger.sources["s1"]["license"]["declared"], "CC0-1.0")
        self.assertEqual(ledger.sources["s1"]["license"]["obligations"], [])


    def test_source_url_requires_https_without_embedded_secrets(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org/source",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_source(source), "verified")
        for unsafe in ("http://example.org/source",
                       "https://user:password@example.org/source",
                       "https://example.org/source?token=secret",
                       "https://example.org/source?access_token=secret"):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(
                    ledger.evaluate_source(dict(source, url=unsafe)), "blocked"
                )

    def test_duplicate_source_identity_in_combination_is_blocked(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org/source",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source]), "verified")
        self.assertEqual(ledger.evaluate_combination([source, source]), "blocked")
        changed = dict(source, author="Different publisher")
        self.assertEqual(ledger.evaluate_combination([source, changed]), "blocked")

    def test_unknown_license_is_blocked(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "s1", "url": "https://example.org/source",
            "author": "Author", "version": "1",
            "license": {"declared": "UNKNOWN", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_source(source), "blocked")

if __name__ == '__main__':
    unittest.main()
