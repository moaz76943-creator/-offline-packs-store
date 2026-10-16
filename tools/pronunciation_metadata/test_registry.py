import unittest
import json
from tools.pronunciation_metadata.registry import PronunciationRegistry

class TestPronunciationRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = PronunciationRegistry()

    def test_valid_entry(self):
        record = {
            "lexical_entry_id": "test1",
            "language": "eng",
            "provenance_id": "prov1",
            "source_version": "1.0",
            "offline_availability": "unknown",
            "ipa": "tɛst",
            "locale": "en-US",
            "dialect": "American English",
            "variants": ["tɛst"]
        }
        self.registry.add_record(json.dumps(record))
        self.assertIn("test1", self.registry.records)

    def test_missing_evidence(self):
        record = {
            "lexical_entry_id": "test2",
            "language": "eng",
            "offline_availability": "unknown"
            # Missing provenance_id and source_version
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(json.dumps(record))

    def test_cjk_phonetics(self):
        record = {
            "lexical_entry_id": "test3",
            "language": "zho",
            "provenance_id": "prov3",
            "source_version": "1.0",
            "offline_availability": "unsupported",
            "phonetic_transliteration": "ni3 hao3" # Pinyin, not IPA
        }
        self.registry.add_record(json.dumps(record))
        self.assertEqual(self.registry.records["test3"]["phonetic_transliteration"], "ni3 hao3")

    def test_invalid_locale(self):
        record = {
            "lexical_entry_id": "test4",
            "language": "eng",
            "provenance_id": "prov1",
            "source_version": "1.0",
            "offline_availability": "unknown",
            "locale": "invalid_locale_format"
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(json.dumps(record))

    def test_invalid_ipa(self):
        record = {
            "lexical_entry_id": "test5",
            "language": "eng",
            "provenance_id": "prov1",
            "source_version": "1.0",
            "offline_availability": "unknown",
            "ipa": "apple" # Just English letters, no phonetic symbols
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(json.dumps(record))

    def test_wrong_language_provenance(self):
        record = {
            "lexical_entry_id": "test6",
            "language": "fra", # Mismatched language
            "provenance_id": "prov1", # prov1 is bound to 'eng'
            "source_version": "1.0",
            "offline_availability": "unknown"
        }
        with self.assertRaises(ValueError):
            self.registry.add_record(json.dumps(record))

    def test_incremental_and_deterministic(self):
        record1 = {
            "lexical_entry_id": "b_test",
            "language": "eng",
            "provenance_id": "prov1",
            "source_version": "1.0",
            "offline_availability": "unknown"
        }
        record2 = {
            "lexical_entry_id": "a_test",
            "language": "eng",
            "provenance_id": "prov1",
            "source_version": "1.0",
            "offline_availability": "unknown"
        }
        self.registry.incremental_update(json.dumps(record1))
        self.registry.incremental_update(json.dumps(record2))
        compiled = self.registry.compile_registry()
        self.assertEqual(compiled[0]["lexical_entry_id"], "a_test")
        self.assertEqual(compiled[1]["lexical_entry_id"], "b_test")

if __name__ == '__main__':
    unittest.main()
