"""Deterministic offline candidate conformance and negative/rollback tests."""
import base64
import gzip
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.gha_factory.release import candidate as rc


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def sample(self, language='de', surface='Überraschung'):
        path = self.root / 'fixture.sqlite'
        if path.exists():
            path.unlink()
        with sqlite3.connect(path) as db:
            db.executescript('''
                PRAGMA foreign_keys=ON;
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,description TEXT);
                CREATE TABLE concepts(concept_id TEXT PRIMARY KEY);
                CREATE TABLE lexicon(id TEXT PRIMARY KEY,surface TEXT,part_of_speech TEXT,pos TEXT,
                    direction TEXT,language_code TEXT,script TEXT,dialect TEXT,sort_key TEXT,
                    cefr_level TEXT,frequency_rank INTEGER,fields_json TEXT,source_json TEXT);
                CREATE INDEX idx_lexicon_order ON lexicon(language_code,sort_key,id);
                CREATE INDEX idx_lexicon_surface ON lexicon(language_code,surface);
                CREATE TABLE senses(sense_id TEXT PRIMARY KEY,lexeme_id TEXT REFERENCES lexicon(id),
                    concept_id TEXT REFERENCES concepts(concept_id),definition TEXT,payload_json TEXT);
                CREATE TABLE translations(translation_id TEXT PRIMARY KEY,from_sense_id TEXT REFERENCES senses(sense_id),
                    to_sense_id TEXT REFERENCES senses(sense_id),language_code TEXT,text TEXT,payload_json TEXT);
                CREATE TABLE examples(example_id TEXT PRIMARY KEY,sense_id TEXT REFERENCES senses(sense_id),
                    lexeme_id TEXT REFERENCES lexicon(id),language_code TEXT,text TEXT,payload_json TEXT);
                CREATE TABLE lexical_relations(relation_id TEXT PRIMARY KEY,from_lexeme_id TEXT REFERENCES lexicon(id),
                    to_lexeme_id TEXT REFERENCES lexicon(id),kind TEXT,payload_json TEXT);
                CREATE TABLE grammar(grammar_id TEXT PRIMARY KEY,language_code TEXT,category TEXT,title TEXT,
                    payload_json TEXT,source_json TEXT);
                CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED,
                    tokenize='unicode61 remove_diacritics 0');
                CREATE INDEX idx_senses_lexeme ON senses(lexeme_id,sense_id);
                CREATE INDEX idx_examples_sense ON examples(sense_id,example_id);
                CREATE INDEX idx_translations_directed ON translations(from_sense_id,language_code,translation_id);
                PRAGMA user_version=2;
            ''')
            db.executemany('INSERT INTO metadata VALUES (?,?)', [('contract_version','1.0.0'),
                         ('mapping_version','2.0.0'), ('language_code', language)])
            db.execute('INSERT INTO schema_migrations VALUES (?,?)', ('2.0.0', 'v2'))
            db.execute("INSERT INTO concepts VALUES ('c')")
            db.execute('INSERT INTO lexicon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('x',surface,'noun','noun','rtl' if language=='ar' else 'ltr',language,
                        'Arab' if language=='ar' else 'Latn',None,surface,None,None,'{}','{}'))
            db.execute("INSERT INTO senses VALUES ('s','x','c','real fixture','{}')")
            db.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES(1,?,?,?,?)',
                       (surface,surface,'real fixture',language))
            db.commit()
        data = path.read_bytes()
        counts = dict.fromkeys(('lexicon','concepts','senses','translations','examples','lexical_relations','grammar'), 0)
        counts.update(lexicon=1,concepts=1,senses=1)
        info = {'languageCode':language,'schemaVersion':'2.0.0','tableCounts':counts,
                'sqliteSha256':rc.digest(data),'fixtureOnly':True,'sourceIds':['fixture-ref']}
        info_bytes=rc.json_bytes(info)
        meta = {'packId':language,'languageCode':language,'schemaVersion':'2.0.0','version':'1.0.0',
                'contentSha256':rc.digest(data),'contentMetadataSha256':rc.digest(info_bytes),
                'contentRows':1,'fixtureOnly':True,'sourceIds':['fixture-ref']}
        files = {'content/content.sqlite':data, 'content/content.json':info_bytes,
                 'metadata/pack.json':rc.json_bytes(meta)}
        env = {'packId':language,'version':'1.0.0','contractVersion':'1.0.0',
               'schemaVersion':'2.0.0','format':'json-gzip-v1',
               'files':[{'path':name,'contentBase64':base64.b64encode(files[name]).decode()}
                        for name in rc.MEMBERS]}
        return env

    def archive(self, env):
        out=io.BytesIO()
        with gzip.GzipFile(filename='',fileobj=out,mode='wb',mtime=0) as f:
            f.write(rc.json_bytes(env))
        return out.getvalue()

    def test_fixture_is_quarantined_and_deterministic(self):
        a=self.archive(self.sample())
        self.assertEqual(a,self.archive(self.sample()))
        report=rc.inspect_archive(a,'de',allow_fixture=True)
        self.assertEqual(report['actual_lexical_count'],1)
        self.assertEqual(report['target_lexical_count'],1)
        self.assertEqual(report['fts5_queries_passed'],1)
        self.assertEqual(report['short_query_fallback'],'passed')
        with self.assertRaisesRegex(rc.ReleaseError,'synthetic fixture'):
            rc.inspect_archive(a,'de')

    def test_arabic_and_cjk_unicode_queries(self):
        for language,word in [('ar','كِتاب'),('zh','学校'),('ja','学校'),('ko','학교')]:
            with self.subTest(language=language):
                a=self.archive(self.sample(language,word))
                self.assertEqual(rc.inspect_archive(a,language,allow_fixture=True)['fts5_queries_passed'],1)

    def test_json_decoder_rejects_duplicate_keys_at_every_depth(self):
        # JSON's last-key-wins behavior can change signed identity and rights
        # metadata depending on which parser later consumes the same bytes.
        for label, raw in (
            ('envelope', b'{"packId":"fr","packId":"de"}'),
            ('content info', b'{"sourceIds":["wrong"],"sourceIds":["fixture-ref"]}'),
            ('pack metadata', b'{"source":{"id":"first","id":"second"}}'),
        ):
            with self.subTest(label=label), self.assertRaisesRegex(rc.ReleaseError, 'invalid ' + label):
                rc._json(raw, label)

    def test_json_decoder_rejects_nonfinite_constants(self):
        for value in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(value=value), self.assertRaisesRegex(rc.ReleaseError, 'invalid envelope'):
                rc._json(b'{"untrusted":' + value + b'}', 'envelope')

    def test_duplicate_archive_identity_rejected_before_candidate_staging(self):
        # A duplicate first key must not be silently shadowed by the last.
        raw = rc.json_bytes(self.sample())
        archive = gzip.compress(b'{"packId":"fr",' + raw[1:], mtime=0)
        with self.assertRaisesRegex(rc.ReleaseError, 'invalid envelope'):
            rc.inspect_archive(archive, 'de', allow_fixture=True)

    def test_wrong_language_and_stale_version(self):
        env=self.sample()
        with self.assertRaisesRegex(rc.ReleaseError,'wrong language'):
            rc.inspect_archive(self.archive(env),'fr',allow_fixture=True)
        env['version']='0.9.0'
        with self.assertRaisesRegex(rc.ReleaseError,'stale'):
            rc.inspect_archive(self.archive(env),'de',allow_fixture=True)

    def test_missing_duplicate_and_corrupt_members(self):
        for change in ('missing','duplicate','base64'):
            env=self.sample()
            if change=='missing':env['files'].pop()
            if change=='duplicate':env['files'][1]['path']=env['files'][0]['path']
            if change=='base64':env['files'][1]['contentBase64']='^not base64'
            with self.subTest(change=change),self.assertRaises(rc.ReleaseError):
                rc.inspect_archive(self.archive(env),'de',allow_fixture=True)

    def test_wrong_hash_and_corrupted_sqlite(self):
        env=self.sample()
        meta=next(x for x in env['files'] if x['path']=='metadata/pack.json')
        payload=json.loads(base64.b64decode(meta['contentBase64']))
        payload['contentSha256']='0'*64
        meta['contentBase64']=base64.b64encode(rc.json_bytes(payload)).decode()
        with self.assertRaisesRegex(rc.ReleaseError,'hash'):
            rc.inspect_archive(self.archive(env),'de',allow_fixture=True)

    def test_archive_bomb_trailing_bytes_and_truncation(self):
        archive=self.archive(self.sample())
        with self.assertRaises(rc.ReleaseError):rc.inspect_archive(archive+b'extra','de',allow_fixture=True)
        with self.assertRaises(rc.ReleaseError):rc.inspect_archive(archive[:-9],'de',allow_fixture=True)
        bomb=gzip.compress(b'a'*(rc.MAX_ENVELOPE+1))
        with self.assertRaisesRegex(rc.ReleaseError,'expansion'):
            rc.bounded_gzip(bomb)

    def test_no_approved_source_never_changes_candidates(self):
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text('{"schema_version":"1.0.0","sources":[]}')
        (self.root/'manifest.json').write_text(json.dumps({'languages':[{'code':f'l{i:03}'} for i in range(100)],'packs':[]}))
        (self.root/'version.json').write_text('{"packs":{},"release_status":"BLOCKED_DEPENDENCY"}')
        (self.root/'lex.json').write_text('{}')
        output=self.root/'candidates'
        output.mkdir()
        known=output/'prior-good.pack.gz'
        known.write_bytes(b'known-good')
        self.assertEqual(rc.audit(self.root)['status'],'BLOCKED_SOURCE')
        with self.assertRaisesRegex(rc.ReleaseError,'BLOCKED_SOURCE'):
            rc.build_candidate(self.root,'lex.json',rc.digest(b'{}'),'l000',output)
        self.assertEqual(known.read_bytes(),b'known-good')
        self.assertEqual(sorted(p.name for p in output.iterdir()),['prior-good.pack.gz'])
        (self.root/'version.json').write_text('{"packs":{"l000":"unsafe"}}')
        with self.assertRaisesRegex(rc.ReleaseError,'no approved sources'):
            rc.audit(self.root)

    def test_signature_fail_closed_and_path_traversal(self):
        with self.assertRaises(rc.ReleaseError):
            rc.verify_signature(b'candidate',self.root/'absent.pem',self.root/'absent.sig')
        with self.assertRaises(rc.ReleaseError):
            rc.safe_file(self.root,'../secret.json')


    def test_candidate_receipt_is_immutable_and_replay_is_deterministic(self):
        archive = b'deterministic candidate bytes'
        report = {'language': 'de', 'archive_sha256': rc.digest(archive),
                  'status': 'FIXTURE_QUARANTINED', 'publication_approved': False}
        output = self.root / 'staged'
        rc.stage_candidate(output, 'de', archive, report)
        self.assertEqual(rc.stage_candidate(output, 'de', archive, report), report)
        self.assertEqual(len(list(output.iterdir())), 2)
        receipt = next(output.glob('*.report.json'))
        receipt.write_text('{"status":"ADMITTED"}')
        with self.assertRaisesRegex(rc.ReleaseError, 'receipt mismatch'):
            rc.stage_candidate(output, 'de', archive, report)
        self.assertEqual(next(output.glob('*.pack.gz')).read_bytes(), archive)
        self.assertEqual(receipt.read_text(), '{"status":"ADMITTED"}')

    def test_symlinked_receipt_and_archive_are_rejected(self):
        archive = b'valid immutable archive'
        report = {'language': 'de', 'archive_sha256': rc.digest(archive)}
        output = self.root / 'staged'
        output.mkdir()
        external = self.root / 'outside'
        external.write_bytes(archive)
        pack = output / ('de-' + rc.digest(archive) + '.pack.gz')
        pack.symlink_to(external)
        with self.assertRaisesRegex(rc.ReleaseError, 'symlink'):
            rc.stage_candidate(output, 'de', archive, report)
        pack.unlink()
        receipt = output / ('de-' + rc.digest(archive) + '.report.json')
        receipt.symlink_to(external)
        with self.assertRaisesRegex(rc.ReleaseError, 'symlink'):
            rc.stage_candidate(output, 'de', archive, report)

    def test_report_stage_failure_rolls_back_only_new_candidate(self):
        from unittest.mock import patch
        archive = b'rollback candidate'
        report = {'language': 'de', 'archive_sha256': rc.digest(archive)}
        output = self.root / 'staged'
        output.mkdir()
        previous = output / 'last-known-good.pack.gz'
        previous.write_bytes(b'keep')
        link = rc.os.link
        calls = []

        def fail_second_link(source, dest):
            calls.append(dest)
            if len(calls) == 2:
                raise OSError('simulated receipt write interruption')
            return link(source, dest)

        with patch.object(rc.os, 'link', side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, 'interruption'):
                rc.stage_candidate(output, 'de', archive, report)
        self.assertEqual([(p.name, p.read_bytes()) for p in output.iterdir()],
                         [('last-known-good.pack.gz', b'keep')])

    def test_receipt_hash_and_source_ids_fail_closed(self):
        archive = b'bytes'
        with self.assertRaisesRegex(rc.ReleaseError, 'receipt identity/hash'):
            rc.stage_candidate(self.root / 'out', 'de', archive,
                               {'language': 'de', 'archive_sha256': '0' * 64})
        for ids in ([42], ['duplicate', 'duplicate'], ['']):
            env = self.sample()
            info = next(x for x in env['files'] if x['path'] == 'content/content.json')
            meta = next(x for x in env['files'] if x['path'] == 'metadata/pack.json')
            obj = json.loads(base64.b64decode(info['contentBase64']))
            obj['sourceIds'] = ids
            info_bytes = rc.json_bytes(obj)
            info['contentBase64'] = base64.b64encode(info_bytes).decode()
            metadata = json.loads(base64.b64decode(meta['contentBase64']))
            metadata['sourceIds'] = ids
            metadata['contentMetadataSha256'] = rc.digest(info_bytes)
            meta['contentBase64'] = base64.b64encode(rc.json_bytes(metadata)).decode()
            with self.subTest(ids=ids), self.assertRaisesRegex(rc.ReleaseError, 'provenance'):
                rc.inspect_archive(self.archive(env), 'de', allow_fixture=True)

    def test_evidence_receipts_bind_real_bytes_to_approved_source(self):
        (self.root / 'legal/ledger').mkdir(parents=True)
        source = self.root / 'source-proof.txt'
        license_proof = self.root / 'license-proof.txt'
        source.write_bytes(b'exact source bytes')
        license_proof.write_bytes(b'exact legal evidence bytes')
        entry = {
            'source_id': 's1', 'status': 'APPROVED_FOR_REDISTRIBUTION',
            'retrieval': {'artifact_path': 'source-proof.txt', 'sha256': rc.digest(source.read_bytes())},
            'license': {'evidence_path': 'license-proof.txt',
                        'evidence_sha256': rc.digest(license_proof.read_bytes()), 'id': 'CC0-1.0'},
            'review': {'reviewer': 'fixture reviewer', 'decision_url': 'https://example.org/decision'},
            'dataset_version': '1.2.3'
        }
        (self.root / 'legal/ledger/sources.json').write_text(
            json.dumps({'schema_version': '1.0.0', 'sources': [entry]}))
        receipt = rc.evidence_receipts(self.root, ['s1'])
        self.assertEqual(receipt[0]['source_sha256'], rc.digest(source.read_bytes()))
        self.assertEqual(receipt[0]['license_evidence_sha256'], rc.digest(license_proof.read_bytes()))
        license_proof.write_bytes(b'altered')
        with self.assertRaisesRegex(rc.ReleaseError, 'license SHA-256 evidence mismatch'):
            rc.evidence_receipts(self.root, ['s1'])
        with self.assertRaisesRegex(rc.ReleaseError, 'unapproved'):
            rc.evidence_receipts(self.root, ['unlisted'])


if __name__ == '__main__':
    unittest.main()
