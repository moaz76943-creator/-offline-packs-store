"""Synthetic fixture-only Unicode, FTS5 and pack boundary regression tests."""
import json
import gzip
import hashlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from tools.gha_factory.search_qa import audit


class SearchAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'fixture.sqlite'

    def reviewed_source(self):
        """Shared synthetic ledger entry. A hand-copied dict drifts when admission gains a field."""
        from legal.ledger.synthetic import synthetic_source
        return synthetic_source(
            self.root, source_id='fixture-source', kind='dictionary',
            publisher='Synthetic test fixture', dataset_version='1.0.0')

    def write_inputs(self, sources, packs=()):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({
            'languages':[{'code':v} for v in codes], 'packs':list(packs)}))
        (self.root/'legal/ledger').mkdir(parents=True, exist_ok=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({
            'schema_version':'1.0.0', 'sources':sources}))

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


    def test_symlinked_manifest_is_rejected_before_read(self):
        self.write_inputs([])
        target = self.root / 'manifest-target.json'
        (self.root / 'manifest.json').rename(target)
        (self.root / 'manifest.json').symlink_to(target)
        with self.assertRaisesRegex(audit.AuditError, 'unsafe.*manifest'):
            audit.audit_manifest(self.root, shards=1)

    def test_symlinked_source_ledger_is_rejected_before_read(self):
        self.write_inputs([])
        ledger = self.root / 'legal/ledger/sources.json'
        target = self.root / 'legal/ledger/ledger-target.json'
        ledger.rename(target)
        ledger.symlink_to(target)
        with self.assertRaisesRegex(audit.AuditError, 'unsafe.*ledger'):
            audit.audit_manifest(self.root, shards=1)

    def test_symlinked_pack_directory_cannot_escape_repo(self):
        source = self.reviewed_source()
        blob = gzip.compress(b'{}', mtime=0)
        outside = self.root / 'external-pack-dir'
        outside.mkdir()
        (outside / 'aa-1.0.0.pack.gz').write_bytes(blob)
        (self.root / 'packs').symlink_to(outside, target_is_directory=True)
        self.write_inputs([source], [dict(id='aa', version='1.0.0',
                                          sha256=hashlib.sha256(blob).hexdigest())])
        with self.assertRaisesRegex(audit.AuditError, 'unsafe.*pack'):
            audit.audit_manifest(self.root, shards=1)

    def test_invalid_shard_is_rejected(self):
        with self.assertRaisesRegex(audit.AuditError,'shard'):
            audit.audit_manifest(self.root, shard=10, shards=10)


    def test_unapproved_ledger_records_do_not_clear_source_gate(self):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({
            'languages':[{'code':v} for v in codes], 'packs': []}))
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({
            'sources':[{'source_id':'fixture-only','status':'PENDING_REVIEW'}]}))
        report = audit.audit_manifest(self.root, shard=0, shards=1)
        self.assertEqual(report['status'], 'BLOCKED_SOURCE')
        self.assertEqual(report['verified_packs'], 0)

    def test_unapproved_ledger_cannot_authorize_advertised_pack(self):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({
            'languages':[{'code':v} for v in codes], 'packs':[{'id':'aa'}]}))
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({
            'sources':[{'source_id':'fixture-only','status':'PENDING_REVIEW'}]}))
        with self.assertRaisesRegex(audit.AuditError, 'no approved source'):
            audit.audit_manifest(self.root, shard=0, shards=10)

    def test_reviewed_fixture_clears_admission(self):
        source = self.reviewed_source()
        from legal.ledger import admission
        blockers = admission.evaluate(
            {'schema_version': '1.0.0', 'sources': [source]},
            {'languages': [], 'packs': []}, [], self.root)
        self.assertEqual(blockers, [])
        self.assertEqual(source['author'], 'synthetic-fixture')

    def test_empty_assigned_shard_cannot_claim_qa_pass(self):
        codes = [chr(97+i//26)+chr(97+i%26) for i in range(100)]
        (self.root/'manifest.json').write_text(json.dumps({
            'languages':[{'code':v} for v in codes], 'packs':[{'id':'aa'}]}))
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({
            'schema_version':'1.0.0', 'sources':[self.reviewed_source()]}))
        report = audit.audit_manifest(self.root, shard=1, shards=10)
        self.assertEqual(report['status'], 'NO_PACKS_IN_SHARD')
        self.assertEqual(report['verified_packs'], 0)
        self.assertNotEqual(report['status'], 'QA_PASS_NOT_RELEASE_APPROVAL')

    def test_status_only_approval_does_not_clear_source_gate(self):
        self.write_inputs([{'source_id':'forged', 'status':'APPROVED_FOR_REDISTRIBUTION'}])
        self.assertEqual('BLOCKED_SOURCE', audit.audit_manifest(self.root, shards=1)['status'])

    def test_changed_rights_and_missing_review_do_not_clear_source_gate(self):
        source = self.reviewed_source()
        self.write_inputs([source])
        (self.root/'license.txt').write_bytes(b'altered')
        self.assertEqual('BLOCKED_SOURCE', audit.audit_manifest(self.root, shards=1)['status'])
        source = self.reviewed_source()
        source.pop('review')
        self.write_inputs([source])
        self.assertEqual('BLOCKED_SOURCE', audit.audit_manifest(self.root, shards=1)['status'])

    def test_archive_sources_must_resolve_to_verified_ledger_entries(self):
        source = self.reviewed_source()
        self.make_db('aa', ('fixture',))
        blob = gzip.compress(b'{}', mtime=0)
        (self.root/'packs').mkdir()
        (self.root/'packs/aa-1.0.0.pack.gz').write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        self.write_inputs([source], [dict(id='aa', version='1.0.0', sha256=digest)])
        from tools.gha_factory.release import candidate
        # Exercise the source join after canonical inspection, without claiming
        # the small search fixture itself is a production-valid archive.
        with patch.object(candidate, 'inspect_archive') as inspect, \
             patch.object(candidate, '_members', return_value={'content/content.sqlite':self.db.read_bytes()}):
            inspect.return_value = dict(source_ids=['unapproved-source'], archive_sha256=digest)
            with self.assertRaisesRegex(audit.AuditError, 'unapproved archive source'):
                audit.audit_manifest(self.root, shards=1)
            inspect.return_value = dict(source_ids=['fixture-source'], archive_sha256=digest)
            report = audit.audit_manifest(self.root, shards=1)
            self.assertEqual(1, report['verified_packs'])


if __name__ == '__main__':
    unittest.main()
