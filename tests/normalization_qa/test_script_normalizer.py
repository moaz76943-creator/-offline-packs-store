import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.normalization.script_normalizer import (
    normalize_turkish,
    normalize_arabic,
    normalize_for_language
)

class TestScriptNormalizer(unittest.TestCase):
    def test_turkish_dotted_and_dotless_i(self):
        # 'I' (capital dotless) must lowercase to 'ı' (U+0131), NOT 'i'
        self.assertEqual(normalize_turkish("IRMAK", to_lower=True), "ırmak")
        # 'İ' (capital dotted) must lowercase to 'i'
        self.assertEqual(normalize_turkish("İSTANBUL", to_lower=True), "istanbul")

    def test_arabic_tashkeel_stripping_and_hamza_harmonization(self):
        vocalized = "كِتَابٌ جَدِيدٌ"
        stripped = normalize_arabic(vocalized, strip_tashkeel=True)
        self.assertEqual(stripped, "كتاب جديد")

        # Hamza harmonization for typo-tolerant FTS search
        hamza_word = "أَحْمَدُ"
        search_key = normalize_arabic(hamza_word, strip_tashkeel=True, harmonize_hamza=True)
        self.assertEqual(search_key, "احمد")

    def test_german_umlauts_canonical_nfc(self):
        # Decomposed Umlaut 'a' + U+0308 -> 'ä'
        decomposed = "a\u0308pfel"
        normalized = normalize_for_language(decomposed, "de", search_mode=False)
        self.assertEqual(normalized, "äpfel")

if __name__ == "__main__":
    unittest.main()
