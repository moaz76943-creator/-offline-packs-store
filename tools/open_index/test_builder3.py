import unittest
import sqlite3
import tempfile
from pathlib import Path
from tools.open_index.builder import build_index

class TestOpenIndexAccentsRTL(unittest.TestCase):
    def test_accented_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
            CREATE TABLE lexicon(
                id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                pos TEXT NOT NULL, direction TEXT NOT NULL, language_code TEXT NOT NULL,
                script TEXT NOT NULL, dialect TEXT, sort_key TEXT NOT NULL,
                cefr_level TEXT, frequency_rank INTEGER, fields_json TEXT NOT NULL,
                source_json TEXT NOT NULL
            )
            ''')
            conn.execute('''
            CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                surface, lemma, gloss, language_code UNINDEXED,
                tokenize='unicode61 remove_diacritics 0'
            )
            ''')
            conn.execute("INSERT INTO lexicon (id, surface, part_of_speech, pos, direction, language_code, script, sort_key, fields_json, source_json) VALUES ('1', 'café', 'n', 'n', 'ltr', 'fra', 'latn', 'cafe', '{}', '{}')")
            conn.execute("INSERT INTO lexicon_fts (rowid, surface, lemma, gloss, language_code) VALUES (1, 'café', 'café', 'coffee', 'fra')")
            conn.commit()
            conn.close()

            build_index(db_path)

            conn = sqlite3.connect(db_path)
            match = conn.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH 'café'").fetchall()
            self.assertEqual(len(match), 1)
            conn.close()

    def test_rtl_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
            CREATE TABLE lexicon(
                id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                pos TEXT NOT NULL, direction TEXT NOT NULL, language_code TEXT NOT NULL,
                script TEXT NOT NULL, dialect TEXT, sort_key TEXT NOT NULL,
                cefr_level TEXT, frequency_rank INTEGER, fields_json TEXT NOT NULL,
                source_json TEXT NOT NULL
            )
            ''')
            conn.execute('''
            CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                surface, lemma, gloss, language_code UNINDEXED,
                tokenize='unicode61 remove_diacritics 0'
            )
            ''')
            # 'سلام'
            conn.execute("INSERT INTO lexicon (id, surface, part_of_speech, pos, direction, language_code, script, sort_key, fields_json, source_json) VALUES ('1', 'سلام', 'n', 'n', 'rtl', 'pes', 'arab', 'salam', '{}', '{}')")
            conn.execute("INSERT INTO lexicon_fts (rowid, surface, lemma, gloss, language_code) VALUES (1, 'سلام', 'سلام', 'hello', 'pes')")
            conn.commit()
            conn.close()

            build_index(db_path)

            conn = sqlite3.connect(db_path)
            match = conn.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH 'سلام'").fetchall()
            self.assertEqual(len(match), 1)
            conn.close()

if __name__ == '__main__':
    unittest.main()
