import unittest
import jsonschema
from legal.licensing.ledger import LicensingLedger, LEDGER_SCHEMA
from legal.ledger.admission import OBLIGATIONS

class TestLicensingLedger(unittest.TestCase):
    def test_schema_validates(self):
        valid_data = {
            "records": [
                {
                    "source_id": "s1", "url": "https://a.com", "author": "a",
                    "version": "1", "license": {"id": "CC0-1.0", "declaration_only": True},
                    "modification_status": "unmodified"
                }
            ]
        }
        jsonschema.validate(instance=valid_data, schema=LEDGER_SCHEMA)

    def test_missing_author_rejected(self):
        v = LicensingLedger()
        res = v.add_record({
            "source_id": "s1", "url": "https://a.com",
            "version": "1", "license": {"id": "CC0-1.0", "declaration_only": True},
            "modification_status": "unmodified"
        })
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("author", res["reason"])

    def test_public_domain_inference_rejected(self):
        v = LicensingLedger()
        res = v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "PUBLIC-DOMAIN", "declaration_only": True},
            "modification_status": "unmodified"
        })
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("evidence", res["reason"])

    def test_mixed_copyleft(self):
        v = LicensingLedger()
        v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "CC-BY-SA-4.0", "declaration_only": True, "provided_obligations": list(OBLIGATIONS["CC-BY-SA-4.0"])},
            "modification_status": "unmodified"
        })
        v.add_record({
            "source_id": "s2", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "GFDL-1.3-only", "declaration_only": True, "provided_obligations": list(OBLIGATIONS["GFDL-1.3-only"])},
            "modification_status": "unmodified"
        })
        res = v.evaluate_combination(["s1", "s2"], "CC-BY-SA-4.0")
        self.assertEqual(res["status"], "REVIEW_REQUIRED")

    def test_relicensing_copyleft_blocked(self):
        v = LicensingLedger()
        v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "CC-BY-SA-4.0", "declaration_only": True, "provided_obligations": list(OBLIGATIONS["CC-BY-SA-4.0"])},
            "modification_status": "unmodified"
        })
        res = v.evaluate_combination(["s1"], "CC0-1.0")
        self.assertEqual(res["status"], "REVIEW_REQUIRED")

    def test_unknown_license_blocked(self):
        v = LicensingLedger()
        res = v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "UNKNOWN", "declaration_only": True},
            "modification_status": "unmodified"
        })
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("unknown license", res["reason"])

    def test_missing_source_identity(self):
        v = LicensingLedger()
        res = v.add_record({
            "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "CC0-1.0", "declaration_only": True},
            "modification_status": "unmodified"
        })
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("source_id", res["reason"])

    def test_evaluate_missing_source(self):
        v = LicensingLedger()
        res = v.evaluate_combination(["s1"], "CC0-1.0")
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("missing sources", res["reason"])

    def test_changed_source_version(self):
        v = LicensingLedger()
        v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "CC0-1.0", "declaration_only": True},
            "modification_status": "unmodified"
        })
        v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "2", "license": {"id": "CC0-1.0", "declaration_only": True},
            "modification_status": "unmodified"
        })

        # Requesting a version that exists is verified
        res = v.evaluate_combination(["s1"], "CC0-1.0", target_version={"s1": "2"})
        self.assertEqual(res["status"], "VERIFIED")

        # Requesting a version that does NOT exist is blocked
        res2 = v.evaluate_combination(["s1"], "CC0-1.0", target_version={"s1": "3"})
        self.assertEqual(res2["status"], "BLOCKED")

    def test_incomplete_cc_by_sa_obligations(self):
        v = LicensingLedger()

        # Only provide 'attribution' and not the rest
        res = v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {"id": "CC-BY-SA-4.0", "declaration_only": True, "provided_obligations": ["attribution"]},
            "modification_status": "unmodified"
        })

        # Should be blocked on add due to missing obligations
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("missing obligations", res["reason"])

    def test_gfdl_provenance(self):
        v = LicensingLedger()

        # Provide some GFDL obligations but not history
        res = v.add_record({
            "source_id": "s1", "url": "https://a.com", "author": "a",
            "version": "1", "license": {
                "id": "GFDL-1.3-only",
                "declaration_only": True,
                "provided_obligations": ["copyright_notices"]
            },
            "modification_status": "unmodified"
        })

        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("missing obligations", res["reason"])

if __name__ == '__main__':
    unittest.main()
