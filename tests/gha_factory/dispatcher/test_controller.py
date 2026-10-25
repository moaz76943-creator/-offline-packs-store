import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from tools.gha_factory.dispatcher import queue,controller,worker
from test_queue import task,NOW

class FakeGitHub:
    def __init__(self,items):self.data={x['number']:x for x in items};self.writes=[]
    def issues(self):return list(self.data.values())
    def one(self,number):return self.data[number]
    def update(self,number,t):
        self.data[number]['body']=queue.serialize(t)
        self.writes.append((number,t['state']))

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'catalog').mkdir();(self.root/'legal/ledger').mkdir(parents=True)
        langs=['de','en','fr','ar']+[chr(97+i//26)+chr(97+i%26) for i in range(100) if chr(97+i//26)+chr(97+i%26) not in {'de','en','fr','ar'}][:96]
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({'schema_version':'1.0.0','languages':[{'id':x} for x in langs]}))
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'schema_version':'1.0.0','sources':[]}))
        self.sha=hashlib.sha256((self.root/'catalog/language_registry.v1.json').read_bytes()).hexdigest()
    def issue(self,n,t,owner=controller.OWNER):
        return {'number':n,'title':queue.PREFIX+t['task_id'],'body':queue.serialize(t),'user':{'login':owner}}
    def test_claim_parallel_and_duplicate_safety(self):
        a=task(source_sha256=self.sha,language='de',state='NEW')
        b=task(source_sha256=self.sha,language='en')
        c=task(source_sha256=self.sha,language='fr')
        d=task(source_sha256=self.sha,language='ar')
        api=FakeGitHub([self.issue(1,a),self.issue(2,b),self.issue(3,c),self.issue(4,d),self.issue(5,b)])
        jobs=controller.controller(api,321,1,NOW,self.root)
        self.assertEqual([j['number'] for j in jobs],[1,2,3])
        self.assertEqual(queue.parse(api.one(5)['body'])['state'],'QUARANTINED')
        self.assertEqual(queue.parse(api.one(4)['body'])['state'],'READY')
        self.assertEqual(queue.parse(api.one(1)['body'])['run_id'],321)
        self.assertEqual(controller.controller(api,322,1,NOW,self.root),[])
    def test_missing_source_blocked_and_untrusted_issue_ignored(self):
        a=task(source_sha256=self.sha,task_type='admission_partition_verify',source_id='absent',checkpoint=0)
        b=task(source_sha256=self.sha,language='en')
        api=FakeGitHub([self.issue(1,a),self.issue(2,b,owner='stranger')])
        api.issues=lambda:[x for x in api.data.values() if x['user']['login']==controller.OWNER]
        self.assertEqual(controller.controller(api,40,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(1)['body'])['state'],'BLOCKED_SOURCE')
    def test_complete_receipt_persist_and_replay_rejected(self):
        a=task(source_sha256=self.sha,language='de')
        api=FakeGitHub([self.issue(1,a)])
        jobs=controller.controller(api,123,1,NOW,self.root)
        folder=self.root/'artifacts/dispatcher-1';folder.mkdir(parents=True)
        (folder/'receipt.json').write_text(json.dumps({'schema_version':'1.0','task_id':a['task_id'],'run_id':123,'run_attempt':1,'status':'SUCCEEDED','checkpoint':1,'candidate_count':0,'candidate_sha256':None,'error_code':None}))
        result=controller.finish(api,jobs,self.root/'artifacts',123,1,NOW)
        self.assertEqual(result[0]['state'],'SUCCEEDED')
        self.assertIn((1,'RUNNING'),api.writes)
        with self.assertRaises(ValueError):controller.finish(api,jobs,self.root/'artifacts',123,1,NOW)
    def test_failure_injection_artifact_corruption(self):
        a=task(source_sha256=self.sha)
        api=FakeGitHub([self.issue(1,a)])
        jobs=controller.controller(api,123,1,NOW,self.root)
        folder=self.root/'artifacts/dispatcher-1';folder.mkdir(parents=True)
        (folder/'receipt.json').write_text(json.dumps({'schema_version':'1.0','task_id':a['task_id'],'run_id':123,'run_attempt':1,'status':'SUCCEEDED','checkpoint':1,'candidate_count':1,'candidate_sha256':'f'*64,'error_code':None}))
        (folder/'candidates.jsonl').write_text('tampered')
        with self.assertRaises(ValueError):controller.finish(api,jobs,self.root/'artifacts',123,1,NOW)
        self.assertEqual(queue.parse(api.one(1)['body'])['state'],'CLAIMED')

if __name__=='__main__':unittest.main()
