import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tools.open_index.audit import IndexBlocked, inspect

DDL='''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE lexicon(id TEXT PRIMARY KEY, surface TEXT NOT NULL, language_code TEXT NOT NULL);
CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED,tokenize='unicode61 remove_diacritics 0');
'''

class ReadOnlyIndexTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.path=Path(self.t.name)/'source.sqlite'
        with sqlite3.connect(self.path) as db:
            db.executescript(DDL)
            for key,value in [('contract_version','1.0.0'),('mapping_version','2.0.0'),('language_code','ar')]:
                db.execute('INSERT INTO metadata VALUES(?,?)',(key,value))
            db.execute('INSERT INTO lexicon VALUES(?,?,?)',('lex.ar.001','كَتَبَ','ar'))
            rowid=db.execute('SELECT rowid FROM lexicon').fetchone()[0]
            db.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES(?,?,?,?,?)',
                       (rowid,'كَتَبَ','كَتَبَ','to write','ar'))
            db.execute('PRAGMA user_version=2')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def audit(self, **kw):
        return inspect(self.path,kw.get('language','ar'),kw.get('sha',self.sha),canonical_ddl=DDL)

    def test_real_fts5_exact_match_without_mutating_bytes(self):
        result=self.audit()
        self.assertEqual(result['fts5_exact_matches'],1)
        self.assertEqual(self.sha,hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertFalse(result['publication_approved'])
        self.assertFalse(result['optional_diacritic_matching_proven'])

    def test_wrong_language_rejected(self):
        with self.assertRaisesRegex(IndexBlocked,'language mismatch'):
            self.audit(language='de')

    def test_invalid_hash_rejected(self):
        with self.assertRaisesRegex(IndexBlocked,'SHA-256 mismatch'):
            self.audit(sha='a'*64)

    def test_repeated_execution_deterministic(self):
        self.assertEqual(self.audit(),self.audit())

    def test_altered_fts_surface_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE lexicon_fts SET surface='كتب' WHERE rowid=1")
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(IndexBlocked):
            self.audit()

    def test_wrong_sqlite_version_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=1')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(IndexBlocked,'user_version'):
            self.audit()

    def test_non_database_input_rejected(self):
        self.path.write_bytes(b'not a database')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(IndexBlocked):
            self.audit()

if __name__=='__main__':
    unittest.main()
