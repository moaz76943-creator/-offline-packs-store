"""Synthetic-only regression tests for Arabic root Unicode shape (GHA-04).

These examples are structural test fixtures, not source attestations or corpus.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gha_factory" / "linguistics"))
from validator import LinguisticError, validate_form


def fixture(root, language="ar"):
    return {
        "language_code": language,
        "lemma_id": language + ":fixture:lemma",
        "sense_id": language + ":fixture:sense",
        "lemma": "fixture",
        "form": "fixture",
        "features": {},
        "source_id": "synthetic-qa-only",
        "evidence_version": "test-1",
        "root": root,
    }


class ArabicRootUnicodeTests(unittest.TestCase):
    def test_arabic_tatweel_is_not_a_root_letter(self):
        for root in ("ك-ـ-ب", "ـ-ت-ب", "ك-ت-ب-ـ"):
            with self.subTest(root=root), self.assertRaises(LinguisticError):
                validate_form(fixture(root), {"ar"})

    def test_arabic_letters_including_hamza_remain_accepted(self):
        for root in ("ك-ت-ب", "ء-ك-ل", "د-ح-ر-ج"):
            with self.subTest(root=root):
                self.assertTrue(validate_form(fixture(root), {"ar"}))

    def test_diacritic_punctuation_and_non_arabic_script_rejected(self):
        for root in ("ك-َ-ب", "ك-?-ب", "ك-t-ب", "ك-ت-ب-ب-ب"):
            with self.subTest(root=root), self.assertRaises(LinguisticError):
                validate_form(fixture(root), {"ar"})

    def test_non_arabic_morphology_does_not_inherit_root_rule(self):
        self.assertTrue(validate_form(fixture("A-B-C", language="tr"), {"tr"}))


if __name__ == "__main__":
    unittest.main()
