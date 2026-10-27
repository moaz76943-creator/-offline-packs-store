"""Real dispatcher regressions; run directly against baseline or staged patch."""
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests/gha_factory/dispatcher'))
from tools.gha_factory.dispatcher import queue,controller,worker
from test_queue import task,NOW
from test_controller import Tests,FakeGitHub

class Lifecycle(Tests):
    def active(self,**kw):
        return task(source_sha256=self.sha,state='CLAIMED',attempts=1,run_id=11,run_attempt=1,lease_until=queue.iso(NOW-timedelta(minutes=31)),**kw)
    def test_live_expired_run_keeps_slot(self):
        a=self.active();api=FakeGitHub([self.issue(1,a)])
        api.run=lambda _:{'id':11,'run_attempt':1,'status':'in_progress'}
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(1)['body']),a)
    def test_unknown_run_keeps_slot(self):
        a=self.active();api=FakeGitHub([self.issue(1,a)])
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(1)['body']),a)
    def test_foreign_or_newer_attempt_cannot_release_claim(self):
        for record in ({'id':12,'run_attempt':1,'status':'completed'},{'id':11,'run_attempt':2,'status':'completed'}):
            a=self.active();api=FakeGitHub([self.issue(1,a)])
            api.run=lambda _,r=record:r
            self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
            self.assertEqual(queue.parse(api.one(1)['body']),a)
    def test_terminal_crash_recovers_checkpoint_once(self):
        a=self.active(checkpoint=1);api=FakeGitHub([self.issue(1,a)])
        api.run=lambda _:{'id':11,'run_attempt':1,'status':'completed'}
        self.assertEqual(len(controller.controller(api,22,1,NOW,self.root)),1)
        t=queue.parse(api.one(1)['body'])
        self.assertEqual((t['checkpoint'],t['attempts'],t['run_id']),(1,2,22))
        self.assertEqual(controller.controller(api,23,1,NOW,self.root),[])
    def test_exhausted_ready_does_not_crash_or_claim(self):
        api=FakeGitHub([self.issue(1,task(source_sha256=self.sha,attempts=3))])
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(1)['body'])['state'],'FAILED')
    def test_active_duplicate_outweighs_older_ready(self):
        a=self.active();b=dict(a,state='READY',attempts=0,lease_until=None,run_id=None,run_attempt=None)
        api=FakeGitHub([self.issue(1,b),self.issue(2,a)])
        api.run=lambda _:{'id':11,'run_attempt':1,'status':'in_progress'}
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(2)['body']),a)
        self.assertEqual(queue.parse(api.one(1)['body'])['state'],'QUARANTINED')
    def test_duplicate_live_runs_all_count_toward_capacity(self):
        a=self.active();b=dict(a,run_id=12);c=self.active(language='en');d=task(source_sha256=self.sha,language='fr')
        api=FakeGitHub([self.issue(1,a),self.issue(2,b),self.issue(3,c),self.issue(4,d)])
        api.run=lambda n:{'id':n,'run_attempt':1,'status':'in_progress'}
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(2)['body']),b)
    def test_completed_duplicate_releases_slot_without_reprocessing(self):
        a=self.active();b=dict(a,run_id=12);api=FakeGitHub([self.issue(1,a),self.issue(2,b)])
        api.run=lambda n:{'id':n,'run_attempt':1,'status':'completed' if n==12 else 'in_progress'}
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(2)['body'])['state'],'QUARANTINED')
    def test_succeeded_identity_survives_duplicate(self):
        a=task(source_sha256=self.sha,state='SUCCEEDED',attempts=1,checkpoint=1)
        api=FakeGitHub([self.issue(1,task(source_sha256=self.sha)),self.issue(2,a)])
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(2)['body']),a)
    def test_independent_parallel_slots_and_source_locks(self):
        items=[self.issue(1,self.active())]+[self.issue(n,task(source_sha256=self.sha,language=l)) for n,l in ((2,'en'),(3,'fr'),(4,'ar'))]
        api=FakeGitHub(items);api.run=lambda _:{'id':11,'run_attempt':1,'status':'in_progress'}
        self.assertEqual([j['number'] for j in controller.controller(api,22,1,NOW,self.root)],[2,3])
        self.assertEqual(controller.controller(api,23,1,NOW,self.root),[])
    def test_renewal_is_fenced_and_hard_bounded(self):
        a=self.active();a['lease_until']=queue.iso(NOW+timedelta(minutes=1));until=NOW+timedelta(minutes=5)
        t=queue.renew(a,NOW,11,1,until)
        self.assertEqual(t['lease_until'],queue.iso(until));self.assertEqual(t['checkpoint'],a['checkpoint'])
        for rid,attempt,now in ((12,1,NOW),(11,2,NOW),(11,1,NOW+timedelta(minutes=1))):
            with self.assertRaises(ValueError):queue.renew(a,now,rid,attempt,until)
    def test_expired_worker_never_executes(self):
        a=self.active();api=FakeGitHub([self.issue(1,a)])
        with patch.object(queue,'utc_now',return_value=NOW),patch.object(worker,'work') as execute:
            with self.assertRaises(ValueError):worker.worker(api,1,a['task_id'],11,1,self.root/'out',self.root)
            execute.assert_not_called()
    def test_spawned_real_worker_times_out(self):
        a=task(source_sha256=self.sha)
        self.assertEqual(worker.bounded_work(a,self.root,self.root,timeout=0.000001),('FAILED',0,0,None,'TIMEOUT'))
    def test_spawned_real_registry_verification(self):
        (self.root/'catalog/validate_registry.py').write_text('raise SystemExit(0)\n')
        a=task(source_sha256=self.sha)
        self.assertEqual(worker.bounded_work(a,self.root,self.root),('SUCCEEDED',1,0,None,None))
    def test_frozen_real_subprocess_is_stopped(self):
        (self.root/'catalog/validate_registry.py').write_text(
            "import os,time,pathlib\npathlib.Path('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n")
        a=task(source_sha256=self.sha)
        self.assertEqual(worker.bounded_work(a,self.root,self.root,timeout=0.5),('FAILED',0,0,None,'TIMEOUT'))
        pidfile=self.root/'child.pid'
        self.assertTrue(pidfile.is_file(),'actual frozen subprocess must have started')
        status=Path('/proc')/pidfile.read_text()/'stat'
        try:
            state=status.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError, OSError):
            pass
        else:
            self.assertIn(state,('Z','X'))
    def test_attempt_limit_after_interruption(self):
        a=self.active();a['attempts']=3
        api=FakeGitHub([self.issue(1,a)])
        api.run=lambda _:{'id':11,'run_attempt':1,'status':'completed'}
        self.assertEqual(controller.controller(api,22,1,NOW,self.root),[])
        self.assertEqual(queue.parse(api.one(1)['body'])['state'],'FAILED')
    def test_old_receipt_after_resume_is_rejected(self):
        a=self.active(checkpoint=1)
        api=FakeGitHub([self.issue(1,a)])
        api.run=lambda _:{'id':11,'run_attempt':1,'status':'completed'}
        controller.controller(api,22,1,NOW,self.root)
        current=queue.parse(api.one(1)['body'])
        receipt={'schema_version':'1.0','task_id':a['task_id'],'run_id':11,'run_attempt':1,
                 'status':'SUCCEEDED','checkpoint':1,'candidate_count':0,'candidate_sha256':None,'error_code':None}
        with self.assertRaises(ValueError):queue.finalize(current,receipt,NOW)
        self.assertEqual(queue.parse(api.one(1)['body']),current)
    def test_suspicious_issue_is_not_executed(self):
        issue=self.issue(1,task(source_sha256=self.sha));issue['body']+='\n$(touch /tmp/not-executed)'
        api=FakeGitHub([issue]);self.assertEqual(controller.controller(api,22,1,NOW,self.root),[]);self.assertEqual(api.writes,[])

if __name__=='__main__':unittest.main(defaultTest='Lifecycle',verbosity=2)
