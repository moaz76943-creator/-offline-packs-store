"""Synthetic evidence only: temporary fixtures never enter the public corpus ledger."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_engine import FakeAPI
from test_protocol import NOW
from tools.gha_factory.admission import pipeline
from tools.gha_factory.dispatcher import controller as legacy
from tools.gha_factory.orchestration import engine as e, protocol as p, api

ROOT=Path(__file__).resolve().parents[3]

def sha(b):return hashlib.sha256(b).hexdigest()

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for x in ('input','catalog','legal/ledger'):(self.root/x).mkdir(parents=True,exist_ok=True)
        shutil.copy(ROOT/'catalog/language_registry.v1.json',self.root/'catalog/language_registry.v1.json')
        self.raw=b'{"lang_code":"de","word":"Haus","pos":"noun","senses":[{"glosses":["home"]}]}\n'
        (self.root/'input/raw.jsonl').write_bytes(self.raw)
        evidence=b'SYNTHETIC TEST ONLY';(self.root/'input/license.txt').write_bytes(evidence)
        self.source={'source_id':'test-fixture','kind':'dictionary','origin_url':'https://example.org/data','publisher':'Fixture',
            'dataset_version':'test-v1','retrieval':{'identity':'fixture-snapshot','url':'https://example.org/raw','date':'2026-10-13','artifact_path':'input/raw.jsonl','sha256':sha(self.raw)},
            'license':{'id':'CC0-1.0','evidence_url':'https://example.org/LICENSE','evidence_path':'input/license.txt','evidence_sha256':sha(evidence)},
            'status':'APPROVED_FOR_REDISTRIBUTION','alterations':['none'],'review':{'reviewer':'fixture','decision_url':'https://example.org/decision'}}
        self.ledger()
        self.out=self.root/'tools/gha_factory/admission/accepted/fixture'
        self.out.parent.mkdir(parents=True)
        pipeline.admit(repo_root=self.root,source_id='test-fixture',input_path=self.root/'input/raw.jsonl',out_dir=self.out,language='de',dataset_version='test-v1',format_name='wiktextract-jsonl',part_size=1)
        self.t=p.new('test-fixture',sha(self.raw),'de','approved_snapshot_verify',0)
    def ledger(self):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'schema_version':'1.0.0','sources':[self.source]}))
    def gate(self):
        ctx,digest=legacy.context(self.root);return e.source_gate(self.t,ctx,digest,self.root)
    def test_actual_byte_verified_fixture_traverses_queue(self):
        ctx,digest=legacy.context(self.root);gh=FakeAPI([])
        self.assertEqual(e.seed(gh,ctx,digest,self.root),[1])
        jobs=e.control(gh,101,1,NOW,self.root)
        directory=self.root/'result/dispatcher-1'
        r=e.execute(gh,1,jobs[0]['task_id'],101,1,directory,self.root,NOW)
        self.assertEqual(r['status'],'SUCCEEDED');self.assertEqual(r['checkpoint'],1)
        self.assertEqual(r['candidate_count'],0)
        self.assertEqual(e.finalize(gh,jobs,directory.parent,101,1,NOW)[0]['state'],'SUCCEEDED')
        gh.data[1]['state']='closed'
        self.assertEqual(e.seed(gh,ctx,digest,self.root),[])
    def test_invalid_source_sha(self):
        (self.root/'input/raw.jsonl').write_bytes(b'tampered');self.assertEqual(self.gate(),'BLOCKED_SOURCE')
    def test_unlicensed_dataset(self):
        self.source['license']['id']='UNLICENSED';self.ledger();self.assertEqual(self.gate(),'BLOCKED_SOURCE')
    def test_missing_snapshot(self):
        (self.root/'input/raw.jsonl').unlink();self.assertEqual(self.gate(),'BLOCKED_SOURCE')
    def test_missing_license_proof(self):
        (self.root/'input/license.txt').unlink();self.assertEqual(self.gate(),'BLOCKED_SOURCE')
    def test_expired_approval(self):
        self.source['review']['expires_at']='2000-01-01';self.ledger();self.assertEqual(self.gate(),'BLOCKED_SOURCE')
    def test_tampered_partition(self):
        (self.out/'partition-00000000.jsonl').write_bytes(b'tamper');self.assertEqual(self.gate(),'QUARANTINED')
    def test_wrong_canonical_language(self):
        self.t=p.new('test-fixture',sha(self.raw),'zz','approved_snapshot_verify',0);self.assertEqual(self.gate(),'QUARANTINED')
    def test_large_snapshot_needs_durable_handoff(self):
        with patch.object(e,'MAX_CONTROLLER_BYTES',1):self.assertEqual(self.gate(),'BLOCKED_DEPENDENCY')
    def test_v1_seed_identity_is_reused(self):
        ctx,digest=legacy.context(self.root)
        t=dict(self.t);t.pop('dependencies');t.update(schema_version='1.0',contract_version='1.0.0',task_type='admission_partition_verify')
        from tools.gha_factory.dispatcher import queue
        t['task_id']=queue.fingerprint(t)
        self.assertEqual(e.seed(FakeAPI([(1,t)]),ctx,digest,self.root),[])
    def test_fixed_api_paths_and_main_write_guard(self):
        gh=api.GitHub('test-token')
        for endpoint in ('/contents/private','/actions/workflows/evil/dispatches','/issues?state=all&per_page=100&page=999','/issues/1?redirect=evil'):
            with self.assertRaises(ValueError):gh.request(endpoint)
        with patch.dict('os.environ',{'GITHUB_REPOSITORY':e.REPO,'GITHUB_REF':'refs/heads/evil'}):
            with self.assertRaises(ValueError):gh.update(1,self.t)

if __name__=='__main__':unittest.main()
