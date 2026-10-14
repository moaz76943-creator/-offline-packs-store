"""Small synthetic FTS alignment regressions; no production evidence."""
import hashlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.gha_factory.search_qa import audit


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA user_version=2;
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO metadata VALUES('mapping_version','2.0.0');
                INSERT INTO metadata VALUES('contract_version','1.0.0');
                CREATE TABLE lexicon(id TEXT PRIMARY KEY,surface TEXT,language_code TEXT);
                CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                    surface,lemma,gloss,language_code UNINDEXED,
                    tokenize='unicode61 remove_diacritics 0');
            """)
            for i in range(1, audit.MAX_SAMPLES + 2):
                word = 'Wort' + str(i)
                db.execute('INSERT INTO lexicon VALUES(?,?,?)', (f'lex.{i:03}', word, 'de'))
                db.execute('INSERT INTO lexicon_fts(rowid,surface,language_code) VALUES(?,?,?)',
                           (i, word, 'de'))
        self.last = audit.MAX_SAMPLES + 1

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def reject(self, sql, params, reason):
        with sqlite3.connect(self.path) as db:
            db.execute(sql, params)
        before = self.digest()
        with self.assertRaisesRegex(audit.AuditError, reason):
            audit.check_sqlite(self.path, 'de')
        self.assertEqual(before, self.digest())

    def test_equal_counts_missing_and_orphan_outside_sample_rejected(self):
        self.reject('UPDATE lexicon_fts SET rowid=999 WHERE rowid=?',
                    (self.last,), 'FTS5.*alignment')

    def test_unsampled_surface_mismatch_rejected(self):
        self.reject("UPDATE lexicon_fts SET surface='forged' WHERE rowid=?",
                    (self.last,), 'FTS5.*mismatch')

    def test_unsampled_language_mismatch_rejected(self):
        self.reject("UPDATE lexicon_fts SET language_code='ar' WHERE rowid=?",
                    (self.last,), 'FTS5.*mismatch')

    def test_unsampled_null_surface_rejected(self):
        self.reject('UPDATE lexicon_fts SET surface=NULL WHERE rowid=?',
                    (self.last,), 'FTS5.*mismatch')

    def test_physical_size_limit_rejects_before_connect(self):
        with patch.object(audit, 'MAX_SQLITE_BYTES', self.path.stat().st_size - 1):
            with patch.object(audit.sqlite3, 'connect') as connect:
                with self.assertRaisesRegex(audit.AuditError, 'oversized'):
                    audit.check_sqlite(self.path, 'de')
                connect.assert_not_called()

    def test_expired_sql_deadline_rejects_without_mutation(self):
        with sqlite3.connect(self.path) as db:
            for i in range(100, 600):
                db.execute('INSERT INTO lexicon VALUES(?,?,?)', (f'lex.{i}', 'Wort', 'de'))
                rowid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
                db.execute('INSERT INTO lexicon_fts(rowid,surface,language_code) VALUES(?,?,?)',
                           (rowid, 'Wort', 'de'))
        before = self.digest()
        with patch.object(audit, 'SQL_SECONDS', -1):
            with self.assertRaisesRegex(audit.AuditError, 'interrupted'):
                audit.check_sqlite(self.path, 'de')
        self.assertEqual(before, self.digest())

    def test_valid_full_alignment_remains_read_only(self):
        before = self.digest()
        result = audit.check_sqlite(self.path, 'de')
        self.assertEqual(result['lexical_count'], self.last)
        self.assertEqual(result['sampled'], audit.MAX_SAMPLES)
        self.assertEqual(before, self.digest())


if __name__ == '__main__':
    unittest.main()
