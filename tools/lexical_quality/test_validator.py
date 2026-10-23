"""Unit tests for the LexicalValidator."""

import unittest
import sys
import os
import io
import json
from unittest.mock import patch

# Ensure the module can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools.lexical_quality.validator import LexicalValidator
from tools.lexical_quality.fixtures import VALID_ENTRIES, INVALID_ENTRIES, REVIEW_REQUIRED_ENTRIES

class TestLexicalValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LexicalValidator()
        self.addCleanup(self.validator.close)

    def test_spilled_history_keeps_old_ids_and_bounds_python_memory(self):
        with LexicalValidator(max_history=2) as validator:
            for i in range(20):
                entry = {'id': f'eng-word-{i}', 'surface': 'word', 'language': 'eng', 'pos': 'noun'}
                self.assertEqual(validator.validate_entry(entry)['status'], 'accepted')
                self.assertLessEqual(len(validator.seen_ids), 2)
            duplicate = validator.validate_entry({
                'id': 'eng-word-0', 'surface': 'word', 'language': 'eng', 'pos': 'noun'})
            self.assertEqual(duplicate['status'], 'rejected')
            self.assertIn('Duplicate lexical ID: eng-word-0', duplicate['errors'])
            self.assertEqual(validator._history_db.execute('SELECT count(*) FROM seen').fetchone()[0], 20)
            history_path = validator._history_dir.name
        self.assertFalse(os.path.exists(history_path))

    def test_history_limit_must_be_positive_integer(self):
        for limit in (0, -1, True, '2'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                LexicalValidator(max_history=limit)

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
        entry = {"id": "eng-dup-1", "surface": "word", "language": "eng", "pos": "noun"}
        res1 = self.validator.validate_entry(entry)
        self.assertEqual(res1["status"], "accepted")

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
        # Python allows storing lone surrogates in strings internally,
        # but they fail UTF-8 encoding.
        # \ud83d is a high surrogate for emojis, but without the low surrogate, it's invalid
        entry = {"id": "eng-uni-1", "surface": "bad\ud83dstring", "language": "eng", "pos": "noun"}
        result = self.validator.validate_entry(entry)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("invalid Unicode" in err for err in result["errors"]))

    def test_non_string_id_and_language_are_rejected_without_crash(self):
        for key, value in [('id', 123), ('id', ['wrong']),
                           ('language', 123), ('language', ['eng']),
                           ('pos', ['noun'])]:
            with self.subTest(key=key, value=value):
                entry = {'id': 'eng-safe', 'surface': 'word',
                         'language': 'eng', 'pos': 'noun'}
                entry[key] = value
                result = LexicalValidator().validate_entry(entry)
                self.assertEqual(result['status'], 'rejected')
                self.assertTrue(result['errors'])

    def test_pos_matches_canonical_schema_enum(self):
        from tools.lexical_quality.validator import POS_ALLOWED
        schema_path = os.path.join(os.path.dirname(__file__), '..', '..',
                                   'standards', 'lexical', 'lexical.schema.json')
        with open(schema_path, encoding='utf-8') as source:
            canonical = set(json.load(source)['$defs']['lexeme']['properties']['pos']['enum'])
        self.assertEqual(POS_ALLOWED, canonical)
        for pos in ('determiner', 'numeral', 'classifier', 'multiword', 'other'):
            entry = {'id': 'eng-pos-'+pos, 'surface': 'word',
                     'language': 'eng', 'pos': pos}
            self.assertEqual(LexicalValidator().validate_entry(entry)['status'], 'accepted')
        for pos in ('article', 'affix', 'phrase', 'idiom', 'proverb'):
            entry = {'id': 'eng-pos-'+pos, 'surface': 'word',
                     'language': 'eng', 'pos': pos}
            self.assertEqual(LexicalValidator().validate_entry(entry)['status'], 'rejected')

    def test_invalid_record_does_not_consume_valid_identifier(self):
        validator = LexicalValidator()
        invalid = {'id': 'eng-retain', 'surface': '', 'language': 'eng', 'pos': 'noun'}
        valid = {'id': 'eng-retain', 'surface': 'word', 'language': 'eng', 'pos': 'noun'}
        self.assertEqual(validator.validate_entry(invalid)['status'], 'rejected')
        self.assertEqual(validator.validate_entry(valid)['status'], 'accepted')

    def test_cli_rejects_non_object_and_oversized_records_then_recovers(self):
        from tools.lexical_quality.__main__ import main
        huge = b'{' + b' ' * (102400 + 32) + b'}\n'
        payload = (b'null\n[]\n' + huge +
                   b'{"id":"eng-ok","surface":"word","language":"eng","pos":"noun"}\n')
        incoming = io.TextIOWrapper(io.BytesIO(payload), encoding='utf-8')
        captured = io.StringIO()
        with patch('sys.stdin', incoming), patch('sys.stdout', captured):
            main()
        results = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertEqual([x['status'] for x in results],
                         ['rejected', 'rejected', 'rejected', 'accepted'])
        self.assertIn('size limit', ' '.join(results[2]['errors']).lower())

    def test_preserves_original_records(self):
        """Preserve original records for reversible remediation."""
        original = {"id": "eng-pres-1", "surface": "test", "language": "eng", "pos": "noun"}
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
