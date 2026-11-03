import os
import tempfile
import unittest
import sys
import json
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

    def test_reject_malformed_structures_and_truthy_values(self):
        malformed = [
            ["entry"],
            {"vocabulary": "word"},
            {"vocabulary": [None]},
            {"vocabulary": [{"lemma": True, "translations": 42}]},
            {"vocabulary": [{"lemma": " ", "translations": [""]}]},
            {"vocabulary": [{"lemma": "Haus", "translations": [" "]}]},
            {"vocabulary": [{"lemma": "Haus", "translations": ["house", 7]}]},
            {"vocabulary": [{"lemma": 5, "translations": ["house"]}]},
            {"vocabulary": [{"lemma": "Haus", "translations": "house"}]},
        ]
        for i, payload in enumerate(malformed):
            with self.subTest(case=i):
                path = os.path.join(self.temp_dir.name, f"invalid_{i}.json")
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f)
                ok, msg = validate_test_fixture(path)
                self.assertFalse(ok, msg)

    def test_reject_empty_translation_among_valid_values(self):
        p = os.path.join(self.temp_dir.name, "invalid_translation.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"vocabulary": [{"lemma": "Haus", "translations": ["house", " "]}]}, f)
        self.assertFalse(validate_test_fixture(p)[0])

if __name__ == "__main__":
    unittest.main()
