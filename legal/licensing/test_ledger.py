import unittest
import json
from legal.licensing.ledger import LicensingLedger, LEDGER_SCHEMA

class TestLicensingLedger(unittest.TestCase):
    def test_missing_author_blocked(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "origin_url": "http://test",
                    "license": {"id": "PUBLIC-DOMAIN", "evidence_verified": True},
                    "modification_status": "none"
                }
            ]
        }
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError):
            LicensingLedger(data)

    def test_missing_license_blocked_no_pd_inference(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("missing license claim cannot infer Public Domain", res["reason"])

    def test_public_domain_inference_without_evidence_blocked(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {"id": "PUBLIC-DOMAIN", "evidence_verified": False},
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("unverified public domain", res["reason"])

    def test_unverified_license_review_required(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {"id": "CC-BY-2.0-FR", "evidence_verified": False},
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1")
        self.assertEqual(res["status"], "reviewRequired")

    def test_missing_attributions_cc_by_sa(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {
                        "id": "CC-BY-SA-4.0",
                        "evidence_verified": True,
                        "obligations_met": {
                            "sharealike": True
                        }
                    },
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("missing obligation: attribution", res["reason"])

    def test_gfdl_provenance_missing_history(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {
                        "id": "GFDL-1.3-only",
                        "evidence_verified": True,
                        "obligations_met": {
                            "license_copy": True,
                            "copyright_notices": True
                            # "history" missing
                        }
                    },
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("missing obligation: history", res["reason"])

    def test_changed_source_versions(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "version": "1.0",
                    "license": {"id": "CC0-1.0", "evidence_verified": True},
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_source("SRC1", expected_version="2.0")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("changed source version", res["reason"])

    def test_invalid_copyleft_mixture(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {
                        "id": "CC-BY-SA-4.0",
                        "evidence_verified": True,
                        "obligations_met": {
                            "attribution": True, "license_link": True, "changes_disclosed": True, "sharealike": True, "no_additional_restrictions": True
                        }
                    },
                    "modification_status": "none"
                },
                {
                    "source_id": "SRC2",
                    "author": "Bob",
                    "license": {
                        "id": "GFDL-1.3-only",
                        "evidence_verified": True,
                        "obligations_met": {
                            "license_copy": True, "copyright_notices": True, "history": True, "invariant_sections_checked": True, "cover_texts_checked": True, "transparent_copy_checked": True
                        }
                    },
                    "modification_status": "none"
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_combination({
            "id": "COMB1",
            "source_ids": ["SRC1", "SRC2"],
            "output_license": "CC-BY-SA-4.0"
        })
        self.assertEqual(res["status"], "blocked")
        self.assertIn("invalid copyleft mixture", res["reason"])

    def test_downgrade_to_public_domain_blocked(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {
                        "id": "CC-BY-2.0-FR",
                        "evidence_verified": True,
                        "obligations_met": {
                            "attribution": True, "license_link": True
                        }
                    }
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_combination({
            "id": "COMB1",
            "source_ids": ["SRC1"],
            "output_license": "PUBLIC-DOMAIN"
        })
        self.assertEqual(res["status"], "blocked")
        self.assertIn("cannot downgrade CC-BY-2.0-FR to PUBLIC-DOMAIN", res["reason"])

    def test_permissive_to_copyleft(self):
        data = {
            "sources": [
                {
                    "source_id": "SRC1",
                    "author": "Alice",
                    "license": {
                        "id": "CC-BY-2.0-FR",
                        "evidence_verified": True,
                        "obligations_met": {
                            "attribution": True, "license_link": True
                        }
                    }
                },
                {
                    "source_id": "SRC2",
                    "author": "Bob",
                    "license": {
                        "id": "CC-BY-SA-4.0",
                        "evidence_verified": True,
                        "obligations_met": {
                            "attribution": True, "license_link": True, "changes_disclosed": True, "sharealike": True, "no_additional_restrictions": True
                        }
                    }
                }
            ]
        }
        ledger = LicensingLedger(data)
        res = ledger.evaluate_combination({
            "id": "COMB1",
            "source_ids": ["SRC1", "SRC2"],
            "output_license": "CC-BY-SA-4.0"
        })
        self.assertEqual(res["status"], "verified")

    def test_missing_source_identity(self):
        # Missing source_id is blocked by schema
        data = {
            "sources": [
                {
                    "author": "Alice",
                    "license": {"id": "PUBLIC-DOMAIN", "evidence_verified": True},
                }
            ]
        }
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError):
            LicensingLedger(data)
