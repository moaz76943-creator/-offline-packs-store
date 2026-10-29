import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.cefr_validation.cefr_evidence_validator import (
    resolve_safe_evidence_path,
    validate_cefr_record
)

class TestCefrEvidenceValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_path_traversal_strictly_blocked(self):
        with self.assertRaises(ValueError):
            resolve_safe_evidence_path(self.temp_dir.name, "../../../etc/shadow")

        with self.assertRaises(ValueError):
            resolve_safe_evidence_path(self.temp_dir.name, "evidence/../../private_data.key")

    def test_valid_safe_path_resolves(self):
        resolved = resolve_safe_evidence_path(self.temp_dir.name, "evidence/cefr_a1.json")
        self.assertTrue(resolved.startswith(self.temp_dir.name))

    def test_valid_cefr_levels_and_skills(self):
        valid = {'level': 'B1', 'skill': 'vocabulary', 'term': 'Verhandlung'}
        ok, msg = validate_cefr_record(valid)
        self.assertTrue(ok)

        invalid_level = {'level': 'X9', 'skill': 'vocabulary', 'term': 'Test'}
        ok2, msg2 = validate_cefr_record(invalid_level)
        self.assertFalse(ok2)
        self.assertIn("INVALID_CEFR_LEVEL", msg2)

if __name__ == "__main__":
    unittest.main()
