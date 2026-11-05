import unittest
from ledger import validate_sources, LicensingLedger

class TestLicensingLedger(unittest.TestCase):
    def test_valid_cc_by_sa(self):
        source = {
            "source_id": "test-ccbysa",
            "url": "https://example.com",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "declared_id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64,
                "cc_by_sa_obligations": {
                    "attribution": True,
                    "license_link": True,
                    "changes_disclosed": False,
                    "sharealike": True,
                    "no_additional_restrictions": True
                }
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-ccbysa"], "VERIFIED")

    def test_incomplete_ccbysa(self):
        source = {
            "source_id": "test-ccbysa-inc",
            "url": "https://example.com",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "declared_id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64,
                "cc_by_sa_obligations": {
                    "attribution": True,
                    "license_link": False,
                    "changes_disclosed": False,
                    "sharealike": True,
                    "no_additional_restrictions": True
                }
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-ccbysa-inc"], "REVIEW_REQUIRED")

    def test_modified_ccbysa_missing_disclosed(self):
        source = {
            "source_id": "test-ccbysa-mod",
            "url": "https://example.com",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "declared_id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64,
                "cc_by_sa_obligations": {
                    "attribution": True,
                    "license_link": True,
                    "changes_disclosed": False,
                    "sharealike": True,
                    "no_additional_restrictions": True
                }
            },
            "modification_status": "MODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-ccbysa-mod"], "REVIEW_REQUIRED")

    def test_gfdl_provenance(self):
        source_valid = {
            "source_id": "test-gfdl",
            "url": "https://example.com",
            "author": "Test Author",
            "version": "1.0",
            "license": {
                "declared_id": "GFDL-1.3-only",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64,
                "gfdl_obligations": {
                    "license_copy": True,
                    "copyright_notices": True,
                    "history": True
                }
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source_valid])
        self.assertEqual(res["test-gfdl"], "VERIFIED")

        import copy
        source_invalid = copy.deepcopy(source_valid)
        source_invalid["source_id"] = "test-gfdl-invalid"
        source_invalid["license"]["gfdl_obligations"]["history"] = False
        res = validate_sources([source_invalid])
        self.assertEqual(res["test-gfdl-invalid"], "REVIEW_REQUIRED")

    def test_missing_author(self):
        source = {
            "source_id": "test-no-author",
            "url": "https://example.com",
            "version": "1.0",
            "license": {
                "declared_id": "CC0-1.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-no-author"], "BLOCKED")

    def test_changed_source_version(self):
        source = {
            "source_id": "test-no-version",
            "url": "https://example.com",
            "author": "Author",
            # missing version
            "license": {
                "declared_id": "CC0-1.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-no-version"], "BLOCKED")

    def test_empty_author(self):
        source = {
            "source_id": "test-no-author2",
            "url": "https://example.com",
            "author": "",
            "version": "1.0",
            "license": {
                "declared_id": "CC0-1.0",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-no-author2"], "BLOCKED")

    def test_public_domain_review_required(self):
        source = {
            "source_id": "test-pd",
            "url": "https://example.com",
            "author": "Unknown",
            "version": "1.0",
            "license": {
                "declared_id": "PUBLIC-DOMAIN",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-pd"], "REVIEW_REQUIRED")

    def test_missing_license(self):
        source = {
            "source_id": "test-no-license",
            "url": "https://example.com",
            "author": "Unknown",
            "version": "1.0",
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-no-license"], "BLOCKED")

    def test_invalid_license_id(self):
        source = {
            "source_id": "test-invalid-license",
            "url": "https://example.com",
            "author": "Unknown",
            "version": "1.0",
            "license": {
                "declared_id": "UNKNOWN-LICENSE",
                "evidence_url": "https://example.com/license",
                "evidence_hash": "a" * 64
            },
            "modification_status": "UNMODIFIED"
        }
        res = validate_sources([source])
        self.assertEqual(res["test-invalid-license"], "BLOCKED")

if __name__ == "__main__":
    unittest.main()
