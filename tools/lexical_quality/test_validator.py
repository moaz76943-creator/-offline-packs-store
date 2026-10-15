"""Unit tests for the LexicalValidator."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools.lexical_quality.validator import LexicalValidator
from tools.lexical_quality.fixtures import VALID_ENTRIES, INVALID_ENTRIES, REVIEW_REQUIRED_ENTRIES

class TestLexicalValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LexicalValidator()

    def test_valid_entries(self):
        """Real valid entries pass structural validation."""
        for entry in VALID_ENTRIES:
            result = self.validator.validate_entry(entry)
            self.assertEqual(
                result["status"],
                "accepted",
                f"Valid entry rejected: {entry['id']} - Errors: {result.get('errors')} Warnings: {result.get('warnings')}"
            )
            self.assertEqual(len(result["errors"]), 0)

    def test_invalid_entries_fail_deterministically(self):
        """Corrupt and incompatible records fail deterministically."""
        for i, entry in enumerate(INVALID_ENTRIES):
            result = self.validator.validate_entry(entry)
            self.assertEqual(
                result["status"],
                "rejected",
                f"Invalid entry {i} should be rejected: {entry}"
            )
            self.assertTrue(len(result["errors"]) > 0)

    def test_review_required(self):
        """Linguistic uncertainty is reported rather than hidden (impossible combinations)."""
        for i, entry in enumerate(REVIEW_REQUIRED_ENTRIES):
            result = self.validator.validate_entry(entry)
            self.assertEqual(
                result["status"],
                "reviewRequired",
                f"Review entry {i} should be reviewRequired: {entry}"
            )
            self.assertEqual(len(result["errors"]), 0)
            self.assertTrue(len(result["warnings"]) > 0)

    def test_duplicate_senses(self):
        """Detect duplicate IDs."""
        entry = {"id": "eng-dup-1", "surface": "word", "language": "eng", "pos": "noun"}
        res1 = self.validator.validate_entry(entry)
        self.assertEqual(res1["status"], "accepted", f"First validation failed: {res1.get('errors')} {res1.get('warnings')}")

        # Second time should fail
        res2 = self.validator.validate_entry(entry)
        self.assertEqual(res2["status"], "rejected")
        self.assertIn("Duplicate lexical ID: eng-dup-1", res2["errors"])

    def test_valid_lexical_variations_preserved(self):
        """Valid lexical variations (different IDs) are not falsely deleted."""
        entry1 = {"id": "eng-var-1", "surface": "color", "language": "eng", "pos": "noun"}
        entry2 = {"id": "eng-var-2", "surface": "colour", "language": "eng", "pos": "noun"}

        self.assertEqual(self.validator.validate_entry(entry1)["status"], "accepted")
        self.assertEqual(self.validator.validate_entry(entry2)["status"], "accepted")

    def test_bounded_memory(self):
        """Validation has bounded memory requirements (size limits)."""
        import json
        large_text = "a" * (110 * 1024) # 110 KB string, exceeds 100 KB limit
        entry = {"id": "eng-huge-1", "surface": large_text, "language": "eng", "pos": "noun"}

        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("exceeds size limit" in err for err in result["errors"]))

    def test_invalid_unicode_lone_surrogate(self):
        """Detect invalid Unicode (lone surrogates)."""
        entry = {"id": "eng-uni-1", "surface": "bad\ud83dstring", "language": "eng", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("invalid Unicode" in err for err in result["errors"]))

    def test_preserves_original_records(self):
        """Preserve original records for reversible remediation."""
        original = {"id": "eng-pres-1", "surface": "test", "language": "eng", "pos": "noun"}
        import copy
        entry_copy = copy.deepcopy(original)

        result = self.validator.validate_entry(entry_copy)
        self.assertEqual(result["entry"], original)
        self.assertEqual(entry_copy, original)

    def test_absent_optional_fields(self):
        """Test absent optional fields are handled correctly."""
        entry = {"id": "eng-abs-1", "surface": "test", "language": "eng", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "accepted")

    def test_language_mismatch(self):
        """Test language mismatch between ID and language field."""
        entry = {"id": "eng-mis-1", "surface": "test", "language": "deu", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("Language mismatch" in err for err in result["errors"]))

    def test_isolating_languages(self):
        """Test grammar rules for isolating languages (should be reviewRequired if they have plurals)."""
        entry = {"id": "zho-iso-1", "surface": "测试", "language": "zho", "pos": "noun", "plural": "测试们"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "reviewRequired")
        self.assertTrue(any("Isolating language 'zho' has 'plural' field" in warn for warn in result["warnings"]))

    def test_malformed_examples(self):
        """Test malformed examples are detected."""
        entry = {"id": "eng-mal-1", "surface": "test", "language": "eng", "pos": "noun", "examples": [{"wrong_key": "val"}]}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("missing 'text'" in err for err in result["errors"]))

if __name__ == '__main__':
    unittest.main()
