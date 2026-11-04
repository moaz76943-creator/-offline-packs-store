import unittest
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from validator import MorphologyValidator

class TestMorphologyValidatorBasic(unittest.TestCase):
    def setUp(self):
        self.validator = MorphologyValidator()


        self.valid_base = {
            "language_code": "de",
            "lemma_id": "de:Buch:1",
            "sense_id": "de:Buch:book",
            "lemma": "Buch",
            "form": "Buch",
            "features": {"number": "singular", "case": "nominative"},
            "source_id": "wiktionary-de-buch",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }

    def test_valid_record(self):
        self.assertTrue(self.validator.validate(self.valid_base))

    def test_valid_transliteration(self):
        trans_record = self.valid_base.copy()
        trans_record["transliteration"] = "book"
        self.assertTrue(self.validator.validate(trans_record))

    def test_typed_features(self):
        typed_record = self.valid_base.copy()
        typed_record["features"] = {
            "is_plural": True,
            "weight": 2.5,
            "count": 10,
            "unknown_feature": None,
            "case": "nominative"
        }
        self.assertTrue(self.validator.validate(typed_record))

    def test_invalid_schema(self):
        invalid_record = self.valid_base.copy()
        del invalid_record["form"]
        with self.assertRaises(ValueError) as context:
            self.validator.validate(invalid_record)
        self.assertIn("Schema validation failed", str(context.exception))

    def test_invalid_lemma_id_prefix(self):
        invalid_record = self.valid_base.copy()
        invalid_record["lemma_id"] = "en:Buch:1"
        with self.assertRaises(ValueError) as context:
            self.validator.validate(invalid_record)
        self.assertIn("must start with language_code", str(context.exception))

    def test_invalid_sense_id_prefix(self):
        invalid_record = self.valid_base.copy()
        invalid_record["sense_id"] = "en:Buch:book"
        with self.assertRaises(ValueError) as context:
            self.validator.validate(invalid_record)
        self.assertIn("must start with language_code", str(context.exception))

class TestMorphologyValidatorFeatures(unittest.TestCase):
    def setUp(self):
        self.validator = MorphologyValidator()


        self.valid_en_base = {
            "language_code": "en",
            "lemma_id": "en:book:1",
            "sense_id": "en:book:item",
            "lemma": "book",
            "form": "books",
            "features": {"number": "plural"},
            "source_id": "wiktionary-en-book",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }

    def test_invalid_feature_for_language(self):
        invalid_record = self.valid_en_base.copy()
        # en overrides say grammatical_gender is not_applicable
        invalid_record["features"] = {"grammatical_gender": "feminine"}
        with self.assertRaises(ValueError) as context:
            self.validator.validate(invalid_record)
        self.assertIn("explicitly not applicable for language 'en'", str(context.exception))

    def test_invalid_morpheme_kind(self):
        invalid_record = self.valid_en_base.copy()
        # Let's say we have a mock language "testlang" with "clitic": "not_applicable"
        # We can temporarily patch the validator's compatibility map
        self.validator.compatibility["testlang"] = {"clitic": "not_applicable"}

        testlang_record = {
            "language_code": "testlang",
            "lemma_id": "testlang:word:1",
            "sense_id": "testlang:word:item",
            "lemma": "word",
            "form": "words",
            "features": {},
            "morphemes": [{"surface": "s", "kind": "clitic", "position": 1}],
            "source_id": "test",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        with self.assertRaises(ValueError) as context:
            self.validator.validate(testlang_record)
        self.assertIn("Morpheme kind 'clitic' requires feature 'clitic' which is not applicable", str(context.exception))

    def test_invalid_process_broken_plural(self):
        self.validator.compatibility["testlang"] = {"nonconcatenative": "not_applicable", "root_pattern": "not_applicable"}
        testlang_record = {
            "language_code": "testlang",
            "lemma_id": "testlang:word:1",
            "sense_id": "testlang:word:item",
            "lemma": "word",
            "form": "words",
            "features": {},
            "processes": ["broken_plural"],
            "source_id": "test",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        with self.assertRaises(ValueError) as context:
            self.validator.validate(testlang_record)
        self.assertIn("Process 'broken_plural' requires 'nonconcatenative' or 'root_pattern'", str(context.exception))

    def test_invalid_property_root(self):
        self.validator.compatibility["testlang"] = {"root_pattern": "not_applicable", "nonconcatenative": "not_applicable"}
        testlang_record = {
            "language_code": "testlang",
            "lemma_id": "testlang:word:1",
            "sense_id": "testlang:word:item",
            "lemma": "word",
            "form": "words",
            "features": {},
            "root": "w-r-d",
            "source_id": "test",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        with self.assertRaises(ValueError) as context:
            self.validator.validate(testlang_record)
        self.assertIn("Property 'root' requires feature 'root_pattern' which is not applicable", str(context.exception))

if __name__ == '__main__':
    unittest.main()

class TestMorphologyValidatorTypologies(unittest.TestCase):
    def setUp(self):
        self.validator = MorphologyValidator()


    def test_agglutinative_sequence(self):
        # Using TR since agglutinative sequences are typically known for Turkic
        tr_record = {
            "language_code": "tr",
            "lemma_id": "tr:kitap:1",
            "sense_id": "tr:kitap:book",
            "lemma": "kitap",
            "form": "kitaplar",
            "features": {"number": "plural"},
            "processes": ["suffix", "agglutinative_sequences"],
            "morphemes": [
                {"surface": "kitap", "kind": "stem", "position": 0},
                {"surface": "lar", "kind": "suffix", "position": 1}
            ],
            "vowel_harmony_class": "back",
            "source_id": "wiktionary-tr-kitap",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        self.assertTrue(self.validator.validate(tr_record))

    def test_nonconcatenative_root_pattern(self):
        ar_record = {
            "language_code": "ar",
            "lemma_id": "ar:kitab:1",
            "sense_id": "ar:kitab:book",
            "lemma": "كِتَاب",
            "form": "كُتُب",
            "features": {"number": "plural", "grammatical_gender": "masculine"},
            "root": "ك-ت-ب",
            "pattern": "فُعُل",
            "processes": ["broken_plural", "nonconcatenative"],
            "source_id": "wiktionary-ar-kitab",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        self.assertTrue(self.validator.validate(ar_record))

    def test_ambiguous_forms_incomplete_paradigm(self):
        # In English, "read" past and past participle are same
        en_record_past = {
            "language_code": "en",
            "lemma_id": "en:read:1",
            "sense_id": "en:read:book",
            "lemma": "read",
            "form": "read",
            "features": {"tense": "past"},
            "source_id": "wiktionary-en-read",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        en_record_participle = {
            "language_code": "en",
            "lemma_id": "en:read:1",
            "sense_id": "en:read:book",
            "lemma": "read",
            "form": "read",
            "features": {"verb_form": "past_participle"},
            "source_id": "wiktionary-en-read",
            "evidence_version": "2026-10-12",
            "schema_version": "1.0.0"
        }
        self.assertTrue(self.validator.validate(en_record_past))
        self.assertTrue(self.validator.validate(en_record_participle))

if __name__ == '__main__':
    unittest.main()
