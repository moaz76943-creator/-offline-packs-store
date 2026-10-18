"""Production gating exercised with isolated, explicitly synthetic approved fixtures."""
import copy
import gzip
import hashlib
import json
import sqlite3
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from tools.gha_factory.content_ingestion.worker import snapshot, process, export, Blocked
from tools.gha_factory.content_ingestion.normalize import canonical

ROOT=Path(__file__).resolve().parents[3]


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'catalog').mkdir();(self.root/'legal/ledger').mkdir(parents=True)
        for name in ['language_registry.v1.json','content_readiness.v1.json']:
            (self.root/'catalog'/name).write_bytes((ROOT/'catalog'/name).read_bytes())
        (self.root/'input').mkdir()
        (self.root/'input/license.txt').write_bytes(b'TEST ONLY source license evidence')
        (self.root/'input/review.txt').write_bytes(b'TEST ONLY reviewer evidence')
        self.source={'source_id':'test.synthetic','kind':'dictionary','fixture_only':True,
                     'origin_url':'https://example.org/data','publisher':'TEST ONLY',
                     'dataset_version':'fixture-v1','status':'APPROVED_FOR_REDISTRIBUTION',
                     'alterations':['TEST ONLY'],
                     'retrieval':{'identity':'fixture-v1','url':'https://example.org/data.jsonl',
                                  'date':'2026-10-13','artifact_path':'input/data.jsonl'},
                     'license':{'id':'CC0-1.0','evidence_url':'https://example.org/license',
                                'evidence_path':'input/license.txt','evidence_sha256':self.sha(b'TEST ONLY source license evidence')},
                     'review':{'reviewer':'TEST ONLY','decision_url':'https://example.org/review',
                               'evidence_path':'input/review.txt','evidence_sha256':self.sha(b'TEST ONLY reviewer evidence')}}
        self.raw=(canonical(self.row())+'\n').encode();self.write(self.raw)
        self.db=self.root/'checkpoint.sqlite'

    @staticmethod
    def sha(raw):return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def row():
        return {'lang_code':'de','word':'Testwort','pos':'noun','tags':['neuter'],
                'senses':[{'glosses':['TEST first']},{'glosses':['TEST second']}]}

    def ledger(self,sources=None):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'schema_version':'1.0.0','sources':[self.source] if sources is None else sources}))

    def write(self,raw,compressed=False):
        name='input/data.jsonl.gz' if compressed else 'input/data.jsonl'
        self.source['retrieval']['artifact_path']=name
        self.source['retrieval']['sha256']=self.sha(raw)
        (self.root/name).write_bytes(raw);self.ledger()

    def snapshot(self,**kwargs):return snapshot(self.root,'test.synthetic','de',**kwargs)

    def run_worker(self,desc=None,**kwargs):
        return process(self.root,desc or self.snapshot(),self.db,**kwargs)

    def test_empty_live_ledger_blocked_no_checkpoint(self):
        with self.assertRaisesRegex(Blocked,'BLOCKED_SOURCE'):snapshot(ROOT,'test.synthetic','de')
        self.ledger([])
        with self.assertRaises(Blocked):self.run_worker()
        self.assertFalse(self.db.exists())

    def test_proof_and_source_mismatch(self):
        for path in ['input/license.txt','input/review.txt','input/data.jsonl']:
            old=(self.root/path).read_bytes();(self.root/path).write_bytes(old+b'changed')
            with self.subTest(path=path),self.assertRaises(Blocked):self.snapshot()
            (self.root/path).write_bytes(old)
        del self.source['review']['evidence_sha256'];self.ledger()
        with self.assertRaises(Blocked):self.snapshot()

    def test_snapshot_identity_pins_contract_license_registry(self):
        desc=self.snapshot();self.assertEqual(desc['status'],'VERIFIED_IMMUTABLE')
        wrong=dict(desc,source_sha256='f'*64)
        with self.assertRaises(Blocked):self.run_worker(wrong)
        self.assertFalse(self.db.exists())

    def test_gzip_truncation_and_expansion_limit(self):
        compressed=gzip.compress(self.raw,mtime=0)
        self.write(compressed,True)
        result=self.run_worker();self.assertEqual(result['accepted_lexemes'],1)
        for raw in [compressed[:-4],compressed[:-12]]:
            self.write(raw,True)
            with self.assertRaises(Blocked):self.snapshot()
        self.write(compressed,True)
        with self.assertRaisesRegex(Blocked,'EXPANSION'):self.snapshot(max_expanded=5)

    def test_resume_and_duplicate_evidence(self):
        self.write(self.raw*3)
        desc=self.snapshot()
        a=self.run_worker(desc,limit=1);self.assertFalse(a['complete'])
        b=self.run_worker(desc,limit=2);self.assertTrue(b['complete'])
        self.assertEqual((b['accepted_lexemes'],b['accepted_senses'],b['duplicates']),(1,2,2))
        c=self.run_worker(desc);self.assertEqual(b,c)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],3)

    def test_invalid_records_exact_counts(self):
        bad=[b'{bad}\n',b'{"word":"one","word":"two"}\n',b'\xff\n',b'[]\n',
             (canonical(dict(self.row(),word='اختبار'))+'\n').encode(),
             (canonical(dict(self.row(),license_id='CC-BY-NC-4.0'))+'\n').encode(),
             b'x'*(1024*1024+12)+b'\n']
        self.write(self.raw+b''.join(bad))
        out=self.run_worker()
        self.assertEqual((out['input_rows'],out['rejected_records'],out['accepted_lexemes']),(8,7,1))

    def test_conflict_atomic_rollback(self):
        conflict=self.row();conflict['tags']=['feminine'];conflict['senses']=[{'glosses':['TEST conflict must rollback']}]
        conflict['forms']=[{'form':'Testconflict','tags':['plural']}]
        self.write(self.raw+(canonical(conflict)+'\n').encode())
        out=self.run_worker();self.assertEqual(out['rejected_records'],1)
        self.assertEqual(out['accepted_senses'],2)
        with sqlite3.connect(self.db) as db:
            self.assertNotIn('feminine',db.execute('SELECT payload FROM lexemes').fetchone()[0])
            self.assertEqual(db.execute('SELECT code FROM errors').fetchone()[0],'CONFLICTING_MORPHOLOGY')

    def test_export_atomic_new_directory_and_exact_sha(self):
        self.run_worker();out=self.root/'out';receipt=export(self.db,out)
        self.assertEqual(receipt['status'],'LEXICAL_REVIEW_REQUIRED')
        self.assertEqual(receipt['files']['lexical.jsonl'],self.sha((out/'lexical.jsonl').read_bytes()))
        self.assertEqual(receipt['accepted_senses'],2)
        with self.assertRaises(Blocked):export(self.db,out)

    def test_disjoint_partitions_aggregate_exact_rows(self):
        rows=[dict(self.row(),word='Test'+str(i)) for i in range(40)]
        self.write(('\n'.join(map(canonical,rows))+'\n').encode());desc=self.snapshot()
        results=[process(self.root,desc,self.root/f'{i}.sqlite',shard=i,shards=3) for i in range(3)]
        self.assertEqual(sum(r['accepted_lexemes'] for r in results),40)
        self.assertEqual(sum(r['owned_rows'] for r in results),40)

    def test_crash_rolls_back_uncommitted_batch(self):
        self.write(self.raw*4);desc=self.snapshot()
        def crash(n):
            if n==2:raise RuntimeError('TEST crash')
        with self.assertRaises(RuntimeError):self.run_worker(desc,batch_size=4,after_row=crash)
        out=self.run_worker(desc)
        self.assertEqual((out['input_rows'],out['accepted_lexemes'],out['duplicates']),(4,1,3))

    def test_large_synthetic_stream_memory_is_bounded(self):
        # Repeated test record isolates streaming/checkpoint overhead from unique output storage.
        path=self.root/'input/data.jsonl'
        with path.open('wb') as stream:
            for _ in range(15000):stream.write(self.raw)
        self.source['retrieval']['sha256']=self.sha(path.read_bytes());self.ledger()
        tracemalloc.start()
        try:
            result=self.run_worker();_,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertEqual(result['input_rows'],15000)
        self.assertLess(peak,24*1024*1024)

    def test_duplicate_attested_forms_keep_all_row_evidence(self):
        r=self.row();r['forms']=[{'form':'Testformen','tags':['plural']}]
        r['sounds']=[{'ipa':'/test/'}]
        raw=(canonical(r)+'\n').encode();self.write(raw*3)
        out=self.run_worker();self.assertEqual(out['duplicates'],2)
        with sqlite3.connect(self.db) as db:
            lex=json.loads(db.execute('SELECT payload FROM lexemes').fetchone()[0])
            self.assertEqual(len(lex['morphology']['inflections']),1)
            self.assertEqual(len(lex['pronunciations']),1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],3)

    def test_nonfinite_and_oversized_integer_rejected_without_abort(self):
        self.write(self.raw+b'{"x":1e400}\n'+b'{"x":'+b'9'*5000+b'}\n')
        out=self.run_worker();self.assertEqual(out['rejected_records'],2)

    def test_conflicting_records_owned_by_nonzero_shard(self):
        from tools.gha_factory.content_ingestion.normalize import extract,partition
        registry=json.loads((self.root/'catalog/language_registry.v1.json').read_text())
        r=self.row()
        for i in range(50):
            r['word']='Test'+str(i)
            if partition(extract(r,self.source,registry,'de','line:1')['lexeme']['lexeme_id'],3)==1:break
        bad=copy.deepcopy(r);bad['tags']=['feminine']
        self.write((canonical(r)+'\n'+canonical(bad)+'\n').encode());desc=self.snapshot()
        results=[process(self.root,desc,self.root/f'{i}.sqlite',shard=i,shards=3) for i in range(3)]
        self.assertEqual(sum(x['rejected_records'] for x in results),1)
        self.assertEqual(results[1]['rejected_records'],1)

    def test_empty_artifact_is_rejected(self):
        self.write(b'')
        with self.assertRaisesRegex(Blocked, 'empty'):
            self.snapshot()
        self.assertFalse(self.db.exists())

    def test_replacement_after_validation_is_not_verified(self):
        import unittest.mock
        import tools.gha_factory.admission.pipeline as pipeline
        artifact = self.root / 'input/data.jsonl'
        original = pipeline.checked_file

        def swapped(root, relative, expected, label):
            found = original(root, relative, expected, label)
            if label == 'source':
                artifact.write_bytes((canonical(dict(self.row(), word='Evilwort')) + '\n').encode())
            return found

        with unittest.mock.patch.object(pipeline, 'checked_file', swapped):
            with self.assertRaises(Blocked):
                self.snapshot()

    def test_in_place_rewrite_is_not_committed(self):
        desc = self.snapshot()
        artifact = self.root / 'input/data.jsonl'

        def rewrite(_processed):
            data = bytearray(artifact.read_bytes())
            data[0] ^= 1
            with artifact.open('r+b') as handle:
                handle.write(data)

        with self.assertRaises(Blocked):
            self.run_worker(desc, batch_size=1, after_row=rewrite)
        if self.db.exists():
            with sqlite3.connect(self.db) as db:
                self.assertIsNone(db.execute('SELECT payload FROM lexemes').fetchone())

    def test_export_route06_and_route07_fixture_projection(self):
        import subprocess
        import sys
        from standards.lexical.validate import validate
        self.run_worker();out=self.root/'out';export(self.db,out)
        for i,line in enumerate((out/'lexical.jsonl').read_text().splitlines()):
            doc=json.loads(line);validate(doc)
            path=self.root/f'fragment-{i}.json';path.write_text(line)
            database=self.root/f'projection-{i}.sqlite'
            proc=subprocess.run([sys.executable,str(ROOT/'standards/lexical/sqlite_v2.py'),str(path),str(database)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
