import unittest
from legal.licensing.ledger import LicensingLedger, LEDGER_SCHEMA

class TestLicensingLedger(unittest.TestCase):
    def setUp(self):
        self.valid_source = {
            "source_id": "src1",
            "url": "https://example.com/src1",
            "author": "Alice",
            "version": "1.0",
            "license": "CC-BY-SA-4.0",
            "modification_status": "modified",
            "artifact_hash": "a" * 64,
            "verified_evidence": True
        }

    def test_missing_required_attributes(self):
        # Missing author
        invalid_src = self.valid_source.copy()
        del invalid_src["author"]
        ledger = LicensingLedger({"sources": [invalid_src], "output_license": "CC-BY-SA-4.0"})
        self.assertEqual(ledger.evaluate_combination(), "blocked")

        # Missing license
        invalid_src2 = self.valid_source.copy()
        del invalid_src2["license"]
        ledger2 = LicensingLedger({"sources": [invalid_src2], "output_license": "CC-BY-SA-4.0"})
        self.assertEqual(ledger2.evaluate_combination(), "blocked")

        # Missing source identity
        invalid_src3 = self.valid_source.copy()
        del invalid_src3["source_id"]
        ledger3 = LicensingLedger({"sources": [invalid_src3], "output_license": "CC-BY-SA-4.0"})
        self.assertEqual(ledger3.evaluate_combination(), "blocked")

    def test_changed_source_versions(self):
        ledger = LicensingLedger({
            "sources": [self.valid_source],
            "output_license": "CC-BY-SA-4.0",
            "compliance": {
                "attribution": True,
                "license_link": True,
                "changes_disclosed": True,
                "sharealike": True,
                "no_additional_restrictions": True
            }
        })
        usage = {"src1": {"version": "1.1"}} # version changed
        self.assertEqual(ledger.evaluate_combination(usage), "reviewRequired")

        usage2 = {"src1": {"version": "1.0", "artifact_hash": "b"*64}} # hash changed
        self.assertEqual(ledger.evaluate_combination(usage2), "reviewRequired")

    def test_incomplete_cc_by_sa_obligations(self):
        # Missing one obligation
        ledger = LicensingLedger({
            "sources": [self.valid_source],
            "output_license": "CC-BY-SA-4.0",
            "compliance": {
                "attribution": True,
                "license_link": True,
                "changes_disclosed": True,
                "sharealike": True
                # no_additional_restrictions is missing
            }
        })
        self.assertEqual(ledger.evaluate_combination(), "blocked")

    def test_gfdl_provenance(self):
        gfdl_source = self.valid_source.copy()
        gfdl_source["license"] = "GFDL-1.3-only"

        ledger = LicensingLedger({
            "sources": [gfdl_source],
            "output_license": "GFDL-1.3-only",
            "compliance": {
                "license_copy": True,
                "copyright_notices": True,
                "history": True,
                "invariant_sections_checked": True,
                "cover_texts_checked": True
                # transparent_copy_checked missing
            }
        })
        self.assertEqual(ledger.evaluate_combination(), "blocked")

        ledger_valid = LicensingLedger({
            "sources": [gfdl_source],
            "output_license": "GFDL-1.3-only",
            "compliance": {
                "license_copy": True,
                "copyright_notices": True,
                "history": True,
                "invariant_sections_checked": True,
                "cover_texts_checked": True,
                "transparent_copy_checked": True
            }
        })
        self.assertEqual(ledger_valid.evaluate_combination(), "verified")

    def test_invalid_license_mixtures(self):
        gfdl_source = self.valid_source.copy()
        gfdl_source["source_id"] = "src2"
        gfdl_source["license"] = "GFDL-1.3-only"

        # Mixed copyleft
        ledger = LicensingLedger({
            "sources": [self.valid_source, gfdl_source],
            "output_license": "CC-BY-SA-4.0"
        })
        self.assertEqual(ledger.evaluate_combination(), "blocked")

    def test_unverified_public_domain(self):
        pd_source = self.valid_source.copy()
        pd_source["license"] = "PUBLIC-DOMAIN"
        pd_source["verified_evidence"] = False

        ledger = LicensingLedger({
            "sources": [pd_source],
            "output_license": "PUBLIC-DOMAIN"
        })
        self.assertEqual(ledger.evaluate_combination(), "reviewRequired")

    def test_relicensing_copyleft_blocked(self):
        ledger = LicensingLedger({
            "sources": [self.valid_source],
            "output_license": "CC0-1.0",
            "compliance": {
                "attribution": True,
                "license_link": True,
                "changes_disclosed": True,
                "sharealike": True,
                "no_additional_restrictions": True
            }
        })
        self.assertEqual(ledger.evaluate_combination(), "blocked")

    def test_public_domain_contradicts_original(self):
        ledger = LicensingLedger({
            "sources": [{"source_id": "src1", "url": "https://example.com/src1", "author": "Alice", "version": "1.0", "license": "CC0-1.0", "modification_status": "modified"}],
            "output_license": "PUBLIC-DOMAIN"
        })
        self.assertEqual(ledger.evaluate_combination(), "blocked")

    def test_legally_uncertain_combinations(self):
        uncertain_source = self.valid_source.copy()
        uncertain_source["license"] = "CC-BY-2.0-FR"

        ledger = LicensingLedger({
            "sources": [uncertain_source],
            "output_license": "CC-BY-2.0-FR",
            "compliance": {
                "attribution": True,
                "license_link": True
            }
        })
        # Since CC-BY-2.0-FR is in OBLIGATIONS, it shouldn't trigger "reviewRequired" directly from the uncertain condition.
        self.assertEqual(ledger.evaluate_combination(), "verified")

        # Permissive source with copyleft output license should be allowed
        ledger_permissive_to_copyleft = LicensingLedger({
            "sources": [uncertain_source],
            "output_license": "CC-BY-SA-4.0",
            "compliance": {
                "attribution": True,
                "license_link": True
            }
        })
        self.assertEqual(ledger_permissive_to_copyleft.evaluate_combination(), "verified")

        # Test unknown/proprietary (which would also fail schema validation because it's not in LICENSES)
        unknown_license_source = self.valid_source.copy()
        unknown_license_source["license"] = "UNKNOWN-PROPRIETARY"

        ledger_unknown = LicensingLedger({
            "sources": [unknown_license_source],
            "output_license": "CC-BY-SA-4.0"
        })
        # Schema validation blocks it first because UNKNOWN-PROPRIETARY is not in LICENSES
        self.assertEqual(ledger_unknown.evaluate_combination(), "blocked")

if __name__ == '__main__':
    unittest.main()