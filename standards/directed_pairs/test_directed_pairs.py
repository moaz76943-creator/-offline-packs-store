import json
import sqlite3
import unittest
from pathlib import Path

try:
    from .validate import DirectedPairContractError, validate, verify_compatible
except ImportError:
    from validate import DirectedPairContractError, validate, verify_compatible

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


class DirectedPairsSchemaTest(unittest.TestCase):
    def setUp(self):
        self.positive_data = fixture('positive')
        self.negative_missing_sense = fixture('negative')
        self.negative_same_sense = fixture('negative_same_sense')
        self.negative_duplicate = fixture('negative_duplicate')

    def test_positive_fixture_validates(self):
        self.assertIs(validate(self.positive_data), self.positive_data)
        self.assertEqual(self.positive_data['source_language'], 'en')
        self.assertEqual(self.positive_data['target_language'], 'es')
        self.assertEqual(len(self.positive_data['translations']), 7)

    def test_negative_missing_to_sense(self):
        with self.assertRaises(DirectedPairContractError) as context:
            validate(self.negative_missing_sense)
        self.assertIn("JSON Schema violation", str(context.exception))
        self.assertIn("'to_sense_id' is a required property", str(context.exception))

    def test_negative_same_sense_id(self):
        with self.assertRaises(DirectedPairContractError) as context:
            validate(self.negative_same_sense)
        self.assertIn("translation cannot be to the same sense id", str(context.exception))

    def test_negative_duplicate_id(self):
        with self.assertRaises(DirectedPairContractError) as context:
            validate(self.negative_duplicate)
        self.assertIn("duplicate stable ID", str(context.exception))

    def test_verify_compatible_success(self):
        updated = fixture('positive')
        # Add a new translation which should be backward compatible
        updated['translations'].append({
            "translation_id": "tr.en-es.new",
            "from_language": "en",
            "to_language": "es",
            "from_sense_id": "sense.en.new",
            "to_sense_id": "sense.es.nuevo",
            "translation_text": "nuevo",
            "equivalence": "exact",
            "source": self.positive_data['translations'][0]['source']
        })
        self.assertTrue(verify_compatible(self.positive_data, updated))

    def test_verify_compatible_fails_on_removal(self):
        updated = fixture('positive')
        updated['translations'].pop()
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(self.positive_data, updated)
        self.assertIn("breaking removal", str(context.exception))

    def test_verify_compatible_fails_on_reassignment(self):
        updated = fixture('positive')
        updated['translations'][0]['to_sense_id'] = "sense.es.different"
        with self.assertRaises(DirectedPairContractError) as context:
            verify_compatible(self.positive_data, updated)
        self.assertIn("stable identity reassignment", str(context.exception))


    def test_reverse_direction_requires_separate_document(self):
        reverse = fixture('reverse')
        self.assertIs(validate(reverse), reverse)
        self.assertEqual((reverse['source_language'], reverse['target_language']), ('es','en'))
        wrong = fixture('positive')
        wrong['translations'].append(reverse['translations'][0])
        with self.assertRaisesRegex(DirectedPairContractError, 'record direction'):
            validate(wrong)

    def test_sense_ownership_not_inferred_from_id_spellings(self):
        doc = fixture('positive')
        sense_languages = {'sense.en.bank.financial': 'es', 'sense.es.banco.financial': 'en'}
        with self.assertRaisesRegex(DirectedPairContractError, 'sense-language ownership'):
            validate(doc, sense_languages=sense_languages)

    def test_unknown_language_rejected_against_registry(self):
        doc = fixture('positive')
        doc['target_language'] = 'zz'
        with self.assertRaisesRegex(DirectedPairContractError, 'unknown or identical'):
            validate(doc)

    def test_publication_requires_independent_evidence_indexes(self):
        with self.assertRaisesRegex(DirectedPairContractError, 'independently verified'):
            validate(fixture('positive'), publication=True)

    def test_publication_does_not_trust_self_asserted_source(self):
        doc = fixture('positive')
        for rec in doc['translations']:
            rec['source']['publication_approved'] = True
            rec['source']['fixture_only'] = False
            rec['source']['artifact_sha256'] = 'a' * 64
        senses = {sense: lang for t in doc['translations'] for sense, lang
                  in ((t['from_sense_id'], 'en'), (t['to_sense_id'], 'es'))}
        with self.assertRaisesRegex(DirectedPairContractError, 'source rights admission|unapproved example'):
            validate(doc, publication=True, sense_languages=senses, approved_sources={})

    def test_pair_reassignment_breaks_compatibility(self):
        doc = fixture('positive')
        changed = fixture('positive')
        changed['source_language'], changed['target_language'] = 'es', 'en'
        with self.assertRaises(DirectedPairContractError):
            verify_compatible(doc, changed)

    def test_record_direction_required_by_schema(self):
        doc = fixture('positive')
        del doc['translations'][0]['from_language']
        with self.assertRaisesRegex(DirectedPairContractError, 'JSON Schema violation'):
            validate(doc)

    def test_canonical_sqlite_v2_import(self):
        """
        Verify that data shapes align with standard translation table schemas.
        Create a mock SQLite v2 database layout matching the standard translations table
        and attempt to insert the positive fixture data into it, ensuring no errors occur.
        """
        con = sqlite3.connect(':memory:')
        con.execute('''
            CREATE TABLE translations (
                translation_id TEXT PRIMARY KEY,
                from_sense_id TEXT NOT NULL,
                to_sense_id TEXT NOT NULL,
                language TEXT NOT NULL,
                text TEXT NOT NULL,
                equivalence TEXT NOT NULL,
                context TEXT,
                source_json TEXT NOT NULL
            )
        ''')

        target_lang = self.positive_data['target_language']

        for record in self.positive_data['translations']:
            con.execute('''
                INSERT INTO translations (
                    translation_id, from_sense_id, to_sense_id, language, text, equivalence, context, source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record['translation_id'],
                record['from_sense_id'],
                record['to_sense_id'],
                target_lang,
                record['translation_text'],
                record['equivalence'],
                record.get('context'),
                json.dumps(record['source'])
            ))

        count = con.execute('SELECT COUNT(*) FROM translations').fetchone()[0]
        self.assertEqual(count, len(self.positive_data['translations']))
        con.close()

if __name__ == '__main__':
    unittest.main()
