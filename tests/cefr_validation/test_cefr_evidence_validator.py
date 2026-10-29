import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.cefr_validation.cefr_evidence_validator import validate_cefr_evidence_entry, is_safe_sandbox_path

class TestCefrEvidenceValidator(unittest.TestCase):
    def test_valid_cefr_evidence(self):
        entry = {
            "cefr_level": "A1",
            "evidence_file": "data/cefr_a1_evidence.json",
            "corpus_citation": "DWDS frequency band 1 / Goethe A1 syllabus"
        }
        valid, errors = validate_cefr_evidence_entry(entry, base_dir="/safe/sandbox")
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_path_traversal_blocked(self):
        entry = {
            "cefr_level": "A1",
            "evidence_file": "../../etc/shadow",
            "corpus_citation": "suspicious"
        }
        valid, errors = validate_cefr_evidence_entry(entry, base_dir="/safe/sandbox")
        self.assertFalse(valid)
        self.assertTrue(any("Path traversal detected" in e for e in errors))

    def test_invalid_cefr_level(self):
        entry = {
            "cefr_level": "Z9",
            "evidence_file": "data/valid.json",
            "corpus_citation": "test"
        }
        valid, errors = validate_cefr_evidence_entry(entry)
        self.assertFalse(valid)
        self.assertTrue(any("Invalid CEFR level" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
