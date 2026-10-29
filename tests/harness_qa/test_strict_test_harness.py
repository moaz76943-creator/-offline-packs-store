import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.test_integrity.strict_test_harness import (
    validate_test_fixture,
    assert_non_empty_results
)

class TestStrictTestHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_canonical_fixture_passes_validation(self):
        ok, msg = validate_test_fixture("tests/fixtures/canonical_de_ar_fixture.json")
        self.assertTrue(ok)
        self.assertIn("FIXTURE_VALID", msg)

    def test_empty_fixture_fails_closed(self):
        empty_fix = os.path.join(self.temp_dir.name, "empty_fix.json")
        with open(empty_fix, 'w') as f:
            f.write('{"vocabulary": []}')

        ok, msg = validate_test_fixture(empty_fix)
        self.assertFalse(ok)
        self.assertIn("FALSE_FIXTURE", msg)

    def test_zero_results_assertion_blocks_false_pass(self):
        with self.assertRaises(AssertionError):
            assert_non_empty_results([], "sample_search_test")

        # Non-empty list succeeds
        self.assertTrue(assert_non_empty_results(["result_1"], "sample_search_test"))

if __name__ == "__main__":
    unittest.main()
