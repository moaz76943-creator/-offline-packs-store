import unittest
import sqlite3
import tempfile
from pathlib import Path
from tools.open_index.builder import build_index

class TestOpenIndexEdgeCases(unittest.TestCase):
    def test_interrupted_index_generation(self):
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
            conn.execute("INSERT INTO lexicon (id, surface, part_of_speech, pos, direction, language_code, script, sort_key, fields_json, source_json) VALUES ('1', 'hello', 'n', 'n', 'ltr', 'eng', 'latn', 'hello', '{}', '{}')")
            conn.execute("INSERT INTO lexicon_fts (rowid, surface, lemma, gloss, language_code) VALUES (1, 'hello', 'hello', 'greeting', 'eng')")
            conn.commit()
            conn.close()

            # we want to simulate interrupted build, maybe by causing an error in the middle
            import tools.open_index.builder as builder
            original = builder.verify_tokenizer
            builder.verify_tokenizer = lambda c, t: 1/0

            try:
                with self.assertRaises(ZeroDivisionError):
                    build_index(db_path)
            finally:
                builder.verify_tokenizer = original

            # verify original DB is intact
            self.assertTrue(db_path.exists())
            conn = sqlite3.connect(db_path)
            res = conn.execute("SELECT surface FROM lexicon_fts").fetchone()
            self.assertEqual(res[0], 'hello')
            conn.close()

            # verify staged db is deleted
            self.assertFalse(db_path.with_suffix('.staged.sqlite').exists())

    def test_invalid_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'invalid.sqlite'
            db_path.write_bytes(b'not a sqlite database')

            # it might raise sqlite3.DatabaseError or our own ValueError
            with self.assertRaises(Exception) as cm:
                build_index(db_path)

            # Ensure it's one of the expected errors
            self.assertTrue(isinstance(cm.exception, (sqlite3.DatabaseError, ValueError)))

            self.assertFalse(db_path.with_suffix('.staged.sqlite').exists())

if __name__ == '__main__':
    unittest.main()
