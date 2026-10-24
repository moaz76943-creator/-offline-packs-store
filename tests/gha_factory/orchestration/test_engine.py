import copy
import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from test_protocol import NOW, task
from tools.gha_factory.dispatcher import queue
from tools.gha_factory.orchestration import protocol as p, engine as e

class FakeAPI:
    def __init__(self,tasks):
        self.data={n:{'number':n,'title':p.PREFIX+t['task_id'],'body':p.serialize(t),'user':{'login':e.OWNER}} for n,t in tasks}
        self.runs={};self.writes=[];self.created=[]
    def issues(self):return list(self.data.values())
    def one(self,n):return self.data[n]
    def update(self,n,t):self.data[n]['body']=p.serialize(t);self.writes.append((n,copy.deepcopy(t)))
    def run(self,n):return self.runs.get(n,{'id':n,'run_attempt':1,'status':'in_progress','head_branch':'main','path':e.WORKFLOW})
    def create(self,t):
        n=max(self.data,default=0)+1
        self.data[n]={'number':n,'title':p.PREFIX+t['task_id'],'body':p.serialize(t),'user':{'login':'github-actions[bot]'}}
        self.created.append(n);return n

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.ctx={'languages':{'de','en','fr','ar'},'sources':[],'admissions':{}}
        self.sha='a'*64
        self.gate=patch.object(e,'source_gate',return_value='READY');self.gate.start();self.addCleanup(self.gate.stop)
    def run_controller(self,api,rid=1):return e.control(api,rid,1,NOW,Path('.'),self.ctx,self.sha)
    def test_malformed_owned_issue_does_not_stop_other_jobs(self):
        # A single corrupted owner-created issue must not halt the hourly queue.
        # The invalid issue is left untouched for manual correction; a separate
        # valid task must still be claimable.
        api=FakeAPI([(1,task()),(2,task(language='en'))])
        bad_body=p.MARKER+'[]\\n\x60\x60\x60'
        api.data[1]['body']=bad_body
        jobs=self.run_controller(api)
        self.assertEqual([job['number'] for job in jobs],[2])
        self.assertEqual(api.one(1)['body'],bad_body)
        self.assertEqual(p.parse(api.one(2)['body'])['state'],'CLAIMED')

    def test_mismatched_owned_issue_title_does_not_stop_other_jobs(self):
        api=FakeAPI([(1,task()),(2,task(language='en'))])
        api.data[1]['title']=p.PREFIX+'0'*64
        jobs=self.run_controller(api)
        self.assertEqual([job['number'] for job in jobs],[2])
        self.assertEqual(p.parse(api.one(2)['body'])['state'],'CLAIMED')

    def test_mismatched_active_title_retains_source_lock_and_lease(self):
        running=p.claim(task(state='READY'),NOW,10,1)
        api=FakeAPI([(1,running),(2,task(shard=1)),(3,task(language='en'))])
        api.data[1]['title']=p.PREFIX+'0'*64
        original=api.one(1)['body']
        jobs=self.run_controller(api,11)
        self.assertEqual([j['number'] for j in jobs],[3])
        self.assertEqual(api.one(1)['body'],original)
        self.assertEqual(p.parse(api.one(2)['body'])['state'],'NEW')
        self.assertEqual(p.parse(api.one(3)['body'])['state'],'CLAIMED')

    def test_three_mismatched_active_titles_exhaust_global_capacity(self):
        running=[(i,p.claim(task(language=lang,state='READY'),NOW,10+i,1))
                 for i,lang in enumerate(('de','en','fr'),1)]
        api=FakeAPI(running+[(4,task(language='ar'))])
        bodies={i:api.one(i)['body'] for i in (1,2,3)}
        for i in (1,2,3):
            api.data[i]['title']=p.PREFIX+'0'*64
        self.assertEqual(self.run_controller(api,20),[])
        self.assertEqual({i:api.one(i)['body'] for i in (1,2,3)},bodies)
        self.assertEqual(p.parse(api.one(4)['body'])['state'],'NEW')

    def test_three_global_capacity(self):
        api=FakeAPI([(i,task(language=l)) for i,l in enumerate(('de','en','fr','ar'),1)])
        jobs=self.run_controller(api)
        self.assertEqual(len(jobs),3)
        self.assertEqual(self.run_controller(api,2),[])
    def test_independent_work_while_old_worker_runs(self):
        old=p.claim(task(language='de',state='READY'),NOW,10,1)
        api=FakeAPI([(1,old),(2,task(language='en'))])
        self.assertEqual([j['number'] for j in self.run_controller(api,11)],[2])
    def test_source_language_lock(self):
        api=FakeAPI([(1,task()),(2,task(shard=1))])
        self.assertEqual(len(self.run_controller(api)),1)
    def test_stale_live_run_keeps_slot_and_lock(self):
        old=p.claim(task(state='READY'),NOW-timedelta(hours=7),10,1)
        api=FakeAPI([(1,old),(2,task(shard=1))])
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
    def test_cancelled_expired_run_recovers_with_backoff(self):
        old=p.claim(task(state='READY'),NOW-timedelta(hours=7),10,1)
        api=FakeAPI([(1,old)])
        api.runs[10]={'id':10,'run_attempt':1,'status':'completed','head_branch':'main','path':e.WORKFLOW,'conclusion':'cancelled'}
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'RETRY_WAIT')
    def test_wrong_run_attempt_never_recovers(self):
        old=p.claim(task(state='READY'),NOW-timedelta(hours=7),10,1)
        api=FakeAPI([(1,old)]);api.runs[10]=dict(api.run(10),run_attempt=2,status='completed')
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
    def test_untrusted_and_bot_ownership(self):
        api=FakeAPI([(1,task()),(2,task(language='en'))])
        api.data[1]['user']['login']='stranger';api.data[2]['user']['login']='github-actions[bot]'
        self.assertEqual([j['number'] for j in self.run_controller(api)],[2])
    def test_duplicate_issues_and_closed_success_preserved(self):
        a=p.claim(task(state='READY'),NOW,20,1)
        a=p.finish(a,p.receipt(a,'SUCCEEDED',1,0,None,None),NOW)
        api=FakeAPI([(1,task()),(2,a)])
        api.data[2]['state']='closed';before=api.one(2)['body']
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(api.one(2)['body'],before)
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'QUARANTINED')
    def test_source_id_collision_v1_preserves_receipts(self):
        a=task();a.pop('dependencies');a.update(schema_version='1.0',contract_version='1.0.0',task_type='admission_partition_verify')
        a['task_id']=queue.fingerprint(a);b=dict(a,source_id='another')
        api=FakeAPI([(1,a),(2,b)])
        self.assertEqual(self.run_controller(api),[])
        self.assertTrue(all(p.parse(x['body'])['state']=='QUARANTINED' for x in api.data.values()))
    def test_dependencies_missing_blocked(self):
        api=FakeAPI([(1,task(dependencies=['b'*64]))])
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'BLOCKED_DEPENDENCY')
    def test_unintegrated_workers_blocked(self):
        for kind in p.TYPES-p.EXECUTABLE:
            api=FakeAPI([(1,task(task_type=kind))]);self.assertEqual(self.run_controller(api),[])
            self.assertEqual(p.parse(api.one(1)['body'])['state'],'BLOCKED_DEPENDENCY')
    def test_retry_limit_no_fourth_attempt(self):
        api=FakeAPI([(1,task(state='READY',attempts=3))]);self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'FAILED')
    def test_reread_rejects_interleaved_claim(self):
        api=FakeAPI([(1,task())]);original=api.one
        def changed(n):
            x=copy.deepcopy(original(n));x['body']=p.serialize(p.claim(p.parse(x['body']),NOW,999,1));return x
        api.one=changed
        self.assertEqual(self.run_controller(api),[])
    def test_700_tasks_fair_order(self):
        api=FakeAPI([(i,task(shard=i,language=['de','en','fr','ar'][i%4])) for i in range(1,701)])
        visited=set()
        for hour in range(700):
            jobs=e.control(api,hour+1,1,NOW+timedelta(hours=hour),Path('.'),self.ctx,self.sha)
            numbers=[j['number'] for j in jobs]
            self.assertEqual(numbers,sorted(numbers))
            self.assertLessEqual(len(numbers),3)
            for n in numbers:
                t=p.parse(api.one(n)['body'])
                done=p.finish(t,p.receipt(t,'SUCCEEDED',1,0,None,None),NOW+timedelta(hours=hour))
                api.update(n,done);visited.add(n)
            if len(visited)==700:break
        self.assertEqual(len(visited),700)
    def test_finalizer_missing_receipt_does_not_report_success(self):
        api=FakeAPI([(1,task())]);jobs=self.run_controller(api)
        with tempfile.TemporaryDirectory() as d:
            result=e.finalize(api,jobs,Path(d),1,1,NOW)
        self.assertEqual(result[0]['state'],'RETRY_WAIT')
    def test_failed_finalization_preserves_claim(self):
        api=FakeAPI([(1,task())]);jobs=self.run_controller(api)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'dispatcher-1';folder.mkdir();(folder/'receipt.json').write_text('{}')
            with self.assertRaises(ValueError):e.finalize(api,jobs,Path(d),1,1,NOW)
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
    def test_invalid_receipt_does_not_strand_independent_valid_completion(self):
        api=FakeAPI([(1,task()),(2,task(language='en'))])
        jobs=self.run_controller(api)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            broken=folder/'dispatcher-1';broken.mkdir()
            (broken/'receipt.json').write_text('{}')
            valid=folder/'dispatcher-2';valid.mkdir()
            t=p.parse(api.one(2)['body'])
            (valid/'receipt.json').write_text(json.dumps(p.receipt(t,'SUCCEEDED',1,0,None,None)))
            with self.assertRaises(ValueError):
                e.finalize(api,jobs,folder,1,1,NOW)
            self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
            self.assertEqual(p.parse(api.one(2)['body'])['state'],'SUCCEEDED')
            # Finalization retry after interruption is idempotent for task 2.
            with self.assertRaises(ValueError):
                e.finalize(api,jobs,folder,1,1,NOW)
            self.assertEqual(p.parse(api.one(2)['body'])['checkpoint'],1)

    def test_non_object_receipts_cannot_block_independent_finalization(self):
        # JSON syntax is valid here, but the receipt envelope must be an object.
        # Each rejected shard remains claimed; a different valid shard completes.
        for invalid in ('[]', 'null', '"text"', '42', 'true'):
            with self.subTest(invalid=invalid):
                api=FakeAPI([(1,task()),(2,task(language='en'))])
                jobs=self.run_controller(api)
                with tempfile.TemporaryDirectory() as d:
                    folder=Path(d)
                    bad=folder/'dispatcher-1';bad.mkdir()
                    (bad/'receipt.json').write_text(invalid)
                    good=folder/'dispatcher-2';good.mkdir()
                    t=p.parse(api.one(2)['body'])
                    (good/'receipt.json').write_text(json.dumps(p.receipt(t,'SUCCEEDED',1,0,None,None)))
                    with self.assertRaises(e.FinalizationError) as raised:
                        e.finalize(api,jobs,folder,1,1,NOW)
                    self.assertEqual(raised.exception.errors[0]['issue'],1)
                    self.assertEqual(raised.exception.errors[0]['category'],'ValueError')
                    self.assertEqual(len(raised.exception.results),1)
                    self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
                    self.assertEqual(p.parse(api.one(2)['body'])['state'],'SUCCEEDED')

    def test_non_object_task_metadata_isolates_independent_finalization(self):
        api=FakeAPI([(1,task()),(2,task(language='en'))])
        jobs=self.run_controller(api)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            api.data[1]['body']=p.MARKER+'[]\n```'
            good=folder/'dispatcher-2';good.mkdir()
            t=p.parse(api.one(2)['body'])
            (good/'receipt.json').write_text(json.dumps(p.receipt(t,'SUCCEEDED',1,0,None,None)))
            with self.assertRaises(e.FinalizationError) as raised:
                e.finalize(api,jobs,folder,1,1,NOW)
            self.assertEqual(raised.exception.errors[0]['issue'],1)
            self.assertEqual(raised.exception.errors[0]['category'],'ValueError')
            self.assertEqual(p.parse(api.one(2)['body'])['state'],'SUCCEEDED')
            self.assertEqual(api.one(1)['body'],p.MARKER+'[]\n```')

    def test_finalizer_rejects_symlinked_receipt_directory(self):
        api=FakeAPI([(1,task())]);jobs=self.run_controller(api)
        t=p.parse(api.one(1)['body'])
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as external:
            folder=Path(d);outside=Path(external)
            (outside/'receipt.json').write_text(json.dumps(p.receipt(t,'SUCCEEDED',1,0,None,None)))
            (folder/'dispatcher-1').symlink_to(outside,target_is_directory=True)
            writes=len(api.writes)
            with self.assertRaises(ValueError):e.finalize(api,jobs,folder,1,1,NOW)
            self.assertEqual(len(api.writes),writes)
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
    def test_finalizer_rejects_symlinked_artifact_root(self):
        api=FakeAPI([(1,task())]);jobs=self.run_controller(api)
        t=p.parse(api.one(1)['body'])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);real=root/'real';real.mkdir()
            directory=real/'dispatcher-1';directory.mkdir()
            (directory/'receipt.json').write_text(json.dumps(p.receipt(t,'SUCCEEDED',1,0,None,None)))
            alias=root/'alias';alias.symlink_to(real,target_is_directory=True)
            writes=len(api.writes)
            with self.assertRaises(ValueError):e.finalize(api,jobs,alias,1,1,NOW)
            self.assertEqual(len(api.writes),writes)
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'CLAIMED')
    def test_actual_started_job_marks_running(self):
        t=p.claim(task(state='READY'),NOW,10,1)
        api=FakeAPI([(1,t)])
        api.jobs=lambda run:[{'name':f"worker (1, {t['task_id']})",'status':'in_progress'}]
        self.assertEqual(self.run_controller(api),[])
        self.assertEqual(p.parse(api.one(1)['body'])['state'],'RUNNING')
    def test_empty_ledger_no_seeding(self):
        self.gate.stop()
        api=FakeAPI([])
        self.assertEqual(e.seed(api,self.ctx,self.sha,Path('.')),[])
        self.assertEqual(api.created,[])

if __name__=='__main__':unittest.main()
