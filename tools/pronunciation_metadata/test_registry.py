import unittest
import json
from tools.pronunciation_metadata.registry import PronunciationRegistry, PronunciationRegistryError

class TestPronunciationRegistryValidCases(unittest.TestCase):
    def setUp(self):
        self.registry = PronunciationRegistry()
        self.valid_source = {
            "source_id": "src_01",
            "publisher": "Test Publisher",
            "dataset_version": "1.0",
            "license_id": "CC0",
            "publication_approved": True
        }

    def test_valid_record_with_ipa(self):
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_01",
                    "lexeme_id": "lex_01",
                    "language": "en",
                    "script": "Latn",
                    "locale": "en-US",
                    "offline_voice_status": "device_installed",
                    "source": self.valid_source,
                    "pronunciations": [
                        {
                            "notation": "ipa",
                            "value": "tɛst",
                            "source": self.valid_source
                        }
                    ]
                }
            ]
        }
        self.registry.load_records(json.dumps(doc))
        self.assertIn("rec_01", self.registry.records)

    def test_dialects_and_ipa_variants(self):
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_02",
                    "lexeme_id": "lex_02",
                    "language": "en",
                    "script": "Latn",
                    "locale": "en-GB",
                    "dialect": "Cockney",
                    "offline_voice_status": "unknown",
                    "source": self.valid_source,
                    "pronunciations": [
                        {
                            "notation": "ipa",
                            "value": "wɔːtə",
                            "dialect": "RP",
                            "source": self.valid_source
                        },
                        {
                            "notation": "ipa",
                            "value": "wɔːʔə",
                            "dialect": "Cockney",
                            "source": self.valid_source
                        }
                    ]
                }
            ]
        }
        self.registry.load_records(json.dumps(doc))
        self.assertIn("rec_02", self.registry.records)

    def test_missing_evidence_handling(self):
        # A valid record can have no pronunciations if there's no source evidence.
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_03",
                    "lexeme_id": "lex_03",
                    "language": "es",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": self.valid_source
                }
            ]
        }
        self.registry.load_records(json.dumps(doc))
        self.assertIn("rec_03", self.registry.records)

    def test_cjk_phonetic_representation(self):
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_04",
                    "lexeme_id": "lex_04",
                    "language": "zh",
                    "script": "Hans",
                    "locale": "zh-CN",
                    "offline_voice_status": "unknown",
                    "source": self.valid_source,
                    "pronunciations": [
                        {
                            "notation": "phonetic",
                            "value": "bō",
                            "phonetic_note": "Pinyin",
                            "source": self.valid_source
                        }
                    ]
                }
            ]
        }
        # It should allow phonetic and romanization notes without IPA CJK checking
        self.registry.load_records(json.dumps(doc))
        self.assertIn("rec_04", self.registry.records)

class TestPronunciationRegistryInvalidCases(unittest.TestCase):
    def setUp(self):
        self.registry = PronunciationRegistry()
        self.valid_source = {
            "source_id": "src_01",
            "publisher": "Test Publisher",
            "dataset_version": "1.0",
            "license_id": "CC0",
            "publication_approved": True
        }

    def test_invalid_locale_wrong_language(self):
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_inv1",
                    "lexeme_id": "lex_01",
                    "language": "en",
                    "script": "Latn",
                    "locale": "fr-FR",  # Doesn't match 'en'
                    "offline_voice_status": "unknown",
                    "source": self.valid_source
                }
            ]
        }
        with self.assertRaisesRegex(PronunciationRegistryError, "wrong-language locale mapping"):
            self.registry.load_records(json.dumps(doc))

    def test_cjk_characters_in_ipa_rejected(self):
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_inv2",
                    "lexeme_id": "lex_02",
                    "language": "zh",
                    "script": "Hans",
                    "offline_voice_status": "unknown",
                    "source": self.valid_source,
                    "pronunciations": [
                        {
                            "notation": "ipa",
                            "value": "测试",  # CJK in IPA notation is invalid
                            "source": self.valid_source
                        }
                    ]
                }
            ]
        }
        with self.assertRaisesRegex(PronunciationRegistryError, "CJK characters found in IPA notation"):
            self.registry.load_records(json.dumps(doc))

    def test_unverified_source_record(self):
        unverified_source = self.valid_source.copy()
        unverified_source["publication_approved"] = False
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_inv3",
                    "lexeme_id": "lex_03",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": unverified_source
                }
            ]
        }
        with self.assertRaisesRegex(PronunciationRegistryError, "unverified source reference"):
            self.registry.load_records(json.dumps(doc))

    def test_unverified_source_pronunciation(self):
        unverified_source = self.valid_source.copy()
        unverified_source["publication_approved"] = False
        doc = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "rec_inv4",
                    "lexeme_id": "lex_04",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": self.valid_source,
                    "pronunciations": [
                        {
                            "notation": "ipa",
                            "value": "tɛst",
                            "source": unverified_source
                        }
                    ]
                }
            ]
        }
        with self.assertRaisesRegex(PronunciationRegistryError, "unverified source reference in pronunciation"):
            self.registry.load_records(json.dumps(doc))

    def test_unbounded_input_size(self):
        # Create a string larger than 10MB
        large_str = " " * (10 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(PronunciationRegistryError, "Document too large"):
            self.registry.load_records(large_str)

    def test_schema_malformed_metadata(self):
        with self.assertRaisesRegex(PronunciationRegistryError, "Malformed JSON"):
            self.registry.load_records("{ invalid json")

class TestPronunciationRegistryCompilation(unittest.TestCase):
    def test_incremental_deterministic_compilation(self):
        registry = PronunciationRegistry()
        valid_source = {
            "source_id": "src_01",
            "publisher": "Test",
            "dataset_version": "1.0",
            "license_id": "CC0",
            "publication_approved": True
        }

        doc1 = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "b_rec",
                    "lexeme_id": "lex_b",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": valid_source
                },
                {
                    "record_id": "a_rec",
                    "lexeme_id": "lex_a",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": valid_source
                }
            ]
        }
        registry.load_records(json.dumps(doc1))

        # Test incremental update
        doc2 = {
            "registry_version": "1.0.0",
            "records": [
                {
                    "record_id": "c_rec",
                    "lexeme_id": "lex_c",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "unknown",
                    "source": valid_source
                },
                {
                    "record_id": "b_rec",
                    "lexeme_id": "lex_b",
                    "language": "en",
                    "script": "Latn",
                    "offline_voice_status": "device_installed",
                    "source": valid_source
                }
            ]
        }
        registry.load_records(json.dumps(doc2))

        exported = registry.export()
        exported_data = json.loads(exported)

        # Should be exactly 3 records: a, b, c
        self.assertEqual(len(exported_data["records"]), 3)

        # Must be deterministically sorted
        self.assertEqual(exported_data["records"][0]["record_id"], "a_rec")
        self.assertEqual(exported_data["records"][1]["record_id"], "b_rec")
        self.assertEqual(exported_data["records"][2]["record_id"], "c_rec")

        # b_rec should reflect the incremental update
        self.assertEqual(exported_data["records"][1]["offline_voice_status"], "device_installed")

if __name__ == '__main__':
    unittest.main()
