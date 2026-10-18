import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.gha_factory.dispatcher import queue

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
SHA = 'a' * 64


def task(**updates):
    fields = {'schema_version':'1.0','source_sha256':SHA,'source_id':'public-registry',
              'language':'de','task_type':'registry_validate','shard':0,'contract_version':'1.0.0',
              'state':'READY','attempts':0,'next_retry_at':None,'lease_until':None,
              'run_id':None,'run_attempt':None,'checkpoint':0,'receipt':None}
    fields.update(updates)
    fields['task_id'] = queue.fingerprint(fields)
    return fields

class QueueTests(unittest.TestCase):
    def test_deterministic_ids_and_reject_tampering(self):
        a=task(); self.assertEqual(a['task_id'],task()['task_id'])
        self.assertNotEqual(a['task_id'],task(shard=1)['task_id'])
        self.assertEqual(queue.validate(a),a)
        b=copy.deepcopy(a);b['language']='xx'
        with self.assertRaises(ValueError):queue.validate(b,language_ids={'de'})
        b=copy.deepcopy(a);b['task_id']='0'*64
        with self.assertRaises(ValueError):queue.validate(b)
        b=copy.deepcopy(a);b['shell']='curl evil'
        with self.assertRaises(ValueError):queue.validate(b)
    def test_strict_fingerprint_duplicates(self):
        a=task(); b=task()
        self.assertEqual(queue.duplicates([(9,a),(11,b)]),{11})
    def test_source_gate_blocks_unapproved_or_changed(self):
        a=task(task_type='admission_partition_verify',source_id='evidence',source_sha256=SHA)
        self.assertEqual(queue.admission(a,{'languages':['de'],'sources':[]},SHA),'BLOCKED_SOURCE')
        self.assertEqual(queue.admission(task(source_sha256=SHA),{'languages':['de'],'sources':[]},'b'*64),'QUARANTINED')
    def test_three_slots_and_per_source_language_locks(self):
        xs=[(i,task(shard=i,source_id='s',task_type='admission_partition_verify')) for i in range(5)]
        xs += [(10,task(language='en',source_id='public-registry'))]
        self.assertEqual([i for i,_ in queue.choose(xs,set(),3)],[0,10])
        self.assertEqual(queue.choose(xs,{('s','de')},3)[0][0],10)
    def test_crash_lease_then_retry_twice_only(self):
        a=task(state='RUNNING',attempts=1,lease_until='2026-10-12T23:59:00Z',run_id=123,run_attempt=1)
        b=queue.recover(a,NOW)
        self.assertEqual(b['state'],'RETRY_WAIT')
        self.assertEqual(b['attempts'],1)
        self.assertEqual(b['next_retry_at'],'2026-10-13T00:29:00Z')
        b['attempts']=3;b['state']='RUNNING';b['lease_until']='2026-10-12T23:59:00Z'
        self.assertEqual(queue.recover(b,NOW)['state'],'FAILED')
    def test_safely_reject_old_or_duplicate_receipt(self):
        a=task(state='RUNNING',attempts=1,run_id=111,run_attempt=2,lease_until='2026-10-14T00:00:00Z')
        good={'schema_version':'1.0','task_id':a['task_id'],'run_id':111,'run_attempt':2,
              'status':'SUCCEEDED','checkpoint':1,'candidate_count':0,
              'candidate_sha256':None,'error_code':None}
        self.assertEqual(queue.finalize(a,good,NOW)['state'],'SUCCEEDED')
        old=dict(good,run_id=110)
        with self.assertRaises(ValueError):queue.finalize(a,old,NOW)
        with self.assertRaises(ValueError):queue.finalize(a,dict(good,checkpoint=-1),NOW)
    def test_failure_injection_missing_receipt_and_backoff(self):
        a=task(state='RUNNING',attempts=2,run_id=91,run_attempt=1,lease_until='2026-10-14T00:00:00Z')
        failed=queue.finalize(a,None,NOW)
        self.assertEqual(failed['state'],'RETRY_WAIT')
        self.assertEqual(failed['next_retry_at'],'2026-10-13T01:00:00Z')
        failed['attempts']=3;failed['state']='RUNNING'
        self.assertEqual(queue.finalize(failed,None,NOW)['state'],'FAILED')
    def test_envelope_rejects_extra_text_and_oversized(self):
        a=task()
        body=queue.serialize(a)
        self.assertEqual(queue.parse(body),a)
        with self.assertRaises(ValueError):queue.parse(body+'extra')
        with self.assertRaises(ValueError):queue.parse('x'*70000)
    def test_shard_checkpoint_cannot_cross_boundary(self):
        a=task(task_type='admission_partition_verify',source_id='source',shard=2,checkpoint=400)
        self.assertEqual(queue.validate(a),a)
    def test_approved_new_task_types_validate_safely(self):
        for t_type in ('lexical_partition', 'examples_partition', 'release_candidate_qa'):
            t = task(task_type=t_type, source_id='vetted-source', shard=1)
            self.assertEqual(queue.validate(t), t)

    def test_new_task_types_reject_public_registry_source(self):
        for t_type in ('lexical_partition', 'examples_partition', 'release_candidate_qa'):
            with self.assertRaises(ValueError):
                queue.validate(task(task_type=t_type, source_id='public-registry', shard=1))

    def test_unapproved_task_type_fails_closed(self):
        with self.assertRaises(ValueError):
            queue.validate(task(task_type='unapproved_custom_type', source_id='vetted-source', shard=1))

if __name__ == '__main__':unittest.main()
