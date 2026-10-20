"""Unit tests for the LexicalValidator."""

import unittest
import sys
import os

# Ensure the module can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools.lexical_quality.validator import LexicalQualityValidator
from tools.lexical_quality.fixtures import VALID_ENTRIES, INVALID_ENTRIES, REVIEW_REQUIRED_ENTRIES

class TestLexicalValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LexicalQualityValidator()

    def test_valid_entries(self):
        """Real valid entries pass structural validation."""
        for entry in VALID_ENTRIES:
            result = self.validator.validate_entry(entry)
            self.assertEqual(
                result["status"],
                "accepted",
                f"Valid entry rejected: {entry['id']} - Errors: {result.get('errors')}"
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
        entry = {"id": "dup-1", "surface": "word", "language": "eng", "pos": "noun"}
        res1 = self.validator.validate_entry(entry)
        self.assertEqual(res1["status"], "accepted")

        # Second time should fail
        res2 = self.validator.validate_entry(entry)
        self.assertEqual(res2["status"], "rejected")
        self.assertIn("Duplicate lexical ID: dup-1", res2["errors"])

    def test_valid_lexical_variations_preserved(self):
        """Valid lexical variations (different IDs) are not falsely deleted."""
        entry1 = {"id": "var-1", "surface": "color", "language": "eng", "pos": "noun"}
        entry2 = {"id": "var-2", "surface": "colour", "language": "eng", "pos": "noun"}

        self.assertEqual(self.validator.validate_entry(entry1)["status"], "accepted")
        self.assertEqual(self.validator.validate_entry(entry2)["status"], "accepted")

    def test_bounded_memory(self):
        """Validation has bounded memory requirements (size limits)."""
        import json
        large_text = "a" * (110 * 1024) # 110 KB string, exceeds 100 KB limit
        entry = {"id": "huge-1", "surface": large_text, "language": "eng", "pos": "noun"}

        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("exceeds size limit" in err for err in result["errors"]))

    def test_invalid_unicode_lone_surrogate(self):
        """Detect invalid Unicode (lone surrogates)."""
        # Python allows storing lone surrogates in strings internally,
        # but they fail UTF-8 encoding.
        # \ud83d is a high surrogate for emojis, but without the low surrogate, it's invalid
        entry = {"id": "uni-1", "surface": "bad\ud83dstring", "language": "eng", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("invalid Unicode" in err for err in result["errors"]))

    def test_preserves_original_records(self):
        """Preserve original records for reversible remediation."""
        original = {"id": "pres-1", "surface": "test", "language": "eng", "pos": "noun"}
        # Make a copy to simulate passing it to validator
        import copy
        entry_copy = copy.deepcopy(original)

        result = self.validator.validate_entry(entry_copy)
        # Check that the returned entry is exactly the original
        self.assertEqual(result["entry"], original)
        # Check that it didn't mutate the input dictionary in unexpected ways
        self.assertEqual(entry_copy, original)

    def test_missing_optional_fields(self):
        """Test absent optional fields."""
        entry = {"id": "missing-opt", "surface": "test", "language": "eng", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "accepted")

    def test_malformed_examples(self):
        """Test malformed examples."""
        entry = {"id": "mal-ex", "surface": "test", "language": "eng", "pos": "noun", "examples": [{"not_text": "hello"}]}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")

    def test_language_mismatches(self):
        """Test language mismatches. Missing translation languages or mismatched codes format."""
        entry = {"id": "lang-mis", "surface": "test", "language": "invalid-lang-CODE", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")

    def test_multilingual_entries(self):
        """Test entries with various scripts (Requirement #14)."""
        entries = [
            {"id": "deu-2", "surface": "Katze", "language": "deu", "pos": "noun"},
            {"id": "ara-2", "surface": "كلب", "language": "ara", "pos": "noun"},
            {"id": "heb-2", "surface": "ספר", "language": "heb", "pos": "noun"},
            {"id": "zho-2", "surface": "狗", "language": "zho", "pos": "noun"},
            {"id": "jpn-2", "surface": "猫", "language": "jpn", "pos": "noun"},
            {"id": "tha-2", "surface": "แมว", "language": "tha", "pos": "noun"},
        ]
        for entry in entries:
            result = self.validator.validate_entry(entry)
            self.assertEqual(result["status"], "accepted", f"Failed for entry: {entry}")

if __name__ == '__main__':
    unittest.main()
