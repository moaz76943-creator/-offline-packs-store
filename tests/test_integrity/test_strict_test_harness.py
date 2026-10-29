import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.test_integrity.strict_test_harness import validate_canonical_fixture, load_and_verify_fixture

class TestStrictTestHarness(unittest.TestCase):
    def test_fixture_file_compliance(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "../fixtures/canonical_de_ar_fixture.json")
        data = load_and_verify_fixture(fixture_path)
        self.assertEqual(data["fixture_id"], "canonical_de_ar_v1")
        self.assertGreaterEqual(len(data["words"]), 2)

    def test_invalid_fixture_fails(self):
        bad_fixture = {"fixture_id": "bad", "words": [{"lemma": "test", "pos": ""}]}
        valid, errors = validate_canonical_fixture(bad_fixture)
        self.assertFalse(valid)
        self.assertTrue(any("missing required field" in e for e in errors))

if __name__ == '__main__':
    unittest.main()
