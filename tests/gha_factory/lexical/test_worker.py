"""Synthetic fixtures only; no corpus assertions or publication permissions."""
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / 'tools/gha_factory/lexical/worker.py'
spec = importlib.util.spec_from_file_location('gha_lexical_worker', MODULE)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class FakeImporter:
    POS = {'noun':'noun','verb':'verb','adj':'adjective'}
    LANGS = {}

    @staticmethod
    def normalize(v):
        import unicodedata
        return unicodedata.normalize('NFC',v)

    @classmethod
    def stable(cls, pre,lang,*parts):
        b = json.dumps(parts,ensure_ascii=False,separators=(',',':')).encode()
        return f'{pre}.{lang}.{hashlib.sha256(b).hexdigest()[:24]}'

    def extract(self,row,lang,source,locator):
        if not isinstance(row.get('senses'),list):
            return None
        lid = w._row_identity(row,lang,self)
        if lid is None:
            return None
        provenance = {'source_id':source['source_id'], 'origin_url':source['origin_url'],
                      'publisher':source['publisher'], 'dataset_version':source['dataset_version'],
                      'retrieval_id':'fixture', 'license_id':source['license']['id'],
                      'record_locator':locator,'publication_approved':True,'fixture_only':False,
                      'artifact_sha256':source['retrieval']['sha256']}
        lex = {'lexeme_id':lid,'language':lang,'script':self.LANGS[lang],
               'direction':'ltr','lemma':row['word'],'surface':row['word'],
               'pos':self.POS[row['pos']],'source':provenance}
        if row.get('forms'):
            lex['morphology']={'inflections':[{'surface':p,'features':{'number':'plural'},
                                             'attested':True} for p in row['forms']]}
        if row.get('ipa'):
            lex['pronunciations']=[{'notation':'ipa','value':row['ipa'],'source':provenance}]
        senses=[]
        for definition in row['senses']:
            if not isinstance(definition,str) or not definition.strip():
                continue
            sid=self.stable('sense',lang,lid,definition,[])
            senses.append({'sense_id':sid,'lexeme_id':lid,
                           'concept_id':self.stable('concept.unmapped',lang,sid),
                           'definition':definition,'source':provenance})
        return (lex,senses) if senses else None


