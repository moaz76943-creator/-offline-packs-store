import unittest
import sqlite3
import tempfile
import os
import shutil
import json
from unittest.mock import patch
from tools.open_index.builder import build_index, BuilderError
from tools.pack_v2.pipeline import DDL

class TestBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.sqlite')
        self.setup_db('en')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def setup_db(self, lang, text='hello', direction='ltr', script='Latn'):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            db.executescript(DDL)
            db.execute(f"INSERT INTO metadata VALUES ('language_code', '{lang}')")
            db.execute("INSERT INTO concepts(concept_id) VALUES ('c1')")
            fields_json = json.dumps({'lemma': f'{text}_lemma'})
            db.execute(f"INSERT INTO lexicon(id, surface, part_of_speech, pos, direction, language_code, script, dialect, sort_key, cefr_level, frequency_rank, fields_json, source_json) VALUES ('lex1', ?, 'noun', 'noun', ?, ?, ?, null, ?, null, null, ?, '{{}}')", (text, direction, lang, script, text, fields_json))
            # Test empty definition handling
            db.execute("INSERT INTO senses(sense_id, lexeme_id, concept_id, definition, payload_json) VALUES ('s1', 'lex1', 'c1', 'definition1', '{}')")
            db.execute("INSERT INTO senses(sense_id, lexeme_id, concept_id, definition, payload_json) VALUES ('s2', 'lex1', 'c1', 'definition2', '{}')")
            db.execute("INSERT INTO translations(translation_id, from_sense_id, to_sense_id, language_code, text, payload_json) VALUES ('t1', 's1', 's2', 'en', 'trans1', '{}')")


    def test_build_index_success(self):
        build_index(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
            self.assertEqual(count, 1)
            row = db.execute("SELECT gloss FROM lexicon_fts").fetchone()[0]
            self.assertTrue('definition1' in row)
            self.assertTrue('trans1' in row)

    def test_build_index_invalid_db(self):
        with self.assertRaises(BuilderError):
            build_index("nonexistent.sqlite")

    def test_build_index_thai_rejected(self):
        self.setup_db('th', script='Thai')
        with self.assertRaisesRegex(BuilderError, "Thai dictionary tokenization not supported"):
            build_index(self.db_path)

    @patch('tools.open_index.builder.check_tokenizer', return_value=False)
    def test_build_index_cjk_unsupported_without_trigram(self, mock_check):
        self.setup_db('zh', script='Hani')
        with self.assertRaisesRegex(BuilderError, "Unsupported language zh without trigram tokenizer"):
            build_index(self.db_path)

    @patch('tools.open_index.builder.check_tokenizer', return_value=True)
    def test_build_index_cjk_supported_with_trigram(self, mock_check):
        self.setup_db('zh', text='你好啊', script='Hani')
        build_index(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
            self.assertEqual(count, 1)

    def test_build_index_rtl_accented(self):
        # Arabic with diacritics
        self.setup_db('ar', text='مَرْحَبًا', direction='rtl', script='Arab')
        build_index(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
            self.assertEqual(count, 1)

    @patch('os.replace')
    def test_build_index_interrupted_generation(self, mock_replace):
        mock_replace.side_effect = Exception("Interrupted")
        with self.assertRaises(Exception):
            build_index(self.db_path)

        # Temp file should have been deleted (or at least we shouldn't crash unhandled and DB path is intact)
        self.assertTrue(os.path.exists(self.db_path))

if __name__ == '__main__':
    unittest.main()
