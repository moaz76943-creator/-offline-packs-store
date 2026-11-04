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

    def test_output_license_rejects_unapproved_relicensing(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "attributed", "url": "https://example.org/corpus",
            "author": "Author", "version": "2026-01",
            "license": {"declared": "CC-BY-2.0-FR", "evidence_verified": True,
                        "obligations": ["attribution", "license_link"]},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source]), "verified")
        self.assertEqual(ledger.evaluate_combination([source], output_license="CC0-1.0"), "blocked")
        self.assertEqual(ledger.evaluate_combination([source], output_license="CC-BY-SA-4.0"), "blocked")
        self.assertEqual(ledger.evaluate_combination([source], output_license="CC-BY-2.0-FR"), "verified")

    def test_cc0_is_not_automatically_public_domain(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source], output_license="PUBLIC-DOMAIN"), "blocked")
        self.assertEqual(ledger.evaluate_combination([source], output_license="CC0-1.0"), "verified")

    def test_cc0_can_combine_with_sharealike_without_downgrading_it(self):
        ledger = LicensingLedger()
        base = {
            "url": "https://example.org/corpus", "author": "Author",
            "version": "1", "modification_status": "unchanged",
        }
        cc0 = dict(base, source_id="cc0",
                   license={"declared": "CC0-1.0", "evidence_verified": True})
        sa = dict(base, source_id="sa",
                  license={"declared": "CC-BY-SA-4.0", "evidence_verified": True,
                           "obligations": ["attribution", "license_link",
                                           "changes_disclosed", "sharealike",
                                           "no_additional_restrictions"]})
        self.assertEqual(ledger.evaluate_combination([cc0, sa], output_license="CC-BY-SA-4.0"), "verified")
        self.assertEqual(ledger.evaluate_combination([cc0, sa], output_license="CC0-1.0"), "blocked")

    def test_combination_requires_all_pinned_versions(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "2",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source], expected_versions={"cc0": "1"}), "blocked")
        self.assertEqual(ledger.evaluate_combination([source], expected_versions={}), "blocked")
        self.assertEqual(ledger.evaluate_combination([source], expected_versions={"cc0": "2"}), "verified")

    def test_unknown_output_license_is_blocked(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "1",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source], output_license="UNKNOWN"), "blocked")

    def test_combination_requires_matching_pinned_artifact_sha256(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "2",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged", "artifact_hash": "a" * 64,
        }
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={"cc0": "a" * 64}),
            "verified",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={"cc0": "b" * 64}),
            "blocked",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={}),
            "blocked",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={"cc0": "a" * 64, "other": "b" * 64}),
            "blocked",
        )

    def test_missing_artifact_digest_never_satisfies_pinned_usage(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "2",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged",
        }
        self.assertEqual(ledger.evaluate_combination([source]), "verified")
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={"cc0": None}),
            "blocked",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes={"cc0": "a" * 64}),
            "blocked",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_artifact_hashes=[]),
            "blocked",
        )

    def test_pinned_artifact_digest_and_version_must_both_match(self):
        ledger = LicensingLedger()
        source = {
            "source_id": "cc0", "url": "https://example.org/corpus",
            "author": "Author", "version": "2",
            "license": {"declared": "CC0-1.0", "evidence_verified": True},
            "modification_status": "unchanged", "artifact_hash": "a" * 64,
        }
        self.assertEqual(
            ledger.evaluate_combination([source], expected_versions={"cc0": "1"},
                                        expected_artifact_hashes={"cc0": "a" * 64}),
            "blocked",
        )
        self.assertEqual(
            ledger.evaluate_combination([source], expected_versions={"cc0": "2"},
                                        expected_artifact_hashes={"cc0": "a" * 64}),
            "verified",
        )

if __name__ == '__main__':
    unittest.main()
