import unittest
from tools.compile_store_packs import arabic_translations

class ArabicTranslationsTest(unittest.TestCase):
    def test_empty_dict(self):
        self.assertEqual(arabic_translations({}), "")

    def test_translation_ar_string(self):
        self.assertEqual(arabic_translations({'translation_ar': '  مرحبا  '}), "مرحبا")

    def test_translation_ar_list(self):
        self.assertEqual(arabic_translations({'translation_ar': ['  مرحبا  ', ' أهلا ']}), "مرحبا\nأهلا")

    def test_translations_dict(self):
        self.assertEqual(arabic_translations({'translations': {'ar': 'مرحبا', 'en': 'hello'}}), "مرحبا")

    def test_translations_list_languageCode(self):
        fields = {
            'translations': [
                {'languageCode': 'en', 'text': 'hello'},
                {'languageCode': 'ar', 'text': 'مرحبا'}
            ]
        }
        self.assertEqual(arabic_translations(fields), "مرحبا")

    def test_translations_list_language_code(self):
        fields = {
            'translations': [
                {'language_code': 'ar', 'text': 'أهلا'},
                {'language_code': 'fr', 'text': 'bonjour'}
            ]
        }
        self.assertEqual(arabic_translations(fields), "أهلا")

    def test_translationLanguageCode(self):
        fields = {
            'translationLanguageCode': 'ar',
            'translation': 'مرحبا'
        }
        self.assertEqual(arabic_translations(fields), "مرحبا")

    def test_translation_language_code(self):
        fields = {
            'translation_language_code': 'ar',
            'translation': 'أهلا'
        }
        self.assertEqual(arabic_translations(fields), "أهلا")

    def test_deduplication_and_multiple_sources(self):
        fields = {
            'translation_ar': 'مرحبا',
            'translations': {'ar': '  مرحبا  '},
            'translationLanguageCode': 'ar',
            'translation': 'أهلا'
        }
        self.assertEqual(arabic_translations(fields), "مرحبا\nأهلا")

if __name__ == '__main__':
    unittest.main()
