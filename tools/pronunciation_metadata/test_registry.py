import unittest
import json
from tools.pronunciation_metadata.registry import PronunciationRegistry

class TestPronunciationRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = PronunciationRegistry()
        self.valid_record = {
            "schema_version": "1.0.0",
            "id": "pron_eng_12345",
            "language": "eng",
            "lexical_entry_id": "word.eng.test",
            "ipa": "tɛst",
            "offline_voice_availability": "supported",
            "provenance_id": "source.eng.dict",
            "source_version": "v1.2.3"
        }

    def test_valid_record(self):
        self.registry.add_record(self.valid_record)
        self.assertIn("pron_eng_12345", self.registry.records)

    def test_missing_language(self):
        record = self.valid_record.copy()
        del record["language"]
        with self.assertRaises(ValueError):
            self.registry.add_record(record)

    def test_missing_lexical_entry_id(self):
        record = self.valid_record.copy()
        del record["lexical_entry_id"]
        with self.assertRaises(ValueError):
            self.registry.add_record(record)

    def test_valid_ipa(self):
        record = self.valid_record.copy()
        record["ipa"] = "ˌpɹoʊnʌnsiˈeɪʃən"
        self.registry.add_record(record)
        self.assertIn("pron_eng_12345", self.registry.records)

    def test_invalid_ipa_control_char(self):
        record = self.valid_record.copy()
        record["ipa"] = "tɛst\x00"
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record)
        self.assertIn("Invalid character in IPA string", str(context.exception))

    def test_missing_actual_pronunciation(self):
        record = self.valid_record.copy()
        del record["ipa"]
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record)
        self.assertIn("lacks any actual pronunciation data", str(context.exception))

    def test_phonetic_transliteration_instead_of_ipa(self):
        record = self.valid_record.copy()
        del record["ipa"]
        record["phonetic_transliteration"] = "test"
        self.registry.add_record(record)
        self.assertIn("pron_eng_12345", self.registry.records)

    def test_input_size_bounds(self):
        record = self.valid_record.copy()
        record["phonetic_notes"] = "a" * 5000 # exceeds 4096 json
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record)
        self.assertIn("exceeds maximum bounded input size", str(context.exception))

    def test_cjk_phonetic_representation(self):
        record = self.valid_record.copy()
        record["id"] = "pron_zho_1"
        record["language"] = "zho"
        del record["ipa"]
        record["phonetic_transliteration"] = "pīn yīn" # valid pinyin
        record["phonetic_notes"] = "bopomofo: ㄆㄧㄣ ㄧㄣ"
        self.registry.add_record(record)
        self.assertIn("pron_zho_1", self.registry.records)

    def test_invalid_locale(self):
        record = self.valid_record.copy()
        record["locale"] = "invalid-locale-string-too-long"
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record)
        self.assertIn("Schema validation failed", str(context.exception))

    def test_wrong_language_format(self):
        record = self.valid_record.copy()
        record["language"] = "english" # not a valid 2/3 letter code
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record)
        self.assertIn("Schema validation failed", str(context.exception))

    def test_missing_evidence(self):
        record = self.valid_record.copy()
        del record["provenance_id"]
        with self.assertRaises(ValueError):
            self.registry.add_record(record)

    def test_unverified_source_reference_mock(self):
        # Using the catalog_validator hook
        def mock_catalog_validator(r):
            if r["provenance_id"] != "approved.source":
                raise ValueError("Unverified source reference")

        record = self.valid_record.copy()
        record["provenance_id"] = "unapproved.source"
        with self.assertRaises(ValueError) as context:
            self.registry.add_record(record, catalog_validator=mock_catalog_validator)
        self.assertIn("Unverified source reference", str(context.exception))

    def test_dialect_variant(self):
        record = self.valid_record.copy()
        record["dialect"] = "American English"
        record["variants"] = ["alternative_1"]
        self.registry.add_record(record)
        self.assertEqual(self.registry.records["pron_eng_12345"]["dialect"], "American English")

    def test_deterministic_compilation(self):
        record1 = self.valid_record.copy()
        record1["id"] = "pron_eng_B"

        record2 = self.valid_record.copy()
        record2["id"] = "pron_eng_A"

        # Add out of order
        self.registry.add_record(record1)
        self.registry.add_record(record2)

        compiled_json = self.registry.compile()
        compiled_data = json.loads(compiled_json)

        # Check order of items is deterministic (A then B)
        self.assertEqual(compiled_data[0]["id"], "pron_eng_A")
        self.assertEqual(compiled_data[1]["id"], "pron_eng_B")

        # Check keys are ordered deterministically
        keys = list(compiled_data[0].keys())
        self.assertEqual(keys, sorted(keys))

    def test_incremental_updates(self):
        # 1. Add new record
        record1 = self.valid_record.copy()

        # 2. Update existing record (new version)
        record2 = self.valid_record.copy()
        record2["id"] = "pron_eng_2"
        record2["source_version"] = "v1.0"
        self.registry.add_record(record2)

        record2_updated = record2.copy()
        record2_updated["source_version"] = "v2.0"
        record2_updated["ipa"] = "tɛst2"

        # 3. Skipped record (same version)
        record3 = self.valid_record.copy()
        record3["id"] = "pron_eng_3"
        self.registry.add_record(record3)

        stream = [record1, record2_updated, record3]

        result = self.registry.incremental_update(stream)

        self.assertEqual(result["added"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped"], 1)

        self.assertEqual(self.registry.records["pron_eng_2"]["ipa"], "tɛst2")

if __name__ == '__main__':
    unittest.main()
