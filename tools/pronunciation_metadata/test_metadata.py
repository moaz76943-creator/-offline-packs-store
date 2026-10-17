import unittest
import os
import json
import tempfile
from registry import PronunciationRegistry

class TestPronunciationMetadata(unittest.TestCase):
    def setUp(self):
        self.schema_path = os.path.join(os.path.dirname(__file__), "pronunciation.schema.json")
        self.registry = PronunciationRegistry(self.schema_path)

    def test_valid_ipa(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "installed",
            "source": {
                "source_id": "src-1",
                "dataset_version": "v1.0"
            }
        }
        self.registry.add_record(record)
        self.assertEqual(len(self.registry.records), 1)

    def test_invalid_ipa_symbols(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hello@123", # contains @ and numbers
            "offline_voice_support": "unknown",
            "source": {
                "source_id": "src-1",
                "dataset_version": "v1.0"
            }
        }
        with self.assertRaisesRegex(ValueError, "Invalid Unicode IPA symbols detected"):
            self.registry.add_record(record)

    def test_dialect_and_unknown_voice(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "es",
            "script": "Latn",
            "locale": "es-MX",
            "dialect": "Mexican Spanish",
            "notation": "ipa",
            "value": "o.la",
            "offline_voice_support": "unknown",
            "source": {
                "source_id": "src-1",
                "dataset_version": "v1.0"
            }
        }
        self.registry.add_record(record)
        self.assertEqual(len(self.registry.records), 1)

    def test_cjk_phonetic_representation(self):
        record = {
            "lexeme_id": "test-lex-2",
            "language": "zh",
            "script": "Hans",
            "locale": "zh-CN",
            "notation": "romanization", # e.g. pinyin
            "value": "nǐ hǎo",
            "offline_voice_support": "unsupported",
            "source": {
                "source_id": "src-1",
                "dataset_version": "v1.0"
            }
        }
        self.registry.add_record(record)
        self.assertEqual(len(self.registry.records), 1)

    def test_missing_evidence_unverified_source(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "installed",
            "source": {
                "source_id": "src-1"
                # Missing dataset_version
            }
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(record)

    def test_auto_gen_orthography_rejected(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "unknown",
            "source": {
                "source_id": "auto-gen-orthography",
                "dataset_version": "v1.0"
            }
        }
        with self.assertRaisesRegex(ValueError, "Auto-generating pronunciation from orthographic spelling is not allowed"):
            self.registry.add_record(record)

    def test_deterministic_output_and_incremental(self):
        record1 = {
            "lexeme_id": "lex-1",
            "language": "en",
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "unknown",
            "source": {"source_id": "src-1", "dataset_version": "v1.0"}
        }
        record2 = {
            "lexeme_id": "lex-2",
            "language": "fr",
            "script": "Latn",
            "locale": "fr-FR",
            "notation": "ipa",
            "value": "bɔ̃.ʒuʁ",
            "offline_voice_support": "installed",
            "source": {"source_id": "src-1", "dataset_version": "v1.0"}
        }

        self.registry.add_record(record2)
        self.registry.add_record(record1)

        # Adding record1 again should just overwrite/update incrementally based on key
        self.registry.add_record(record1)
        self.assertEqual(len(self.registry.records), 2)

        doc = self.registry.compile("doc-1")
        # Ensure it's sorted by key for determinism
        # key format: {lang}|{lexeme}|{val}|{notat}|{dialect}
        # record1 key: en|lex-1|hɛˈloʊ|ipa|
        # record2 key: fr|lex-2|bɔ̃.ʒuʁ|ipa|
        # "en" comes before "fr"
        self.assertEqual(doc["pronunciations"][0]["language"], "en")
        self.assertEqual(doc["pronunciations"][1]["language"], "fr")

    def test_wrong_language_format(self):
        record = {
            "lexeme_id": "test-lex-1",
            "language": "English", # Invalid, must match ^[a-z]{2,3}... pattern
            "script": "Latn",
            "locale": "en-US",
            "notation": "ipa",
            "value": "hɛˈloʊ",
            "offline_voice_support": "unknown",
            "source": {
                "source_id": "src-1",
                "dataset_version": "v1.0"
            }
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(record)

if __name__ == '__main__':
    unittest.main()
