import unittest
import os
import json
from legal.licensing.ledger import LedgerAPI

class TestLedgerAPI(unittest.TestCase):
    def setUp(self):
        self.api = LedgerAPI()

    def get_valid_source(self):
        return {
            "source_id": "test_001",
            "url": "https://example.com/source",
            "author": "Test Author",
            "version": "1.0",
            "artifact_hash": "a" * 64,
            "modification_status": "unmodified",
            "license": {
                "declared": "CC-BY-SA-4.0",
                "evidence": "https://example.com/license",
                "obligations_met": True
            }
        }

    def test_valid_cc_by_sa(self):
        result = self.api.evaluate([self.get_valid_source()])
        self.assertEqual(result["status"], "verified")

    def test_missing_author(self):
        source = self.get_valid_source()
        del source["author"]
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("failed schema validation", result["reason"])
        self.assertIn("author", result["reason"])

    def test_missing_license_does_not_default_to_public_domain(self):
        source = self.get_valid_source()
        del source["license"]
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("failed schema validation", result["reason"])
        self.assertIn("license", result["reason"])

    def test_incomplete_cc_by_sa_obligations(self):
        source = self.get_valid_source()
        source["license"]["obligations_met"] = False
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("obligations are not met", result["reason"])

    def test_gfdl_provenance_valid(self):
        source = self.get_valid_source()
        source["license"]["declared"] = "GFDL-1.3-only"
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "verified")

    def test_mixed_provenance_requires_review(self):
        source1 = self.get_valid_source()
        source2 = self.get_valid_source()
        source2["source_id"] = "test_002"
        source2["license"]["declared"] = "GFDL-1.3-only"

        result = self.api.evaluate([source1, source2])
        self.assertEqual(result["status"], "reviewRequired")
        self.assertIn("Mixed provenance", result["reason"])

    def test_changed_source_version(self):
        source = self.get_valid_source()
        source["version"] = "2.0"
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "verified")

    def test_missing_source_id(self):
        source = self.get_valid_source()
        del source["source_id"]
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "blocked")

    def test_invalid_artifact_hash(self):
        source = self.get_valid_source()
        source["artifact_hash"] = "invalid_hash"
        result = self.api.evaluate([source])
        self.assertEqual(result["status"], "blocked")

if __name__ == '__main__':
    unittest.main()
