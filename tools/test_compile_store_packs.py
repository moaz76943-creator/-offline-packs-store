import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.compile_store_packs import input_rows

class TestInputRows(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_json_valid(self):
        src = self.temp_path / 'en.json'
        data = {
            'languageCode': 'en',
            'lexicon': [{'id': '1', 'surface': 'cat', 'part_of_speech': 'noun', 'fields_json': '{}'}],
            'concepts': [{'concept_id': 'c1', 'lemma': 'cat', 'part_of_speech': 'noun', 'cefr': 'a1'}]
        }
        src.write_text(json.dumps(data))
        root, lexicon, concepts = input_rows(src, 'en')
        self.assertEqual(root, data)
        self.assertEqual(lexicon, data['lexicon'])
        self.assertEqual(concepts, data['concepts'])

    def test_json_invalid_language_code(self):
        src = self.temp_path / 'en.json'
        src.write_text(json.dumps({'languageCode': 'fr'}))
        with self.assertRaisesRegex(ValueError, 'invalid languageCode'):
            input_rows(src, 'en')

    def test_json_invalid_arrays(self):
        src = self.temp_path / 'en.json'
        src.write_text(json.dumps({'languageCode': 'en', 'lexicon': 'not_an_array'}))
        with self.assertRaisesRegex(ValueError, 'lexicon/concepts must be arrays'):
            input_rows(src, 'en')

    def test_sqlite_valid(self):
        src = self.temp_path / 'en.sqlite'
        with sqlite3.connect(src) as conn:
            conn.execute('CREATE TABLE lexicon (id TEXT, surface TEXT, part_of_speech TEXT, fields_json TEXT, direction TEXT, cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT)')
            conn.execute("INSERT INTO lexicon VALUES ('1', 'cat', 'noun', '{}', 'ltr', 'a1', 1, 'cat')")
            conn.execute('CREATE TABLE concepts (concept_id TEXT, lemma TEXT, part_of_speech TEXT, cefr TEXT)')
            conn.execute("INSERT INTO concepts VALUES ('c1', 'cat', 'noun', 'a1')")

        root, lexicon, concepts = input_rows(src, 'en')
        self.assertEqual(root, {})
        self.assertEqual(len(lexicon), 1)
        self.assertEqual(lexicon[0]['id'], '1')
        self.assertEqual(len(concepts), 1)
        self.assertEqual(concepts[0]['concept_id'], 'c1')

    def test_sqlite_no_concepts(self):
        src = self.temp_path / 'en.sqlite'
        with sqlite3.connect(src) as conn:
            conn.execute('CREATE TABLE lexicon (id TEXT, surface TEXT, part_of_speech TEXT, fields_json TEXT)')
            conn.execute("INSERT INTO lexicon VALUES ('1', 'cat', 'noun', '{}')")

        root, lexicon, concepts = input_rows(src, 'en')
        self.assertEqual(root, {})
        self.assertEqual(len(lexicon), 1)
        self.assertEqual(len(concepts), 0)

    def test_sqlite_missing_columns(self):
        src = self.temp_path / 'en.sqlite'
        with sqlite3.connect(src) as conn:
            conn.execute('CREATE TABLE lexicon (id TEXT, surface TEXT, part_of_speech TEXT)') # missing fields_json
        with self.assertRaisesRegex(ValueError, 'missing lexicon columns'):
            input_rows(src, 'en')

    def test_sqlite_invalid_concepts(self):
        src = self.temp_path / 'en.sqlite'
        with sqlite3.connect(src) as conn:
            conn.execute('CREATE TABLE lexicon (id TEXT, surface TEXT, part_of_speech TEXT, fields_json TEXT)')
            conn.execute('CREATE TABLE concepts (concept_id TEXT)') # missing lemma, part_of_speech, cefr
        with self.assertRaisesRegex(ValueError, 'concepts schema mismatch'):
            input_rows(src, 'en')

    def test_unsupported_extension(self):
        src = self.temp_path / 'en.txt'
        with self.assertRaisesRegex(ValueError, 'unsupported source'):
            input_rows(src, 'en')

if __name__ == '__main__':
    unittest.main()
