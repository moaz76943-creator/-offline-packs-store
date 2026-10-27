import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from standards.directed_pairs.validate import validate, DirectedPairContractError
from standards.directed_pairs.sqlite_v2 import build

class TestDirectedPairs(unittest.TestCase):
    def setUp(self):
        self.valid_document = {
            "schema_version": "1.0.0",
            "document_id": "test.doc.1",
            "pairs": [
                {
                    "translation_id": "test.trans.1",
                    "equivalence": "literal",
                    "source": {
                        "source_id": "test.source.1",
                        "provenance_id": "prov-123",
                        "dataset_version": "v1",
                        "confidence": 0.95
                    },
                    "from_sense": {
                        "sense_id": "test.sense.en.1",
                        "language": "en",
                        "text": "bank",
                        "context": "financial institution"
                    },
                    "to_sense": {
                        "sense_id": "test.sense.fr.1",
                        "language": "fr",
                        "text": "banque"
                    }
                },
                {
                    "translation_id": "test.trans.2",
                    "equivalence": "contextual_alternative",
                    "source": {
                        "source_id": "test.source.2",
                        "provenance_id": "prov-124",
                        "dataset_version": "v1",
                        "confidence": 0.8
                    },
                    "from_sense": {
                        "sense_id": "test.sense.en.2",
                        "language": "en",
                        "text": "bank",
                        "context": "river side"
                    },
                    "to_sense": {
                        "sense_id": "test.sense.fr.2",
                        "language": "fr",
                        "text": "rive"
                    }
                }
            ]
        }
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_document(self):
        # Should not raise
        validate(self.valid_document)

    def test_malformed_direction(self):
        doc = dict(self.valid_document)
        doc['pairs'][0]['to_sense']['language'] = 'en'
        with self.assertRaises(DirectedPairContractError) as context:
            validate(doc)
        self.assertIn("Invalid direction", str(context.exception))

    def test_missing_sense_identity(self):
        doc = dict(self.valid_document)
        del doc['pairs'][0]['from_sense']['sense_id']
        with self.assertRaises(DirectedPairContractError):
            validate(doc)

    def test_duplicate_translation_id(self):
        doc = dict(self.valid_document)
        doc['pairs'].append(doc['pairs'][0])
        with self.assertRaises(DirectedPairContractError) as context:
            validate(doc)
        self.assertIn("Duplicate translation_id", str(context.exception))

    def test_sense_identity_mismatch(self):
        doc = dict(self.valid_document)
        # Add another pair using test.sense.en.1 but with different text
        doc['pairs'].append({
            "translation_id": "test.trans.3",
            "equivalence": "approximate",
            "source": self.valid_document['pairs'][0]['source'],
            "from_sense": {
                "sense_id": "test.sense.en.1",
                "language": "en",
                "text": "different text"
            },
            "to_sense": {
                "sense_id": "test.sense.es.1",
                "language": "es",
                "text": "diferente"
            }
        })
        with self.assertRaises(DirectedPairContractError) as context:
            validate(doc)
        self.assertIn("Sense identity mismatch", str(context.exception))

    def test_sqlite_v2_projection(self):
        output_path = Path(self.temp_dir.name) / "test.db"
        build(self.valid_document, output_path)
        self.assertTrue(output_path.exists())

        conn = sqlite3.connect(output_path)
        try:
            # Check metadata
            version = conn.execute("SELECT value FROM metadata WHERE key='contract_version'").fetchone()[0]
            self.assertEqual(version, "1.0.0")

            # Check senses
            senses_count = conn.execute("SELECT COUNT(*) FROM senses").fetchone()[0]
            self.assertEqual(senses_count, 4)

            # Check directed_pairs
            pairs_count = conn.execute("SELECT COUNT(*) FROM directed_pairs").fetchone()[0]
            self.assertEqual(pairs_count, 2)

            # Check integrity
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(integrity, "ok")
        finally:
            conn.close()

if __name__ == '__main__':
    unittest.main()

    def test_regional_variant_fixture(self):
        doc = dict(self.valid_document)
        doc['pairs'].append({
            "translation_id": "test.trans.regional.1",
            "equivalence": "contextual_alternative",
            "source": self.valid_document['pairs'][0]['source'],
            "from_sense": {
                "sense_id": "test.sense.en-GB.1",
                "language": "en-GB",
                "text": "lorry"
            },
            "to_sense": {
                "sense_id": "test.sense.en-US.1",
                "language": "en-US",
                "text": "truck"
            }
        })
        validate(doc) # should succeed

    def test_reverse_pair_not_assumed(self):
        doc = dict(self.valid_document)
        doc['pairs'].append({
            "translation_id": "test.trans.reverse.1",
            "equivalence": "literal",
            "source": self.valid_document['pairs'][0]['source'],
            "from_sense": {
                "sense_id": "test.sense.fr.1",
                "language": "fr",
                "text": "banque"
            },
            "to_sense": {
                "sense_id": "test.sense.en.1",
                "language": "en",
                "text": "bank",
                "context": "financial institution"
            }
        })
        validate(doc) # Reverse translations need explicit definitions; validation must succeed if specified properly.
