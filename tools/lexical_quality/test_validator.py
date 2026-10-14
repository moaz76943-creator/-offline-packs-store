"""Unit tests for the LexicalValidator."""

import unittest
import sys
import os

# Ensure the module can be imported
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

    def test_duplicate_ids(self):
        """Detect duplicate entry IDs."""
        # Reset seen sets
        self.validator = LexicalValidator()
        entry = {"id": "dup-1", "surface": "word", "language": "eng", "pos": "noun"}
        res1 = self.validator.validate_entry(entry)
        self.assertEqual(res1["status"], "accepted")

        # Second time should fail
        res2 = self.validator.validate_entry(entry)
        self.assertEqual(res2["status"], "rejected")
        self.assertIn("Duplicate lexical ID: dup-1", res2["errors"])

    def test_duplicate_senses_and_mismatches(self):
        """Detect duplicate sense IDs within/across entries and language mismatches."""
        # This uses the new INVALID_ENTRIES added to fixtures
        for entry in INVALID_ENTRIES:
            if entry.get("id") == "eng-11": # duplicate senses
                res = self.validator.validate_entry(entry)
                self.assertEqual(res["status"], "rejected")
                self.assertTrue(any("Duplicate sense ID" in err for err in res["errors"]))
            elif entry.get("id") == "eng-12": # language mismatch
                res = self.validator.validate_entry(entry)
                self.assertEqual(res["status"], "rejected")
                self.assertTrue(any("language cannot be the same as entry language" in err for err in res["errors"]))

    def test_absent_optional_fields_and_malformed_examples(self):
        """Test absent optional fields handle cleanly and malformed examples are caught."""
        for entry in INVALID_ENTRIES:
            if entry.get("id") == "eng-13": # malformed examples
                res = self.validator.validate_entry(entry)
                self.assertEqual(res["status"], "rejected")
                self.assertTrue(any("must be a dictionary" in err for err in res["errors"]))
            elif entry.get("id") == "eng-14": # malformed sense (absent id)
                res = self.validator.validate_entry(entry)
                self.assertEqual(res["status"], "rejected")
                self.assertTrue(any("missing 'id'" in err for err in res["errors"]))

    def test_isolating_language_grammar(self):
        """Test isolating language grammar rules for plural/conjugation evidence."""
        for entry in REVIEW_REQUIRED_ENTRIES:
            if entry.get("id") in ("zho-2", "tha-2"):
                res = self.validator.validate_entry(entry)
                self.assertEqual(res["status"], "reviewRequired")
                self.assertTrue(any("unusual for isolating languages" in warn for warn in res["warnings"]))

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

if __name__ == '__main__':
    unittest.main()
