import json
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from standards.directed_pairs.validate import validate, verify_compatible, DirectedTranslationError

class TestDirectedPairs(unittest.TestCase):
    def setUp(self):
        self.valid_data = {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "es",
            "translations": [
                {
                    "source_sense_id": "sense.en.hello",
                    "target_sense_id": "sense.es.hola",
                    "translation_text": "hola",
                    "equivalence": "literal",
                    "context": "greeting",
                    "provenance": {
                        "provenance_id": "prov.123",
                        "source_version": "1.0",
                        "confidence": 1.0
                    }
                }
            ]
        }

    def test_valid_document(self):
        result = validate(self.valid_data)
        self.assertEqual(result, self.valid_data)

    def test_missing_required_fields(self):
        invalid_data = self.valid_data.copy()
        del invalid_data["source_language"]
        with self.assertRaises(DirectedTranslationError):
            validate(invalid_data)

    def test_same_sense_id(self):
        invalid_data = self.valid_data.copy()
        invalid_data["translations"][0]["target_sense_id"] = invalid_data["translations"][0]["source_sense_id"]
        with self.assertRaises(DirectedTranslationError):
            validate(invalid_data)

    def test_verify_compatible_add_ok(self):
        updated = json.loads(json.dumps(self.valid_data))
        updated["translations"].append({
            "source_sense_id": "sense.en.world",
            "target_sense_id": "sense.es.mundo",
            "translation_text": "mundo",
            "equivalence": "literal",
            "provenance": {
                "provenance_id": "prov.123",
                "source_version": "1.0",
                "confidence": 0.9
            }
        })
        self.assertTrue(verify_compatible(self.valid_data, updated))

    def test_verify_compatible_remove_fails(self):
        updated = json.loads(json.dumps(self.valid_data))
        updated["translations"] = []
        with self.assertRaises(DirectedTranslationError):
            verify_compatible(self.valid_data, updated)

    def test_fixtures_polysemous_homographs(self):
        data = {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "fr",
            "translations": [
                {
                    "source_sense_id": "sense.en.bank.1",
                    "target_sense_id": "sense.fr.banque.1",
                    "translation_text": "banque",
                    "equivalence": "literal",
                    "context": "financial institution",
                    "provenance": {
                        "provenance_id": "prov.wiktionary",
                        "source_version": "2023",
                        "confidence": 0.95
                    }
                },
                {
                    "source_sense_id": "sense.en.bank.2",
                    "target_sense_id": "sense.fr.rive.1",
                    "translation_text": "rive",
                    "equivalence": "literal",
                    "context": "side of river",
                    "provenance": {
                        "provenance_id": "prov.wiktionary",
                        "source_version": "2023",
                        "confidence": 0.95
                    }
                }
            ]
        }
        self.assertEqual(validate(data), data)

    def test_fixtures_reverse_pairs(self):
        data = {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "es",
            "translations": [
                {
                    "source_sense_id": "sense.en.water",
                    "target_sense_id": "sense.es.agua",
                    "translation_text": "agua",
                    "equivalence": "literal",
                    "provenance": {
                        "provenance_id": "prov.1",
                        "source_version": "1.0",
                        "confidence": 1.0
                    }
                }
            ]
        }
        reverse_data = {
            "schema_version": "1.0.0",
            "source_language": "es",
            "target_language": "en",
            "translations": [
                {
                    "source_sense_id": "sense.es.agua",
                    "target_sense_id": "sense.en.water",
                    "translation_text": "water",
                    "equivalence": "literal",
                    "provenance": {
                        "provenance_id": "prov.1",
                        "source_version": "1.0",
                        "confidence": 1.0
                    }
                }
            ]
        }
        self.assertEqual(validate(data), data)
        self.assertEqual(validate(reverse_data), reverse_data)

    def test_fixtures_missing_context(self):
        data = {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "es",
            "translations": [
                {
                    "source_sense_id": "sense.en.cat",
                    "target_sense_id": "sense.es.gato",
                    "translation_text": "gato",
                    "equivalence": "literal",
                    # no context
                    "provenance": {
                        "provenance_id": "prov.1",
                        "source_version": "1.0",
                        "confidence": 1.0
                    }
                }
            ]
        }
        self.assertEqual(validate(data), data)

    def test_fixtures_regional_variants(self):
        data = {
            "schema_version": "1.0.0",
            "source_language": "en-US",
            "target_language": "en-GB",
            "translations": [
                {
                    "source_sense_id": "sense.en-US.truck",
                    "target_sense_id": "sense.en-GB.lorry",
                    "translation_text": "lorry",
                    "equivalence": "literal",
                    "provenance": {
                        "provenance_id": "prov.variant",
                        "source_version": "1.0",
                        "confidence": 1.0
                    }
                }
            ]
        }
        self.assertEqual(validate(data), data)
