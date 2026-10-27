"""Synthetic isolated attacks against canonical compiler output; never production."""
import base64
import copy
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from tools.pack_v2 import pipeline
from tools.gha_factory.release import candidate
from tools.gha_factory.pack_conformance import check

ROOT = Path(__file__).resolve().parents[3]

class ConformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.doc = json.loads((ROOT/'standards/lexical/fixtures/positive.json').read_text())
        self.src = self.root/'lex.json'
        self.src.write_text(pipeline.compact(self.doc))
        self.archive, _ = pipeline.compile_pack(self.src, 'de', self.root, ROOT, fixture_only=True)
        self.env = json.loads(gzip.decompress(self.archive))

    def pack(self, env=None):
        return gzip.compress(pipeline.compact(env or self.env).encode(), mtime=0)

    def inspect(self, blob=None):
        return check.inspect(blob or self.archive, 'de', root=ROOT, allow_fixture=True)

    def mutate_db(self, sql, args=(), recount=False):
        env = copy.deepcopy(self.env)
        files = {r['path']:base64.b64decode(r['contentBase64']) for r in env['files']}
        path = self.root/'mutant.sqlite'
        path.write_bytes(files['content/content.sqlite'])
        refreshed_counts = None
        with sqlite3.connect(path) as db:
            db.execute(sql, args)
            if recount:
                refreshed_counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                    for table in ('concepts', 'lexicon', 'senses', 'translations',
                                  'examples', 'lexical_relations', 'grammar')}
        data = path.read_bytes()
        info = json.loads(files['content/content.json'])
        meta = json.loads(files['metadata/pack.json'])
        if refreshed_counts is not None:
            info['tableCounts'] = refreshed_counts
        info['sqliteSha256'] = pipeline.sha(data)
        info_bytes = (pipeline.compact(info)+'\n').encode()
        meta['contentSha256'] = pipeline.sha(data)
        meta['contentMetadataSha256'] = pipeline.sha(info_bytes)
        files.update({'content/content.sqlite':data,'content/content.json':info_bytes,
                      'metadata/pack.json':(pipeline.compact(meta)+'\n').encode()})
        for r in env['files']:
            r['contentBase64'] = base64.b64encode(files[r['path']]).decode()
        return self.pack(env)

    def test_duplicate_key_bypass_rejected(self):
        raw = gzip.decompress(self.archive)
        bad = gzip.compress(b'{"packId":"wrong",'+raw[1:], mtime=0)
        # Both candidate and stricter conformance paths must now fail closed.
        with self.assertRaisesRegex(candidate.ReleaseError, 'invalid envelope'):
            candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.inspect(bad)

    def test_nonfinite_unknown_metadata_rejected(self):
        raw = gzip.decompress(self.archive)
        bad = gzip.compress(b'{"unused":NaN,'+raw[1:], mtime=0)
        with self.assertRaisesRegex(candidate.ReleaseError, 'invalid envelope'):
            candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaises(ValueError):
            self.inspect(bad)

    def test_wrong_unsampled_fts_lemma_rejected(self):
        bad = self.mutate_db("UPDATE lexicon_fts SET lemma='forged' WHERE rowid=(SELECT MAX(rowid) FROM lexicon)")
        candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'FTS5'):
            self.inspect(bad)

    def test_missing_provenance_inside_record_rejected(self):
        bad = self.mutate_db("UPDATE lexicon SET source_json='{}'")
        candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'provenance|source'):
            self.inspect(bad)

    def test_valid_canonical_directed_multilingual_fixture(self):
        report = self.inspect()
        self.assertEqual(report['status'], 'FIXTURE_QUARANTINED')
        self.assertEqual(report['actual_counts']['lexicon'], len(self.doc['lexemes']))
        self.assertFalse(report['publication_approved'])
        self.assertEqual(report['semantic_accuracy'], 'NOT_VERIFIED')

    def test_production_fixture_forbidden(self):
        with self.assertRaisesRegex(ValueError,'synthetic fixture'):
            check.inspect(self.archive,'de',root=ROOT)

    def test_schema_and_relational_attacks(self):
        attacks = [
            'DROP INDEX idx_lexicon_surface',
            'CREATE TRIGGER evil AFTER INSERT ON metadata BEGIN DELETE FROM lexicon; END',
            "UPDATE schema_migrations SET version='3.0.0'",
            "UPDATE senses SET lexeme_id='absent'",
            "UPDATE examples SET sense_id='absent'",
            "UPDATE translations SET to_sense_id='absent'",
            "UPDATE lexicon SET language_code='xx' WHERE id='lex.de.haus'",
            "UPDATE examples SET language_code='fr' WHERE example_id='ex.de.haus'",
            "UPDATE translations SET language_code='fr' WHERE translation_id='tr.de.ar.house'",
            "UPDATE lexicon_fts SET gloss='forged' WHERE rowid=(SELECT MAX(rowid) FROM lexicon)",
            "UPDATE lexicon_fts SET language_code='xx' WHERE rowid=(SELECT MAX(rowid) FROM lexicon)",
            'DELETE FROM lexicon_fts WHERE rowid=(SELECT MAX(rowid) FROM lexicon)',
            "UPDATE lexicon SET fields_json='{}' WHERE id='lex.de.haus'",
            "UPDATE metadata SET value='fr' WHERE key='language_code'",
            'PRAGMA user_version=3',
        ]
        for sql in attacks:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.inspect(self.mutate_db(sql))

    def test_gzip_attack_matrix(self):
        for blob in [b'invalid gzip',self.archive[:-5],self.archive+b'trailing',
                     self.archive+self.archive,self.archive[:12]+b'broken'+self.archive[18:]]:
            with self.subTest(blob=blob[:12]),self.assertRaises(ValueError):
                self.inspect(blob)

    def test_envelope_attack_matrix(self):
        for attack in ['missing','duplicate','extra','traversal','base64','pack','contract','version','schema']:
            env = copy.deepcopy(self.env)
            if attack == 'missing': env['files'].pop()
            elif attack == 'duplicate': env['files'][1] = env['files'][0]
            elif attack == 'extra': env['files'].append(env['files'][0])
            elif attack == 'traversal': env['files'][0]['path'] = '../outside'
            elif attack == 'base64': env['files'][0]['contentBase64'] = '%%'
            else: env[{'pack':'packId','contract':'contractVersion','version':'version','schema':'schemaVersion'}[attack]] = 'wrong'
            with self.subTest(attack=attack),self.assertRaises(ValueError):
                self.inspect(self.pack(env))

    def test_strict_json_numbers_unicode_and_size(self):
        from unittest.mock import patch
        for raw in [b'{"x":1,"x":2}',b'{"x":Infinity}',b'{"x":1e9999}',
                    b'{"x":"\\ud800"}',b'{"x":"\\u0000"}',b'\xff',b'{']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                check.strict_json(raw)
        with self.assertRaises(ValueError):check.strict_json(b'{}',1)
        with patch.object(candidate,'MAX_ENVELOPE',1024):
            with self.assertRaises(ValueError):self.inspect(gzip.compress(b'a'*1025))

    def test_expected_archive_sha_and_immutability(self):
        before = self.archive
        with self.assertRaisesRegex(ValueError,'hash'):
            check.inspect(before,'de',root=ROOT,allow_fixture=True,expected_sha256='0'*64)
        self.inspect()
        self.assertEqual(before,self.archive)

    def test_reproducible_canonical_bytes(self):
        work = self.root/'second'
        work.mkdir()
        archive, _ = pipeline.compile_pack(self.src,'de',work,ROOT,fixture_only=True)
        self.assertEqual(self.archive,archive)

    def test_source_gate_empty_and_manifest_unchanged(self):
        before = {p:p.read_bytes() for p in [ROOT/'manifest.json',ROOT/'version.json']}
        report = check.audit(ROOT)
        self.assertEqual(report['status'],'BLOCKED_SOURCE')
        self.assertEqual(report['registered_languages'],100)
        self.assertEqual(report['actual_packs_verified'],0)
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_all_100_registered_identities_with_synthetic_script_probes(self):
        registry = json.loads((ROOT/'catalog/language_registry.v1.json').read_text())
        probes = {'Latn':'Straße ÄÖÜ ß ss e\u0301 ñ ç İ ı', 'Cyrl':'Язык',
                  'Arab':'كِتاب أإآ ١۲ کتاب می\u200cروم', 'Grek':'γλώσσα',
                  'Armn':'Հայերեն','Geor':'ქართული','Hans':'学校','Hant':'學校',
                  'Jpan':'かな カナ 学校','Kore':'한글 한','Deva':'भाषा',
                  'Beng':'ভাষা','Guru':'ਭਾਸ਼ਾ','Gujr':'ભાષા','Taml':'மொழி',
                  'Telu':'భాష','Knda':'ಭಾಷೆ','Mlym':'ഭാഷ','Orya':'ଭାଷା',
                  'Sinh':'භාෂාව','Thai':'ภาษา','Laoo':'ພາສາ','Khmr':'ភាសា',
                  'Mymr':'ဘာသာ','Ethi':'ቋንቋ','Mong':'ᠮᠣᠩᠭᠣᠯ','Thaa':'ދިވެހި'}
        checked = 0
        for entry in registry['languages']:
            lang, script = entry['id'], entry['default_script']
            with self.subTest(language=lang,script=script):
                work = self.root/lang
                work.mkdir()
                lex = copy.deepcopy(self.doc['lexemes'][0])
                lex.update(lexeme_id='lex.'+lang+'.probe',language=lang,script=script,
                           surface=probes[script],lemma=probes[script],
                           direction=registry['scripts'][script]['direction'])
                lex.pop('morphology',None)
                lex.pop('pronunciations',None)
                sense = copy.deepcopy(self.doc['senses'][0])
                sense.update(sense_id='sense.'+lang+'.probe',lexeme_id=lex['lexeme_id'],
                             definition='SYNTHETIC Unicode regression probe')
                doc = {'contract_version':'1.0.0','document_id':'fixture.'+lang,
                       'lexemes':[lex],'senses':[sense],'translations':[],
                       'examples':[],'relations':[]}
                src = work/'probe.json'
                src.write_text(pipeline.compact(doc))
                archive, _ = pipeline.compile_pack(src,lang,work,ROOT,fixture_only=True)
                report = check.inspect(archive,lang,root=ROOT,allow_fixture=True)
                self.assertEqual(report['actual_counts']['lexicon'],1)
                self.assertEqual(report['status'],'FIXTURE_QUARANTINED')
                checked += 1
        self.assertEqual(checked,100)

    def test_original_unicode_and_search_distinctions(self):
        with sqlite3.connect(':memory:') as db:
            db.execute("CREATE VIRTUAL TABLE words USING fts5(surface,tokenize='unicode61 remove_diacritics 0')")
            words = ['Straße','Strasse','Äpfel','Apfel','é','e\u0301','İ','ı',
                     'عَلَم','علم','أ','ا','١٢','12','学校','學校','かな','カナ',
                     '한글','한','می\u200cروم','فارسی Latin','100% a_b "quoted"']
            db.executemany('INSERT INTO words(surface) VALUES(?)',[(w,) for w in words])
            self.assertEqual([r[0] for r in db.execute('SELECT surface FROM words ORDER BY rowid')],words)
            for word in words:
                quoted = '"'+word.replace('"','""')+'"'
                self.assertTrue(db.execute('SELECT 1 FROM words WHERE words MATCH ?', (quoted,)).fetchone())
            for query, excluded in [('Straße','Strasse'),('Äpfel','Apfel'),('عَلَم','علم'),('学校','學校')]:
                hits = {r[0] for r in db.execute('SELECT surface FROM words WHERE words MATCH ?',('"'+query+'"',))}
                self.assertNotIn(excluded,hits)

    def test_public_cli_has_no_fixture_release_bypass(self):
        import subprocess
        archive = self.root/'fixture.pack.gz'
        archive.write_bytes(self.archive)
        proc = subprocess.run([sys.executable,'-m','tools.gha_factory.pack_conformance.check',
                               '--root',str(ROOT),'--archive',str(archive),'--language','de',
                               '--sha256',pipeline.sha(self.archive)],cwd=ROOT,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(proc.returncode,1)
        self.assertFalse(json.loads(proc.stdout)['publication_approved'])

    def test_duplicate_global_ids_and_false_fixture_promotion(self):
        bad = self.mutate_db("UPDATE examples SET example_id='lex.de.haus' WHERE example_id='ex.de.haus'")
        with self.assertRaisesRegex(ValueError,'duplicate global'):
            self.inspect(bad)
        env = copy.deepcopy(self.env)
        for member in env['files']:
            if member['path'].endswith('.json'):
                payload = json.loads(base64.b64decode(member['contentBase64']))
                payload['fixtureOnly'] = False
                data = (pipeline.compact(payload)+'\n').encode()
                member['contentBase64'] = base64.b64encode(data).decode()
        # Per-record provenance still declares fixtures; production must fail.
        with self.assertRaisesRegex(ValueError,'source not approved'):
            check.inspect(self.pack(env),'de',root=ROOT)

    def test_self_asserted_release_flags_rejected(self):
        env = copy.deepcopy(self.env)
        env.update(signatureVerified=True,productionReady=True)
        with self.assertRaisesRegex(ValueError,'unexpected envelope'):
            self.inspect(self.pack(env))

    def test_duplicate_nested_metadata_rejected(self):
        env = copy.deepcopy(self.env)
        member = next(r for r in env['files'] if r['path']=='metadata/pack.json')
        raw = base64.b64decode(member['contentBase64'])
        member['contentBase64'] = base64.b64encode(b'{"packId":"wrong",'+raw[1:]).decode()
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.inspect(self.pack(env))

    def test_rejects_unreferenced_concepts_with_reconciled_counts(self):
        bad = self.mutate_db("INSERT INTO concepts VALUES (?)", ('concept.unreferenced',),
                             recount=True)
        # PRAGMA and declared counts pass; canonical conformance must still reject it.
        candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'unreferenced concept'):
            self.inspect(bad)

    def test_rejects_concept_global_id_collision(self):
        bad = self.mutate_db("INSERT INTO concepts VALUES (?)", ('lex.de.haus',),
                             recount=True)
        candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'duplicate global stable ID'):
            self.inspect(bad)

    def test_rejects_grammar_global_id_collision(self):
        source = self.doc['lexemes'][0]['source']
        rule = {'grammar_id': 'lex.de.haus', 'category': 'noun',
                'title': 'Synthetic collision', 'source': source}
        bad = self.mutate_db(
            'INSERT INTO grammar VALUES (?,?,?,?,?,?)',
            ('lex.de.haus', 'de', 'noun', 'Synthetic collision',
             pipeline.compact(rule), pipeline.compact(source)), recount=True)
        candidate.inspect_archive(bad, 'de', allow_fixture=True)
        with self.assertRaisesRegex(ValueError, 'duplicate global stable ID'):
            self.inspect(bad)
