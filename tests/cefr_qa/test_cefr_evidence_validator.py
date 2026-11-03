import os
import json
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.cefr_validation.cefr_evidence_validator import (
    resolve_safe_evidence_path,
    validate_cefr_record,
    run_cefr_audit
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

    def test_symlink_files_and_directories_cannot_escape_sandbox(self):
        with tempfile.TemporaryDirectory() as outside:
            victim = os.path.join(outside, 'victim.json')
            with open(victim, 'w') as stream:
                stream.write('preserve external data')
            source = os.path.join(self.temp_dir.name, 'input.json')
            with open(source, 'w') as stream:
                json.dump({'records': [{'level': 'B1', 'skill': 'vocabulary', 'term': 'Haus'}]}, stream)
            os.symlink(victim, os.path.join(self.temp_dir.name, 'output.json'))
            os.symlink(outside, os.path.join(self.temp_dir.name, 'directory'))
            for path in ('output.json', 'directory/new.json'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    run_cefr_audit(self.temp_dir.name, 'input.json', path)
            with open(victim) as stream:
                self.assertEqual(stream.read(), 'preserve external data')

    def test_only_nonblank_string_terms_are_valid(self):
        for term in (None, [], {}, True, 123, '', ' '):
            with self.subTest(term=term):
                self.assertFalse(validate_cefr_record({'level': 'B1', 'skill': 'vocabulary', 'term': term})[0])

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
