"""Regression suite: fixture records are never interpreted as production evidence."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.pack_v2 import pipeline
from tools.factory_extensions.sqlite_scale_qa import verify

ROOT = Path(__file__).resolve().parents[3]


class SQLiteScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.doc = json.loads((ROOT / 'standards/lexical/fixtures/positive.json').read_text('utf-8'))
        self.source = self.work / 'de.json'
        self.source.write_text(pipeline.compact(self.doc), encoding='utf-8')
        self.archive, _ = pipeline.compile_pack(self.source, 'de', self.work, ROOT, fixture_only=True)
        self.digest = pipeline.sha(self.archive)
        self.probes = {'contract_version':'1.0.0','cases':[
            {'language':'de','script':'Latn','source_id':'fixture.synthetic.v1',
             'query':'Haus','mode':'fts_phrase','expected_ids':['lex.de.haus']}]}

    def check(self, **options):
        return verify.verify(options.get('archive', self.archive), 'de',
                             options.get('digest', self.digest), options.get('source', self.source),
                             options.get('probes', self.probes), root=ROOT, fixture_only=True)

    def test_good_fixture_remains_not_publishable(self):
        result = self.check()
        self.assertEqual(result['status'], 'FIXTURE_QA_ONLY')
        self.assertFalse(result['publication_approved'])
        self.assertEqual(result['real_rows']['lexicon'], len(self.doc['lexemes']))
        self.assertEqual(result['queries'][0]['matched_rows'], 1)

    def test_reproducible_compiler_bytes_without_publication(self):
        report = verify.verify_reproducible(self.source, 'de', root=ROOT, fixture_only=True)
        self.assertEqual(report['reproducibility'], 'PASS')
        self.assertEqual(report['sha256'], self.digest)

    def test_missing_probes_never_implies_unicode_support(self):
        with self.assertRaisesRegex(ValueError, 'search expectations'):
            self.check(probes={'contract_version':'1.0.0','cases':[]})

    def test_wrong_expected_search_result_is_rejected(self):
        probes = copy.deepcopy(self.probes)
        probes['cases'][0]['expected_ids'] = ['lex.de.gehen']
        with self.assertRaisesRegex(ValueError, 'search mismatch'):
            self.check(probes=probes)

    def test_cross_language_probe_is_rejected(self):
        probes = copy.deepcopy(self.probes)
        probes['cases'][0]['language'] = 'ar'
        with self.assertRaisesRegex(ValueError, 'language mismatch'):
            self.check(probes=probes)

    def test_source_projection_tampering_is_rejected(self):
        different = copy.deepcopy(self.doc)
        different['lexemes'][0]['surface'] = 'Other'
        path = self.work / 'modified.json'
        path.write_text(pipeline.compact(different), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source/SQLite'):
            self.check(source=path)

    def test_changed_archive_digest_and_gzip_corruption(self):
        with self.assertRaises(ValueError):
            self.check(digest='f'*64)
        with self.assertRaises(ValueError):
            self.check(archive=self.archive[:-7])

    def test_fixture_is_never_a_production_candidate(self):
        with self.assertRaises(ValueError):
            verify.verify(self.archive, 'de', self.digest, self.source, self.probes, root=ROOT)

    def test_probes_are_bound_to_real_lexeme_and_source(self):
        for field, value in [('source_id','invented.source'),('script','Arab'),
                             ('expected_ids',['lex.invented']),('mode','arabic_magic_fold')]:
            with self.subTest(field=field):
                probes = copy.deepcopy(self.probes)
                probes['cases'][0][field] = value
                with self.assertRaises(ValueError):
                    self.check(probes=probes)

    def test_grammar_sidecar_requires_byte_equivalent_compiled_rows(self):
        sidecar = self.work / 'de.grammar.json'
        source = copy.deepcopy(self.doc['lexemes'][0]['source'])
        sidecar.write_text(pipeline.compact({
            'contract_version':'1.0.0', 'languageCode':'de',
            'rules':[{'grammar_id':'grammar.fixture.rule', 'category':'nouns',
                      'title':'Fixture-only', 'source':source}]
        }), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'grammar/source mismatch'):
            self.check()

    def test_excessive_search_cases_are_rejected_before_sql(self):
        probes = copy.deepcopy(self.probes)
        probes['cases'] *= 129
        with self.assertRaisesRegex(ValueError, 'search probe limit'):
            self.check(probes=probes)

    def test_control_characters_cannot_be_used_as_fts_queries(self):
        probes = copy.deepcopy(self.probes)
        probes['cases'][0]['query'] = 'Haus\\x00'
        with self.assertRaisesRegex(ValueError, 'invalid query'):
            self.check(probes=probes)

    def test_script_aware_exact_search_does_not_infer_normalization(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE lexicon(id TEXT, surface TEXT, language_code TEXT)')
            db.execute('CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED, tokenize="unicode61 remove_diacritics 0")')
            words = [('ar','Arab','كِتَاب'),('zh','Hans','学校'),('ja','Jpan','かな'),
                     ('ko','Kore','한글'),('th','Thai','ภาษา'),('hi','Deva','किताब')]
            for idx, (lang, _script, surface) in enumerate(words, 1):
                db.execute('INSERT INTO lexicon VALUES(?,?,?)', ('id'+str(idx),surface,lang))
                db.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES(?,?,?,?,?)',
                           (idx,surface,surface,'',lang))
            for idx, (lang, script, surface) in enumerate(words, 1):
                lex_id = 'id'+str(idx)
                doc = {'lexemes':[{'lexeme_id':lex_id, 'language':lang,
                                   'script':script,'source':{'source_id':'fixture.source'}}]}
                cases = {'contract_version':'1.0.0','cases':[
                    {'language':lang,'script':script,'source_id':'fixture.source',
                     'query':surface,'mode':'exact_surface','expected_ids':[lex_id]}]}
                self.assertEqual(len(verify.probe_search(db,cases,doc,lang)), 1)
            doc = {'lexemes':[{'lexeme_id':'id1','language':'ar','script':'Arab',
                               'source':{'source_id':'fixture.source'}}]}
            cases = {'contract_version':'1.0.0','cases':[
                {'language':'ar','script':'Arab','source_id':'fixture.source',
                 'query':'كتاب','mode':'exact_surface','expected_ids':['id1']}]}
            with self.assertRaisesRegex(ValueError, 'search mismatch'):
                verify.probe_search(db,cases,doc,'ar')


if __name__ == '__main__':
    unittest.main()
