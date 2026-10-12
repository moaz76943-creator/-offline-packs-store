import json
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parent


class SchemaFixtures(unittest.TestCase):
    def test_evidence_identifiers_and_url_integrity(self):
        sources = json.loads((BASE / 'sources.json').read_text(encoding='utf-8'))['sources']
        languages = set()
        count = 0
        for line in (BASE / 'attested_forms.jsonl').read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            count += 1
            languages.add(record['language_code'])
            self.assertEqual(record['language_code'], record['lemma_id'].split(':', 1)[0])
            self.assertIn(record['source_id'], sources)
            self.assertTrue(sources[record['source_id']]['url'].startswith('https://'))
            self.assertTrue(record['sense_id'])
            self.assertTrue(record['evidence_version'])
            self.assertFalse(record['form'].strip() == '')
        self.assertEqual({'ar','de','en','es','fr'}, languages)
        self.assertGreaterEqual(count, 19)

    def test_capabilities_and_unknown_status_are_explicit(self):
        rules = json.loads((BASE / 'feature_overrides.json').read_text(encoding='utf-8'))
        self.assertEqual(25, len(rules['features']))
        self.assertIn('unknown', rules['status_values'])
        self.assertIn('noun_classes', rules['features'])
        self.assertIn('grammatical_gender', rules['features'])
        self.assertNotEqual(rules['overrides']['en']['grammatical_gender'], 'supported')
        self.assertNotIn('bantu_noun_class', rules['overrides']['de'])


if __name__ == '__main__':
    unittest.main()
