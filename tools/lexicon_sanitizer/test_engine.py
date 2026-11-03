import unittest
from tools.lexicon_sanitizer.engine import SanitizerEngine

class TestSanitizerEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SanitizerEngine(registry_path="catalog/language_registry.v1.json")
        # Ensure we have some valid languages for tests
        self.engine.valid_languages.add("en")
        self.engine.valid_languages.add("ar")
        self.engine.valid_languages.add("de")
        self.engine.valid_languages.add("zh")

    def create_valid_record(self):
        return {
            "contract_version": "1.0.0",
            "document_id": "doc.en.word",
            "lexemes": [
                {
                    "lexeme_id": "lex.en.1",
                    "language": "en",
                    "lemma": "word",
                    "surface": "word",
                    "pos": "noun"
                }
            ],
            "senses": [
                {
                    "sense_id": "sense.en.1",
                    "concept_id": "concept.1",
                    "definition": "A unit of language."
                }
            ],
            "translations": [
                {
                    "translation_id": "trans.1"
                }
            ],
            "examples": [],
            "relations": []
        }

    def test_accept_valid(self):
        record = self.create_valid_record()
        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_ACCEPT)

    def test_quarantine_missing_keys(self):
        record = {"contract_version": "1.0.0"} # Missing document_id, lexemes, etc.
        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

    def test_repairable_whitespace(self):
        record = self.create_valid_record()
        record["document_id"] = "  doc.en.word  "
        record["lexemes"][0]["lemma"] = " word "

        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_REPAIRABLE)
        self.assertEqual(repaired["document_id"], "doc.en.word")
        self.assertEqual(repaired["lexemes"][0]["lemma"], "word")

    def test_quarantine_invalid_unicode(self):
        record = self.create_valid_record()
        record["lexemes"][0]["lemma"] = "word\ud800" # surrogate pair
        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

    def test_arabic_normalization_collisions_preserved(self):
        # tests for Arabic normalization collisions
        # Two distinct records with different Arabic diacritics but same base characters
        record1 = self.create_valid_record()
        record1["document_id"] = "doc.ar.1"
        record1["lexemes"][0]["language"] = "ar"
        record1["lexemes"][0]["lemma"] = "كَتَبَ" # kataba
        record1["lexemes"][0]["surface"] = "كَتَبَ"
        record1["senses"][0]["definition"] = "he wrote"

        record2 = self.create_valid_record()
        record2["document_id"] = "doc.ar.2"
        record2["lexemes"][0]["language"] = "ar"
        record2["lexemes"][0]["lemma"] = "كُتِبَ" # kutiba
        record2["lexemes"][0]["surface"] = "كُتِبَ"
        record2["senses"][0]["definition"] = "it was written"

        status1, _, _ = self.engine.validate_and_repair(record1)
        status2, _, _ = self.engine.validate_and_repair(record2)

        self.assertEqual(status1, SanitizerEngine.STATUS_ACCEPT)
        self.assertEqual(status2, SanitizerEngine.STATUS_ACCEPT)
        # Should not be flagged as duplicates

    def test_duplicate_identity_quarantine(self):
        record1 = self.create_valid_record()
        record2 = self.create_valid_record() # Exact same content

        status1, _, _ = self.engine.validate_and_repair(record1)
        self.assertEqual(status1, SanitizerEngine.STATUS_ACCEPT)

        status2, _, _ = self.engine.validate_and_repair(record2)
        self.assertEqual(status2, SanitizerEngine.STATUS_QUARANTINE)

    def test_german_umlauts_preserved(self):
        # tests for German umlauts
        record1 = self.create_valid_record()
        record1["document_id"] = "doc.de.1"
        record1["lexemes"][0]["language"] = "de"
        record1["lexemes"][0]["lemma"] = "schon"
        record1["senses"][0]["definition"] = "already"

        record2 = self.create_valid_record()
        record2["document_id"] = "doc.de.2"
        record2["lexemes"][0]["language"] = "de"
        record2["lexemes"][0]["lemma"] = "schön"
        record2["senses"][0]["definition"] = "beautiful"

        status1, _, _ = self.engine.validate_and_repair(record1)
        status2, _, _ = self.engine.validate_and_repair(record2)

        self.assertEqual(status1, SanitizerEngine.STATUS_ACCEPT)
        self.assertEqual(status2, SanitizerEngine.STATUS_ACCEPT)

    def test_cjk_homographs_preserved(self):
        # tests for CJK homographs
        record1 = self.create_valid_record()
        record1["document_id"] = "doc.zh.1"
        record1["lexemes"][0]["language"] = "zh"
        record1["lexemes"][0]["lemma"] = "行"
        record1["lexemes"][0]["surface"] = "行"
        record1["senses"][0]["definition"] = "to walk (xíng)"

        record2 = self.create_valid_record()
        record2["document_id"] = "doc.zh.2"
        record2["lexemes"][0]["language"] = "zh"
        record2["lexemes"][0]["lemma"] = "行"
        record2["lexemes"][0]["surface"] = "行"
        record2["senses"][0]["definition"] = "profession (háng)"

        status1, _, _ = self.engine.validate_and_repair(record1)
        status2, _, _ = self.engine.validate_and_repair(record2)

        # They have the same lemma but different definitions, they should not collide
        self.assertEqual(status1, SanitizerEngine.STATUS_ACCEPT)
        self.assertEqual(status2, SanitizerEngine.STATUS_ACCEPT)

    def test_malformed_translations(self):
        # tests for malformed translations
        record = self.create_valid_record()
        # Missing translation_id
        record["translations"][0] = {"some_other_key": "value"}
        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

    def test_mixed_language_entries(self):
        # tests for mixed-language entries
        # A record claiming to be English but using an unsupported language
        record = self.create_valid_record()
        record["lexemes"][0]["language"] = "xx" # Not in our valid set
        status, repaired, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

    def test_duplicate_ids(self):
        record1 = self.create_valid_record()
        record2 = self.create_valid_record()

        # Make them have different identities but the same document_id
        record2["lexemes"][0]["lemma"] = "another_word"

        status1, _, _ = self.engine.validate_and_repair(record1)
        self.assertEqual(status1, SanitizerEngine.STATUS_ACCEPT)

        status2, _, _ = self.engine.validate_and_repair(record2)
        self.assertEqual(status2, SanitizerEngine.STATUS_QUARANTINE)

    def test_rejected_document_does_not_reserve_document_id(self):
        invalid = self.create_valid_record()
        invalid['lexemes'][0]['language'] = 'not-registered'
        status, _, _ = self.engine.validate_and_repair(invalid)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

        valid = self.create_valid_record()
        status, _, _ = self.engine.validate_and_repair(valid)
        self.assertEqual(status, SanitizerEngine.STATUS_ACCEPT)
        self.assertIn('doc.en.word', self.engine.seen_doc_ids)

    def test_null_sense_definition_is_quarantined(self):
        record = self.create_valid_record()
        record['senses'][0]['definition'] = None
        status, _, reason = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)
        self.assertIn('definition must be a string', reason)

    def test_impossible_field_types(self):
        record = self.create_valid_record()
        record["lexemes"][0]["lemma"] = 123
        status, _, _ = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

        record = self.create_valid_record()
        record["senses"][0]["definition"] = ["a", "b"]
        status, _, _ = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

        record = self.create_valid_record()
        record["contract_version"] = 1.0
        status, _, _ = self.engine.validate_and_repair(record)
        self.assertEqual(status, SanitizerEngine.STATUS_QUARANTINE)

if __name__ == '__main__':
    unittest.main()
