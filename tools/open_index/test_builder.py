import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.open_index.builder import build_index, IndexBuilderError, get_tokenizer_for_language


def setup_dummy_db(db_path, language_code, words):
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE lexicon(id TEXT, surface TEXT, lemma TEXT, language_code TEXT)')
        db.execute('CREATE TABLE senses(sense_id TEXT, lexeme_id TEXT, definition TEXT)')
        db.execute('CREATE TABLE translations(translation_id TEXT, from_sense_id TEXT, text TEXT)')
        db.execute('CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, lemma, gloss, language_code UNINDEXED, tokenize="unicode61 remove_diacritics 0")')

        for i, word in enumerate(words):
            lex_id = f"lex{i}"
            db.execute('INSERT INTO lexicon(rowid, id, surface, lemma, language_code) VALUES(?, ?, ?, ?, ?)',
                       (i+1, lex_id, word, word, language_code))
            db.execute('INSERT INTO senses(sense_id, lexeme_id, definition) VALUES(?, ?, ?)',
                       (f"sense{i}", lex_id, "def"))
            db.execute('INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES(?, ?, ?, ?, ?)',
                       (i+1, word, word, "def", language_code))

        db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")


class TestIndexBuilder(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / 'test.sqlite'

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_default_tokenizer(self):
        setup_dummy_db(self.db_path, 'eng', ['hello', 'world'])
        build_index(self.db_path)

        with sqlite3.connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM lexicon_fts WHERE lexicon_fts != 'integrity-check'").fetchone()[0]
            self.assertEqual(count, 2)
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lexicon_fts'").fetchone()
            self.assertIn('unicode61', row[0] if row else "")

    def test_cjk_tokenizer(self):
        setup_dummy_db(self.db_path, 'zho', ['你好世界', '世界和平'])
        build_index(self.db_path)

        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lexicon_fts'").fetchone()[0]
            self.assertIn("tokenize='trigram'", row)

    def test_arabic_tokenizer(self):
        setup_dummy_db(self.db_path, 'ara', ['مرحبا', 'عالم'])
        build_index(self.db_path)

        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lexicon_fts'").fetchone()[0]
            self.assertIn("tokenize='unicode61 remove_diacritics 2'", row)

    def test_accented_text(self):
        setup_dummy_db(self.db_path, 'fra', ['café', 'naïve'])
        build_index(self.db_path)

        with sqlite3.connect(self.db_path) as db:
            res = db.execute("SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH '\"café\"' LIMIT 1").fetchone()
            self.assertIsNotNone(res)

    def test_rtl_tokens(self):
        setup_dummy_db(self.db_path, 'heb', ['שלום', 'עולם'])
        build_index(self.db_path)

        with sqlite3.connect(self.db_path) as db:
            res = db.execute("SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH '\"שלום\"' LIMIT 1").fetchone()
            self.assertIsNotNone(res)

    def test_invalid_sqlite(self):
        self.db_path.write_text("not a sqlite database")
        with self.assertRaises(IndexBuilderError):
            build_index(self.db_path)

    @patch('tools.open_index.builder.is_tokenizer_supported')
    def test_unsupported_tokenizer(self, mock_is_supported):
        mock_is_supported.return_value = False
        setup_dummy_db(self.db_path, 'zho', ['你好世界'])
        with self.assertRaisesRegex(IndexBuilderError, 'Unsupported tokenizer'):
            build_index(self.db_path)

    @patch('os.replace')
    def test_interrupted_index_generation(self, mock_replace):
        mock_replace.side_effect = Exception("Interrupted!")
        setup_dummy_db(self.db_path, 'eng', ['test'])

        with self.assertRaises(Exception):
            build_index(self.db_path)

        staged_path = self.db_path.with_suffix('.sqlite.staged')
        self.assertFalse(staged_path.exists())
        self.assertTrue(self.db_path.exists())


if __name__ == '__main__':
    unittest.main()
