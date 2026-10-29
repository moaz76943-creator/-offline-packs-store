import os
import sys
import unittest

# ضبط مسار الجذر لحل ModuleNotFoundError: No module named 'tools'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from tools.gha_factory.admission.legal_admission_validator import validate_source_entry

class TestLegalAdmissionValidator(unittest.TestCase):
    def test_valid_entry(self):
        entry = {
            "source_id": "kaikki_de_deu",
            "license": "CC-BY-SA-4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "upstream_url": "https://kaikki.org/",
            "snapshot_date": "2026-01-01",
            "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "attribution_text": "Wiktionary contributors via Kaikki.org",
            "commercial_use_allowed": True,
            "share_alike_required": True,
            "modification_allowed": True,
            "legal_review_status": "APPROVED",
        }
        valid, errors = validate_source_entry(entry)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_missing_field(self):
        entry = {"source_id": "incomplete"}
        valid, errors = validate_source_entry(entry)
        self.assertFalse(valid)
        self.assertTrue(any("Missing mandatory field" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
