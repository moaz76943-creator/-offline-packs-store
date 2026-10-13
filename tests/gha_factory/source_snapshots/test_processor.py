"""Synthetic-only source snapshot contract tests: never fetch real corpora."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.gha_factory.source_snapshots import processor as p

def h(b):return hashlib.sha256(b).hexdigest()

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'catalog').mkdir()
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'proof.txt').write_bytes(b'rights fixture')
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({
            'schema_version':'1.0.0','languages':[{'id':'de','default_script':'Latn'}]}))
        self.data=(b'{"lang_code":"de","word":"Baum"}\n'
                   b'{"lang_code":"de","word":"Brot"}\n'
                   b'{malformed\n'
                   b'{"lang_code":"de","word":"Apfel"}\n')
        self.zip=gzip.compress(self.data,mtime=0)
        self.src={'source_id':'synthetic-only','kind':'dictionary','status':'APPROVED_FOR_REDISTRIBUTION',
            'dataset_version':'test','publisher':'synthetic','origin_url':'https://fixtures.example.test/origin',
            'retrieval':{'identity':'test','url':'https://fixtures.example.test/snapshot.gz',
                'date':'2026-01-01','sha256':h(self.zip),'artifact_path':'not-committed/snapshot.gz'},
            'license':{'id':'CC0-1.0','evidence_url':'https://fixtures.example.test/rights',
                'evidence_path':'proof.txt','evidence_sha256':h(b'rights fixture')},
            'review':{'reviewer':'test-only','decision_url':'https://fixtures.example.test/decision'},
            'alterations':['none']}
        self.save()
    def save(self):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'schema_version':'1.0.0','sources':[self.src]}))
    def job(self):return p.approved(self.root,'synthetic-only','de','test')
    def test_rights_fail_closed(self):
        self.src['status']='REVIEW_REQUIRED';self.save()
        with self.assertRaises(p.Blocked):self.job()
        self.src['status']='APPROVED_FOR_REDISTRIBUTION'
        self.src['license']['evidence_sha256']='0'*64;self.save()
        with self.assertRaises(p.Blocked):self.job()
    def test_https_and_redirect_preconditions(self):
        for url in ['http://fixtures.example.test/x','https://127.0.0.1/x',
                    'https://fixtures.example.test.evil.org/x','https://user@fixtures.example.test/x',
                    'https://fixtures.example.test:8080/x']:
            with self.assertRaises(p.Blocked):p.reviewed_url(url,'fixtures.example.test')
    def test_complete_hash_and_deterministic_partition(self):
        source=self.job()
        f=self.root/'data.gz';f.write_bytes(self.zip)
        out=self.root/'output'
        report=p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2)
        self.assertEqual((report['real_input_rows'],report['accepted_rows'],report['rejected_rows']),(4,3,1))
        self.assertEqual(len(report['partitions']),2)
        self.assertEqual(p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2),report)
        (out/'part-00000000.jsonl').write_text('corruption')
        with self.assertRaises(p.Blocked):p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2)
    def test_incomplete_or_corrupt_source_and_abandoned_stage(self):
        source=self.job()
        f=self.root/'data.gz';f.write_bytes(b'partial')
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',len(self.zip),fmt='jsonl.gz')
        f.write_bytes(self.zip)
        (self.root/'out').mkdir()
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',len(self.zip),fmt='jsonl.gz')
    def test_empty_corpus_not_ready(self):
        source=self.job();source['source_sha256']=h(b'')
        f=self.root/'empty';f.write_bytes(b'')
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',0)

if __name__=='__main__':unittest.main()
