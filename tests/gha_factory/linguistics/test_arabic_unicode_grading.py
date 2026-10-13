"""QA-only Unicode grading tests; synthetic strings, not source attestations."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools' / 'gha_factory' / 'linguistics'))
from validator import classify_answer


def form(surface, *, sense='ar:test:sense', features=None, language='ar'):
    return {'language_code': language, 'lemma_id': language + ':test:lemma',
            'sense_id': sense, 'form': surface,
            'features': {'tense': 'past'} if features is None else features}


class ArabicUnicodeGradingTests(unittest.TestCase):
    def test_nfc_decomposed_madda_is_correct(self):
        self.assertEqual(classify_answer('ا\u0653مَنَ', form('آمَنَ')), 'correct')

    def test_nfc_decomposed_hamza_below_is_correct(self):
        self.assertEqual(classify_answer('ا\u0655ِنْسَان', form('إِنْسَان')), 'correct')

    def test_vowel_contrast_without_attestation_is_unknown(self):
        self.assertEqual(classify_answer('عُلِمَ', form('عَلِمَ')), 'unverified')

    def test_tanwin_contrast_without_attestation_is_unknown(self):
        self.assertEqual(classify_answer('كِتَابٍ', form('كِتَابٌ')), 'unverified')

    def test_missing_tashkeel_is_not_automatically_accepted(self):
        self.assertEqual(classify_answer('علم', form('عَلِمَ')), 'unverified')

    def test_attested_nfc_variant_same_features_is_correct(self):
        expected=form('سَأَلَ')
        self.assertEqual(classify_answer('ا\u0653مَنَ', expected, [form('آمَنَ')]), 'correct')

    def test_attested_different_features_proves_morphology_error(self):
        expected=form('عَلِمَ')
        other=form('عُلِمَ', features={'voice': 'passive'})
        self.assertEqual(classify_answer('عُلِمَ', expected, [other]), 'morphology_error')

    def test_other_sense_never_proves_morphology(self):
        expected=form('عَلِمَ')
        other=form('عُلِمَ', sense='ar:other:sense', features={'voice': 'passive'})
        self.assertEqual(classify_answer('عُلِمَ', expected, [other]), 'unverified')

    def test_base_letter_typo_remains_spelling(self):
        self.assertEqual(classify_answer('كَتَمَ', form('كَتَبَ')), 'spelling_error')

    def test_non_arabic_diacritic_still_spelling(self):
        self.assertEqual(classify_answer('schon', form('schön', language='de')), 'spelling_error')

    def test_compatibility_glyph_not_auto_correct(self):
        self.assertNotEqual(classify_answer('ﻻ', form('لا')), 'correct')

    def test_different_language_attestation_is_ignored(self):
        expected=form('عَلِمَ')
        foreign=form('عُلِمَ', language='de', features={'voice': 'passive'})
        self.assertEqual(classify_answer('عُلِمَ', expected, [foreign]), 'unverified')


if __name__ == '__main__':
    unittest.main()
