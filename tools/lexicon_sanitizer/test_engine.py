import unittest
import unicodedata
from pathlib import Path
from tools.lexicon_sanitizer.engine import (
    LexiconSanitizer,
    STATUS_ACCEPT,
    STATUS_REPAIRABLE,
    STATUS_QUARANTINE,
    STATUS_REVIEW_REQUIRED
)

class TestLexiconSanitizer(unittest.TestCase):
    def setUp(self):
        # Pass a dummy workspace path; we will manually set valid_languages for testing
        self.sanitizer = LexiconSanitizer()
        self.sanitizer.valid_languages = {"en", "de", "ar", "zh", "fr"}

    def test_german_umlauts_preserved(self):
        entry1 = {"lexeme_id": "de_apfel", "language": "de", "lemma": "Apfel", "pos": "noun"}
        entry2 = {"lexeme_id": "de_aepfel", "language": "de", "lemma": "Äpfel", "pos": "noun"}

        s1, _, _ = self.sanitizer.sanitize_lexeme(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_lexeme(entry2)
        self.assertEqual(s2, STATUS_ACCEPT)

    def test_arabic_diacritics_preserved(self):
        entry1 = {"lexeme_id": "ar_kutub", "language": "ar", "lemma": "كُتُب", "pos": "noun"}
        entry2 = {"lexeme_id": "ar_kataba", "language": "ar", "lemma": "كَتَبَ", "pos": "verb"}

        s1, _, _ = self.sanitizer.sanitize_lexeme(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_lexeme(entry2)
        self.assertEqual(s2, STATUS_ACCEPT)

    def test_arabic_normalization_collision(self):
        entry1 = {"lexeme_id": "ar_book1", "language": "ar", "lemma": "كتاب", "pos": "noun"}
        entry2 = {"lexeme_id": "ar_book2", "language": "ar", "lemma": "كتاب", "pos": "noun"}

        s1, _, _ = self.sanitizer.sanitize_lexeme(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_lexeme(entry2)
        self.assertEqual(s2, STATUS_REVIEW_REQUIRED)

    def test_cjk_homographs(self):
        entry1 = {"lexeme_id": "zh_test1", "language": "zh", "lemma": "干", "pos": "verb", "homograph_key": "1"}
        entry2 = {"lexeme_id": "zh_test2", "language": "zh", "lemma": "干", "pos": "verb", "homograph_key": "2"}

        s1, _, _ = self.sanitizer.sanitize_lexeme(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_lexeme(entry2)
        self.assertEqual(s2, STATUS_ACCEPT)

    def test_duplicate_ids(self):
        entry1 = {"lexeme_id": "dup_id", "language": "en", "lemma": "test", "pos": "noun"}
        entry2 = {"lexeme_id": "dup_id", "language": "en", "lemma": "other", "pos": "verb"}

        s1, _, _ = self.sanitizer.sanitize_lexeme(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_lexeme(entry2)
        self.assertEqual(s2, STATUS_QUARANTINE)

    def test_malformed_translations(self):
        entry1 = {
            "translation_id": "t1",
            "from_sense_id": "s1",
            "to_sense_id": "s2",
            "language": "en",
            "text": "   " # empty
        }
        s1, _, _ = self.sanitizer.sanitize_translation(entry1)
        self.assertEqual(s1, STATUS_QUARANTINE)

        entry2 = {
            "translation_id": "t2",
            "from_sense_id": "s1",
            "to_sense_id": "s2",
            "language": "en",
            "text": " repairable "
        }
        s2, mod, _ = self.sanitizer.sanitize_translation(entry2)
        self.assertEqual(s2, STATUS_REVIEW_REQUIRED)  # unknown senses and absent source
        self.assertEqual(mod["text"], "repairable")

    def test_mixed_language_entries(self):
        entry = {
            "translation_id": "t3",
            "from_sense_id": "s1",
            "to_sense_id": "s2",
            "language": "en",
            "text": "book كتاب"
        }
        s, _, _ = self.sanitizer.sanitize_translation(entry)
        self.assertEqual(s, STATUS_REVIEW_REQUIRED)

    def test_invalid_unicode(self):
        entry = {"lexeme_id": "bad_unicode", "language": "en", "lemma": "\ud800", "pos": "noun"}
        s, _, _ = self.sanitizer.sanitize_lexeme(entry)
        self.assertEqual(s, STATUS_QUARANTINE)

    def test_unsupported_language_code(self):
        entry = {"lexeme_id": "bad_lang", "language": "xx", "lemma": "test", "pos": "noun"}
        s, _, _ = self.sanitizer.sanitize_lexeme(entry)
        self.assertEqual(s, STATUS_QUARANTINE)

    def test_sense_duplicate_identity(self):
        self.assertEqual(self.sanitizer.sanitize_lexeme(
            {"lexeme_id": "l1", "language": "en", "lemma": "test", "pos": "noun"})[0], STATUS_ACCEPT)
        entry1 = {"sense_id": "s1", "lexeme_id": "l1", "concept_id": "c1"}
        entry2 = {"sense_id": "s2", "lexeme_id": "l1", "concept_id": "c1"}

        s1, _, _ = self.sanitizer.sanitize_sense(entry1)
        self.assertEqual(s1, STATUS_ACCEPT)

        s2, _, _ = self.sanitizer.sanitize_sense(entry2)
        self.assertEqual(s2, STATUS_REVIEW_REQUIRED)

if __name__ == '__main__':
    unittest.main()
