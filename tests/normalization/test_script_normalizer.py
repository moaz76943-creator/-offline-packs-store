import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.normalization.script_normalizer import (
    normalize_arabic,
    fold_german_umlauts,
    normalize_turkish_case
)

class TestScriptNormalizer(unittest.TestCase):
    def test_arabic_diacritic_and_alef_normalization(self):
        # تجريد الحركات وتوحيد الألف والتاء المربوطة
        raw_ar = "كِتَابٌ أَبْيَضُ وَوَرْدَةٌ"
        normalized = normalize_arabic(raw_ar)
        self.assertEqual(normalized, "كتاب ابيض وورده")

    def test_german_umlaut_folding(self):
        raw_de = "Bücher und Äpfel"
        folded = fold_german_umlauts(raw_de)
        self.assertEqual(folded, "Buecher und Aepfel")

    def test_turkish_dotted_dotless_i(self):
        # التركية: İstanbul -> istanbul (وليس ıstanbul)
        self.assertEqual(normalize_turkish_case("İSTANBUL"), "istanbul")
        self.assertEqual(normalize_turkish_case("ISPARTA"), "ısparta")

if __name__ == '__main__':
    unittest.main()
