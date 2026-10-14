import unittest
from ledger import LedgerAPI

class TestLedgerAPI(unittest.TestCase):
    def setUp(self):
        self.api = LedgerAPI()
        self.valid_record = {
            "source_id": "src-1",
            "url": "https://example.com/data",
            "author": "Author A",
            "version": "1.0",
            "hash": "a" * 64,
            "license": {
                "declared_license": "CC-BY-SA-4.0",
                "evidence": {
                    "verified": True,
                    "obligations_met": {
                        "attribution": True,
                        "license_link": True,
                        "changes_disclosed": True,
                        "sharealike": True,
                        "no_additional_restrictions": True
                    }
                }
            },
            "modification_status": "unmodified"
        }
        self.valid_gfdl = {
            "source_id": "src-2",
            "url": "https://example.com/data2",
            "author": "Author B",
            "version": "2.0",
            "hash": "b" * 64,
            "license": {
                "declared_license": "GFDL-1.3-only",
                "evidence": {
                    "verified": True,
                    "obligations_met": {
                        "license_copy": True,
                        "copyright_notices": True,
                        "history": True,
                        "invariant_sections_checked": True,
                        "cover_texts_checked": True,
                        "transparent_copy_checked": True
                    }
                }
            },
            "modification_status": "unmodified"
        }
        self.valid_pd = {
            "source_id": "src-3",
            "url": "https://example.com/data3",
            "author": "Author C",
            "version": "1.0",
            "hash": "c" * 64,
            "license": {
                "declared_license": "PUBLIC-DOMAIN",
                "evidence": {
                    "verified": True
                }
            },
            "modification_status": "unmodified"
        }

    def test_missing_attributions_blocked(self):
        record = self.valid_record.copy()
        record['author'] = ""
        errors = self.api.validate_record(record)
        self.assertTrue(any("missing author" in e for e in errors))

    def test_changed_source_version_hash_mismatch(self):
        errors = self.api.validate_record(self.valid_record, actual_hash="b" * 64)
        self.assertTrue(any("hash mismatch" in e for e in errors))

    def test_incomplete_cc_by_sa_obligations_blocked(self):
        record = self.valid_record.copy()
        record['license'] = {
            "declared_license": "CC-BY-SA-4.0",
            "evidence": {
                "verified": True,
                "obligations_met": {
                    "attribution": True,
                    "license_link": True,
                    # changes_disclosed is missing
                    "sharealike": True,
                    "no_additional_restrictions": True
                }
            }
        }
        errors = self.api.validate_record(record)
        self.assertTrue(any("incomplete obligation changes_disclosed" in e for e in errors))

    def test_incomplete_gfdl_provenance_blocked(self):
        record = self.valid_gfdl.copy()
        record['license'] = {
            "declared_license": "GFDL-1.3-only",
            "evidence": {
                "verified": True,
                "obligations_met": {
                    "license_copy": True,
                    # history missing
                    "copyright_notices": True,
                    "invariant_sections_checked": True,
                    "cover_texts_checked": True,
                    "transparent_copy_checked": True
                }
            }
        }
        errors = self.api.validate_record(record)
        self.assertTrue(any("incomplete obligation history" in e for e in errors))

    def test_missing_license_blocks(self):
        record = self.valid_record.copy()
        record.pop('license')
        errors = self.api.validate_record(record)
        self.assertTrue(any("missing license" in e for e in errors))
        # Never infer Public Domain
        self.assertFalse(any("PUBLIC-DOMAIN" in e for e in errors)) # Actually, it just blocks it completely.

    def test_evaluate_provenance_success(self):
        self.api.add_record(self.valid_record)
        self.api.add_record(self.valid_pd)
        status = self.api.evaluate_provenance(["src-1", "src-3"])
        self.assertEqual(status, "verified")

    def test_evaluate_provenance_uncertainty(self):
        self.api.add_record(self.valid_record)
        self.api.add_record(self.valid_gfdl)
        # GFDL + CC-BY-SA is legally uncertain (reviewRequired)
        status = self.api.evaluate_provenance(["src-1", "src-2"])
        self.assertEqual(status, "reviewRequired")

    def test_evaluate_provenance_blocked_due_to_missing_source(self):
        self.api.add_record(self.valid_record)
        status = self.api.evaluate_provenance(["src-1", "src-unknown"])
        self.assertEqual(status, "blocked")

    def test_evaluate_provenance_blocked_due_to_invalid_source(self):
        invalid_record = self.valid_gfdl.copy()
        invalid_record['author'] = ""
        self.api.add_record(self.valid_record)
        self.api.add_record(invalid_record)
        status = self.api.evaluate_provenance(["src-1", "src-2"])
        self.assertEqual(status, "blocked")

if __name__ == '__main__':
    unittest.main()
