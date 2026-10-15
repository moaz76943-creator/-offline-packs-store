import importlib.util,json,unittest
from pathlib import Path
from datetime import datetime,timezone
P=Path(__file__).resolve().parents[3]/'tools/gha_factory/health/check.py'
spec=importlib.util.spec_from_file_location('h',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
NOW=datetime(2026,10,14,12,tzinfo=timezone.utc)
def issue(**kw):
    task={'schema_version':'1.0','task_id':'a'*64,'state':'RUNNING','run_id':5,'run_attempt':2,'lease_until':'2026-10-14T10:00:00Z','attempts':1}
    task.update(kw)
    return {'number':12,'title':'[GHA-TASK] '+task['task_id'],'user':{'login':'moaz76943-creator'},'body':'```gha-task-v1\n'+json.dumps(task)+'\n```'}
class Health(unittest.TestCase):
    def test_expired_unknown_run_requires_review_not_lost(self):
        a=m.assess([issue()],[],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'EXPIRED_LEASE_RUN_UNKNOWN')
    def test_active_run_not_misdiagnosed_as_dead(self):
        a=m.assess([issue()],[{'id':5,'run_attempt':2,'status':'in_progress'}],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'EXPIRED_LEASE_RUN_ACTIVE')
    def test_completed_run_requires_receipt_review(self):
        a=m.assess([issue()],[{'id':5,'run_attempt':2,'status':'completed'}],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'EXPIRED_LEASE_RUN_COMPLETED')
    def test_unexpired_lease_no_alarm(self):
        self.assertFalse(m.assess([issue(lease_until='2026-10-15T13:00:00Z')],[],NOW)['alerts'])
    def test_invalid_identity_quarantined_in_report(self):
        a=m.assess([issue(task_id='z'*64)],[],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'INVALID_TASK_EVIDENCE')
    def test_duplicate_task_detected(self):
        x=issue(state='READY',lease_until=None)
        a=m.assess([x,{**x,'number':13}],[],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'DUPLICATE_TASK_ID')
    def test_non_owner_ignored(self):
        a=m.assess([{**issue(),'user':{'login':'unknown'}}],[],NOW)
        self.assertEqual(a['queue_issues'],0)
    def test_non_queue_issue_ignored(self):
        a=m.assess([{'number':44,'title':'Other','user':{'login':'moaz76943-creator'}}],[],NOW)
        self.assertEqual(a['queue_issues'],0)
    def test_bounded_page(self):
        with self.assertRaises(ValueError):m.assess([issue()]*601,[],NOW)
    def test_malformed_non_object_issue_does_not_crash_report(self):
        result=m.assess([None, [], issue(state='READY',lease_until=None)],[],NOW)
        self.assertEqual(result['queue_issues'],1)
        self.assertEqual(result['status'],'OBSERVED_ONLY')
        self.assertEqual(len(result['alerts']),0)

    def test_retries(self):
        a=m.assess([issue(state='RETRY_WAIT',lease_until=None,attempts=3)],[],NOW)
        self.assertEqual(a['alerts'][0]['reason'],'RETRY_LIMIT_INSPECT')
if __name__=='__main__':unittest.main()
