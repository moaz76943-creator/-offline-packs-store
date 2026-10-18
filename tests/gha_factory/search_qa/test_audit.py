"""Synthetic fixture-only Unicode, FTS5 and pack boundary regression tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tools.gha_factory.search_qa import audit


class SearchAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'fixture.sqlite'

    def make_db(self, language='de', surfaces=('Straße', 'Äpfel')):
        with sqlite3.connect(self.db) as con:
            con.executescript("""
              PRAGMA user_version=2;
              CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              INSERT INTO metadata VALUES ('mapping_version','2.0.0');
              INSERT INTO metadata VALUES ('contract_version','1.0.0');
              CREATE TABLE lexicon(id TEXT PRIMARY KEY, surface TEXT,
                language_code TEXT NOT NULL);
              CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                surface,lemma,gloss,language_code UNINDEXED,
                tokenize='unicode61 remove_diacritics 0');
            """)
            for i, word in enumerate(surfaces):
                con.execute('INSERT INTO lexicon VALUES (?,?,?)', (f'l{i}', word, language))
                rowid = con.execute('SELECT rowid FROM lexicon WHERE id=?',(f'l{i}',)).fetchone()[0]
                con.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES (?,?,?,?,?)',
                            (rowid, word, word, 'fixture', language))
        return self.db

    def test_unicode_german_arabic_cjk_and_turkish(self):
        cases = [('de',('Straße','Äpfel')), ('ar',('عَلَم','بَيْت')),
                 ('ja',('日本語','かな')), ('ko',('한글','사람')),
                 ('tr',('İstanbul','ışık')), ('es',('árbol','niño'))]
        for language, words in cases:
            with self.subTest(language=language):
                self.make_db(language, words)
                report = audit.check_sqlite(self.db, language)
                self.assertEqual(report['matched_samples'], 2)
                self.assertEqual(report['fallback_samples'], 2)
                self.db.unlink()

    def test_wrong_language_rejected(self):
        self.make_db('de')
        with self.assertRaisesRegex(audit.AuditError, 'language'):
            audit.check_sqlite(self.db, 'fr')

    def test_missing_fts_row_rejected(self):
        self.make_db()
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM lexicon_fts WHERE rowid=1')
        with self.assertRaisesRegex(audit.AuditError, 'FTS5 count'):
            audit.check_sqlite(self.db, 'de')

    def test_wrong_fts_content_rejected(self):
        self.make_db()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE lexicon_fts SET surface='bogus' WHERE rowid=1")
        with self.assertRaisesRegex(audit.AuditError, 'FTS5.*mismatch|FTS5 match'):
            audit.check_sqlite(self.db, 'de')

    def test_wrong_version_rejected(self):
        self.make_db()
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA user_version=1')
        with self.assertRaisesRegex(audit.AuditError, 'version'):
            audit.check_sqlite(self.db, 'de')

    def test_empty_corpus_cannot_claim_ready(self):
        self.make_db(surfaces=())
        with self.assertRaisesRegex(audit.AuditError, 'empty'):
            audit.check_sqlite(self.db, 'de')

    def test_fts_query_escaping_prevents_syntax_error(self):
        self.make_db('en', ('he said "yes"', '100% value', 'a_b\\z'))
        self.assertEqual(audit.check_sqlite(self.db, 'en')['matched_samples'], 3)

    def test_unverified_manifest_stays_blocked(self):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({'languages':[{'code':v} for v in codes], 'packs': []}))
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'sources': []}))
        report = audit.audit_manifest(self.root, shard=0, shards=1)
        self.assertEqual(report['status'], 'BLOCKED_SOURCE')
        self.assertEqual(report['verified_packs'], 0)

    def test_false_published_pack_with_empty_ledger_rejected(self):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({'languages':[{'code':v} for v in codes], 'packs': [{'id':'aa'}]}))
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'sources': []}))
        with self.assertRaisesRegex(audit.AuditError, 'no approved source'):
            audit.audit_manifest(self.root, shard=0, shards=1)

    def test_invalid_shard_is_rejected(self):
        with self.assertRaisesRegex(audit.AuditError,'shard'):
            audit.audit_manifest(self.root, shard=10, shards=10)


if __name__ == '__main__':
    unittest.main()
