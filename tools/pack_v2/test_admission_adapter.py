"""Synthetic admission -> canonical lexical -> actual compile_pack/SQLite/FTS5 checks.

All records are self-authored fixtures and explicitly NOT licensed production data.
Run: python3 -m unittest tools.pack_v2.test_admission_adapter -v
"""
import base64
import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.pack_v2 import pipeline
from tools.pack_v2.admission_adapter import AdapterError, convert

REPO = Path(__file__).resolve().parents[2]
SOURCE_SHA = hashlib.sha256(b'fictional fixture source\n').hexdigest()
RIGHTS_SHA = hashlib.sha256(b'fictional rights fixture\n').hexdigest()
SRC = 'fixture.admission'


def source_record(word, pos, glosses, line):
    fake_raw = pipeline.compact({'word': word, 'pos': pos, 'senses': glosses}).encode() + b'\n'
    return {'source_id': SRC, 'dataset_version': 'fixture-1', 'language': 'de',
            'license_id': 'LicenseRef-SyntheticTestFixture',
            'source_artifact_sha256': SOURCE_SHA,
            'license_evidence_sha256': RIGHTS_SHA,
            'source_line': line, 'source_line_sha256': hashlib.sha256(fake_raw).hexdigest(),
            'excluded_categories': [],
            'content': {'word': word, 'pos': pos, 'senses': glosses}}


class AdmissionAdapterFixtureTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.temp = Path(td.name)
        self.repo = self.temp / 'repo'
        (self.repo / 'legal/ledger').mkdir(parents=True)
        (self.repo / 'catalog').mkdir()
        (self.repo / 'standards/lexical').mkdir(parents=True)
        shutil.copyfile(REPO / 'standards/lexical/lexical.schema.json',
                        self.repo / 'standards/lexical/lexical.schema.json')
        ledger = {'schema_version': '1.0.0', 'sources': [{
            'source_id': SRC, 'status': 'FIXTURE_ONLY',
            'origin_url': 'https://example.org/fictional-fixtures-only',
            'publisher': 'Self-authored illustrative test', 'dataset_version': 'fixture-1',
            'retrieval': {'identity': 'fixture-sha-pinned', 'sha256': SOURCE_SHA},
            'license': {'id': 'LicenseRef-SyntheticTestFixture', 'evidence_sha256': RIGHTS_SHA},
        }]}
        (self.repo / 'legal/ledger/sources.json').write_text(json.dumps(ledger))
        registry = {'schema_version':'1.0.0', 'languages': [{'id':'de','default_script':'Latn'}]}
        (self.repo / 'catalog/language_registry.v1.json').write_text(json.dumps(registry))
        self.stage = self.temp / 'admission'
        self.stage.mkdir()
        self.out = self.temp / 'canonical'
        self.rows = [source_record('Bank', 'noun', ['financial institution', 'bench', 'bench'], 1),
                     source_record('gehen', 'verb', ['move on foot'], 2),
                     source_record('Bank', 'noun', ['financial institution', 'bench', 'bench'], 1)]
        self.make_queue(self.rows)

    def make_queue(self, rows):
        part = self.stage / 'partition-00000000.jsonl'
        part.write_bytes(b''.join((pipeline.compact(row) + '\n').encode() for row in rows))
        job = {'source_id': SRC, 'dataset_version':'fixture-1', 'language':'de',
               'category':'dictionary', 'path':part.name,
               'sha256':hashlib.sha256(part.read_bytes()).hexdigest(),
               'record_count':len(rows), 'partition_index':0,
               'license_id':'LicenseRef-SyntheticTestFixture',
               'license_evidence_sha256': RIGHTS_SHA}
        job['resume_id']='srcadm1-'+hashlib.sha256((pipeline.compact([SOURCE_SHA, job])+'\n').encode()).hexdigest()[:40]
        queue = {'schema_version':'1.0.0', 'status':'ACCEPTED_FOR_QUEUE',
                 'source_id': SRC, 'dataset_version': 'fixture-1', 'language':'de',
                 'source_artifact_sha256':SOURCE_SHA, 'license_evidence_sha256':RIGHTS_SHA,
                 'actual_accepted_records':len(rows), 'publication_approved':False,
                 'jobs':[job]}
        (self.stage / 'queue.json').write_text(json.dumps(queue),encoding='utf-8')
        return queue

    def test_fixture_end_to_end_real_sqlite_and_fts5(self):
        report = convert(self.stage/'queue.json', self.out, self.repo,
                         fixture_only=True, max_lexemes=1)
        self.assertEqual((report['accepted_records'], report['converted_lexemes'],
                          report['converted_senses'], report['deduplicated_records']), (3,2,4,1))
        self.assertEqual(len(report['documents']),2)
        words=[]
        for name in report['documents']:
            canonical = self.out / name
            doc = json.loads(canonical.read_text())
            self.assertFalse(doc['translations'])
            self.assertFalse(doc['examples'])
            self.assertNotIn('levels', doc['senses'][0])
            self.assertFalse(doc['senses'][0]['source']['publication_approved'])
            self.assertEqual(len({s['sense_id'] for s in doc['senses']}),len(doc['senses']))
            with tempfile.TemporaryDirectory() as workspace:
                archive, meta = pipeline.compile_pack(canonical, 'de', Path(workspace), self.repo,
                                                     fixture_only=True)
                self.assertTrue(meta['sha256'])
                inner = {item['path']:base64.b64decode(item['contentBase64'])
                         for item in json.loads(gzip.decompress(archive))['files']}
                db_path = Path(workspace) / 'content.sqlite'
                db_path.write_bytes(inner['content/content.sqlite'])
                with sqlite3.connect(db_path) as conn:
                    self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())
                    self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)
                    word = conn.execute('SELECT surface FROM lexicon').fetchone()[0]
                    words.append(word)
                    self.assertTrue(conn.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ?',
                                                 ('"'+word+'"',)).fetchone())
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM translations').fetchone()[0],0)
                    self.assertIsNone(conn.execute('SELECT cefr_level FROM lexicon').fetchone()[0])
                    if word == 'Bank':
                        self.assertEqual(conn.execute('SELECT COUNT(*) FROM senses').fetchone()[0],3)
                        self.assertTrue(conn.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ?',
                                                     ('"financial"',)).fetchone())
        self.assertEqual(sorted(words),['Bank','gehen'])

    def test_stable_ids_after_repartitioning_same_source_rows(self):
        convert(self.stage/'queue.json', self.out, self.repo, fixture_only=True)
        original = json.loads((self.out/'de-00000000.json').read_text())
        original_ids = {r['surface']:r['lexeme_id'] for r in original['lexemes']}
        self.make_queue(list(reversed(self.rows)))
        new_out = self.temp/'second'
        convert(self.stage/'queue.json', new_out, self.repo, fixture_only=True)
        new_doc = json.loads((new_out/'de-00000000.json').read_text())
        ids = {r['surface']:r['lexeme_id'] for r in new_doc['lexemes']}
        self.assertEqual(ids, original_ids)

    def test_production_without_release_clearance_is_blocked(self):
        with self.assertRaisesRegex(AdapterError,'BLOCKED_SOURCE'):
            convert(self.stage/'queue.json', self.out, self.repo, fixture_only=False)
        self.assertFalse(self.out.exists())

    def test_bad_partition_fails_atomically(self):
        part = self.stage/'partition-00000000.jsonl'
        with part.open('ab') as handle:
            handle.write(b'evil')
        with self.assertRaisesRegex(AdapterError, 'SHA256 mismatch'):
            convert(self.stage/'queue.json', self.out, self.repo, fixture_only=True)
        self.assertFalse(self.out.exists())

    def test_unsupported_pos_refused_instead_of_invented(self):
        self.make_queue([source_record('symbol', 'not-a-certified-pos', ['glyph'], 1)])
        with self.assertRaisesRegex(AdapterError, 'unknown POS'):
            convert(self.stage/'queue.json', self.out, self.repo, fixture_only=True)
        self.assertFalse(self.out.exists())

    def test_report_does_not_approve_source(self):
        report = convert(self.stage/'queue.json', self.out, self.repo, fixture_only=True)
        self.assertEqual(report['status'],'FIXTURE_ONLY_NOT_FOR_PUBLICATION')
        with tempfile.TemporaryDirectory() as workspace:
            with self.assertRaises(ValueError):
                pipeline.compile_pack(self.out/report['documents'][0], 'de', Path(workspace),
                                      self.repo, fixture_only=False)


if __name__ == '__main__':
    unittest.main()