class AcceptValidator:
    def is_valid(self, item):
        return isinstance(item,dict) and bool(item.get('source')) and (
            ('lexeme_id' in item and 'pos' in item) or
            ('sense_id' in item and 'definition' in item))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.joinpath('legal/ledger').mkdir(parents=True)
        (self.root/'legal/ledger/sources.json').write_text('{"schema_version":"1.0.0","sources":[]}')
        self.out=self.root.parent/(self.root.name+'-output')
        self.entry={'id':'ar','default_script':'Arab','scripts':['Arab','Latn']}
        self.scripts={'Arab':{'direction':'rtl'},'Latn':{'direction':'ltr'},
                      'Mong':{'direction':'ttb-ltr'}}
        self.importer=FakeImporter()
        self.source={'source_id':'fixture.example', 'origin_url':'https://example.org/fixture',
                     'publisher':'Synthetic unpublishable test fixture','dataset_version':'unit',
                     'license':{'id':'CC0-1.0'},'retrieval':{'sha256':'a'*64}}
        self.validators=(AcceptValidator(),AcceptValidator())

    def write_lines(self,rows):
        path=self.root/'input.jsonl'
        path.write_bytes(b''.join((w.canonical(row)+'\n').encode() if isinstance(row,dict)
                                  else row for row in rows))
        return path

    def create_db(self, identity='fixture:1'):
        return w.init_db(self.root/'checkpoint.sqlite',identity)

    def ingest(self,db,path,lang='ar',index=0,count=1,max_lines=20000):
        entry = {**self.entry,'id':lang,'default_script': 'Arab' if lang=='ar' else 'Latn',
                 'scripts':['Arab','Latn','Mong']}
        return w._ingest(db,path,lang,index,count,max_lines,self.importer,self.source,
                         entry,self.scripts,self.validators)

    def test_empty_public_ledger_blocks_without_creating_accepted_output(self):
        with self.assertRaisesRegex(ValueError,'BLOCKED_SOURCE'):
            w.approved_source(self.root,'fixture.example')
        self.assertFalse((self.root/'checkpoint.sqlite').exists())

    def test_registry_100_identities_and_direction(self):
        languages=[{'id':f'x{i:02d}','default_script':'Latn','scripts':['Latn']} for i in range(100)]
        self.root.joinpath('catalog').mkdir()
        (self.root/'catalog/language_registry.v1.json').write_text(w.canonical({
            'languages':languages,'scripts':{'Latn':{'direction':'ltr'}}}))
        for language in ('x00','x49','x99'):
            record,scripts,sha=w.registry(self.root,language)
            self.assertEqual(record['id'],language)
            self.assertEqual(len(sha),64)
        with self.assertRaisesRegex(ValueError,'unregistered'):
            w.registry(self.root,'zz')

    def test_five_languages_keep_exact_unicode_and_attested_forms(self):
        cases={'de':'Straße','ar':'عَلَم','en':'look up','es':'árbol','fr':'l’homme'}
        for lang,word in cases.items():
            with self.subTest(language=lang):
                row={'lang_code':lang,'word':word,'pos':'noun','forms':[word+'s'],
                     'ipa':'/ə/','senses':['attested meaning 1','attested meaning 2']}
                parsed=w._extract(row,lang,{**self.entry,'default_script':'Arab' if lang=='ar' else 'Latn'},
                                  self.scripts,self.importer,self.source,'line:1')
                lex,senses=parsed
                self.assertEqual(lex['lemma'],word)
                self.assertEqual(len(senses),2)
                self.assertEqual(lex['morphology']['inflections'][0]['source']['record_locator'],'line:1')
                self.assertEqual(lex['pronunciations'][0]['value'],'/ə/')
                self.assertNotIn('levels',senses[0])
                self.assertEqual(lex['direction'],'rtl' if lang=='ar' else 'ltr')

    def test_partition_deterministic_and_disjoint(self):
        rows=[{'lang_code':'ar','word':'اختبار'+str(i),'pos':'noun','senses':['fixture']} for i in range(360)]
        path=self.write_lines(rows)
        seen=[]
        for index in range(3):
            db=w.init_db(self.root/f'checkpoint{index}.sqlite',f'p{index}')
            state,eof=self.ingest(db,path,index=index,count=3)
            self.assertTrue(eof)
            self.assertEqual(state['input_rows'],360)
            seen.append({r[0] for r in db.execute('SELECT id FROM lexemes')})
            db.close()
        self.assertEqual(len(set.union(*seen)),360)
        self.assertTrue(all(not seen[i].intersection(seen[j])
                            for i in range(3) for j in range(i+1,3)))

    def test_resume_checkpoint_has_no_double_count_and_preserves_two_senses(self):
        path=self.write_lines([
            {'lang_code':'ar','word':'مَعْنَى','pos':'noun','senses':['sense one']},
            {'lang_code':'ar','word':'مَعْنَى','pos':'noun','senses':['sense two']},
            {'lang_code':'ar','word':'مَعْنَى','pos':'noun','senses':['sense one']}])
        db=self.create_db()
        state,eof=self.ingest(db,path,max_lines=1)
        self.assertFalse(eof)
        db.commit()
        db.close()
        db=self.create_db()
        state,eof=self.ingest(db,path)
        self.assertTrue(eof)
        self.assertEqual((state['accepted_lexemes'],state['accepted_senses'],state['duplicates']), (1,2,1))
        self.assertEqual(db.execute('SELECT count(*) FROM evidence').fetchone()[0],2)
        db.close()
        with self.assertRaisesRegex(ValueError,'checkpoint identity mismatch'):
            w.init_db(self.root/'checkpoint.sqlite','a different source')

    def test_malformed_oversized_and_duplicate_json_key_are_counted_without_crash(self):
        huge=b'{"x":"'+b'A'*(w.MAX_LINE_BYTES+10)+b'"}\n'
        path=self.write_lines([b'{bad}\n',b'{"word":"x","word":"y"}\n',huge,
             {'lang_code':'ar','word':'صحيح','pos':'noun','senses':['only verified fixture']},
             {'lang_code':'de','word':'different','pos':'noun','senses':['wrong lang']}])
        db=self.create_db()
        state,eof=self.ingest(db,path)
        self.assertTrue(eof)
        self.assertEqual(state['unrouted_malformed'],4)
        self.assertEqual(state['accepted_lexemes'],1)
        self.assertEqual(state['input_rows'],5)
        db.close()

    def test_fail_closed_on_incorrect_partition_and_source_hash(self):
        with self.assertRaisesRegex(ValueError,'invalid partition'):
            w.execute(self.root,'fixture.example','ar',self.out,3,3)
        with self.assertRaises(FileNotFoundError):
            w.execute(self.root,'fixture.example','ar',self.out,0,1)
        with self.assertRaisesRegex(ValueError,'repeated JSON property'):
            w.json_no_duplicates(b'{"a":1,"a":2}')

    def test_lock_is_exclusive_and_source_identity_stable(self):
        lock=self.root/'worker.lock'
        with w.exclusive_lock(lock):
            with self.assertRaisesRegex(ValueError,'already owned'):
                with w.exclusive_lock(lock):
                    pass
        self.assertNotEqual(w.partition_of('lex.ar.abc',17),w.partition_of('lex.de.abc',17))

    def test_late_attested_forms_keep_own_evidence(self):
        rows=[{'lang_code':'ar','word':'بَيْت','pos':'noun','senses':['home'],
               'forms':['بُيُوت']},
              {'lang_code':'ar','word':'بَيْت','pos':'noun','senses':['building'],
               'forms':['بَيْتَان']}]
        path=self.write_lines(rows)
        db=self.create_db()
        state,eof=self.ingest(db,path)
        self.assertTrue(eof)
        self.assertEqual(state['accepted_lexemes'],1)
        lex=json.loads(db.execute('SELECT payload FROM lexemes').fetchone()[0])
        forms=lex['morphology']['inflections']
        self.assertEqual({f['surface'] for f in forms},{'بُيُوت','بَيْتَان'})
        self.assertEqual({f['source']['record_locator'] for f in forms},{'line:1','line:2'})
        db.close()

    def test_malformed_valid_json_record_does_not_abort_all_rows(self):
        class CrashingImporter(FakeImporter):
            def extract(self,row,lang,source,locator):
                if row.get('word') == 'bad':
                    raise TypeError('invalid nested tags')
                return super().extract(row,lang,source,locator)
        self.importer=CrashingImporter()
        path=self.write_lines([{'lang_code':'ar','word':'bad','pos':'noun',
                                'senses':['should reject']},
                               {'lang_code':'ar','word':'good','pos':'noun',
                                'senses':['attested synthetic']}])
        db=self.create_db()
        state,eof=self.ingest(db,path)
        self.assertTrue(eof)
        self.assertEqual(state['rejected'],1)
        self.assertEqual(state['accepted_lexemes'],1)
        db.close()

    def test_bounded_25000_line_stream_and_checkpoint(self):
        row={'lang_code':'ar','word':'حقيقة','pos':'noun','senses':['fact']}
        path=self.write_lines([row]*25000)
        db=self.create_db()
        state,eof=self.ingest(db,path,max_lines=20000)
        self.assertFalse(eof)
        self.assertEqual(state['input_rows'],20000)
        self.assertEqual((state['accepted_lexemes'],state['accepted_senses']), (1,1))
        state,eof=self.ingest(db,path,max_lines=8000)
        self.assertTrue(eof)
        self.assertEqual(state['duplicates'],24999)
        db.close()


if __name__ == '__main__':
    unittest.main()
