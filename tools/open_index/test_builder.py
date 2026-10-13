import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from tools.open_index.builder import build_index, normalize_text

class TestOpenIndexBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_pack(self, records):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
            db.execute("CREATE TABLE lexicon(id TEXT PRIMARY KEY, surface TEXT NOT NULL, lemma TEXT, language_code TEXT NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED, tokenize='unicode61')")
            for r in records:
                cursor = db.execute("INSERT INTO lexicon(id, surface, lemma, language_code) VALUES (?, ?, ?, ?)", r)
                # insert into fts
                db.execute("INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES (?, ?, ?, ?, ?)",
                           (cursor.lastrowid, r[1], r[2], r[1], r[3]))
            db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
            db.commit()

    def test_normalize_text(self):
        self.assertEqual(normalize_text("كِتاب"), "كتاب")
        self.assertEqual(normalize_text(None), None)
        self.assertEqual(normalize_text("é"), "e")

    def test_accented_text(self):
        self._create_mock_pack([('1', 'café', 'café', 'fr')])
        build_index(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as db:
            # Normalized form will be inserted, 'café' becomes 'cafe'.
            # Searching for 'cafe' should match.
            res = db.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH 'cafe'").fetchall()
            self.assertEqual(len(res), 1)

    def test_rtl_arabic_tokens(self):
        self._create_mock_pack([('1', 'كِتاب', 'كِتاب', 'ar')])
        build_index(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as db:
            # We used unicode61 remove_diacritics 2.
            # Searching for 'كتاب' matches 'كِتاب'.
            res = db.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH 'كتاب'").fetchall()
            self.assertEqual(len(res), 1)

    def test_cjk_fixtures(self):
        self._create_mock_pack([('1', '日本語です', '日本語', 'ja')])
        build_index(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as db:
            # We used trigram tokenizer for CJK.
            res = db.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH '\"日本語\"'").fetchall()
            self.assertEqual(len(res), 1)

    def test_invalid_sqlite(self):
        self.db_path.write_bytes(b'not a sqlite db')
        with self.assertRaises(ValueError):
            build_index(self.db_path)

    def test_missing_tables(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("CREATE TABLE foo(id TEXT)")
        with self.assertRaises(ValueError):
            build_index(self.db_path)

    def test_interrupted_index_generation_preserves_original(self):
        self._create_mock_pack([('1', 'book', 'book', 'ja')])
        original_mtime = self.db_path.stat().st_mtime

        # Monkeypatch check_tokenizer to simulate a crash during index generation
        import tools.open_index.builder
        old_has_tokenizer = tools.open_index.builder.has_tokenizer
        def crashing_has_tokenizer(tok):
            raise RuntimeError("simulated crash")
        tools.open_index.builder.has_tokenizer = crashing_has_tokenizer

        try:
            with self.assertRaises(RuntimeError):
                build_index(self.db_path)
            # The original DB should remain unmodified (not completely verified by mtime,
            # but we verify it can still be opened and has the original data).
            with closing(sqlite3.connect(self.db_path)) as db:
                self.assertEqual(db.execute("SELECT surface FROM lexicon WHERE id='1'").fetchone()[0], 'book')
        finally:
            tools.open_index.builder.has_tokenizer = old_has_tokenizer

if __name__ == '__main__':
    unittest.main()
