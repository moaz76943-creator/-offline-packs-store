import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tools.gha_factory.dispatcher import queue
from tools.gha_factory.orchestration import protocol as p

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)

def task(**kw):
    t = p.new('fixture', 'a'*64, 'de', 'approved_snapshot_verify', 0)
    t.update(kw)
    t['task_id'] = p.fingerprint(t)
    return t

class ProtocolTests(unittest.TestCase):
    def test_v1_identity_is_unchanged(self):
        t = task(source_id='public-registry', task_type='registry_validate')
        t.pop('dependencies'); t['schema_version']='1.0'
        t['contract_version']='1.0.0'; t['task_id']=queue.fingerprint(t)
        original=queue.serialize(t)
        self.assertEqual(p.serialize(p.parse(original)), original)
    def test_source_id_and_dependencies_bind_v2(self):
        a=task(); b=task(source_id='other'); c=task(dependencies=['b'*64])
        self.assertEqual(len({a['task_id'],b['task_id'],c['task_id']}),3)
    def test_closed_enum_and_no_extra_commands(self):
        for k,v in [('task_type','sh -c evil'),('source_sha256','bad'),('language','private'),('command','evil')]:
            t=task();t[k]=v
            with self.assertRaises(ValueError):p.validate(t,{'de'})
    def test_bool_is_not_a_counter(self):
        for key in ('attempts','checkpoint','run_id','shard'):
            t=task();t[key]=True
            with self.assertRaises(ValueError):p.validate(t)
    def test_dependency_ids_bounded_sorted_unique(self):
        for deps in [['a'*64]*2,['z'*64],['c'*64,'b'*64],['b'*64]*33]:
            with self.assertRaises(ValueError):task(dependencies=deps) and p.validate(task(dependencies=deps))
    def test_reject_duplicate_json_keys(self):
        raw=p.serialize(task()).replace('"state":"NEW"','"state":"NEW","state":"READY"')
        with self.assertRaises(ValueError):p.parse(raw)
    def test_claim_maximum_retry(self):
        with self.assertRaises(ValueError):p.claim(task(state='READY',attempts=3),NOW,1,1)
    def test_receipt_replay_and_tamper(self):
        t=p.claim(task(state='READY'),NOW,1,1)
        r=p.receipt(t,'SUCCEEDED',1,1,None,None)
        for key,value in [('run_id',2),('run_attempt',2),('task_id','f'*64),('checkpoint',10001),('candidate_count',True)]:
            wrong=dict(r);wrong[key]=value
            with self.assertRaises(ValueError):p.finish(t,wrong,NOW)
    def test_completion_idempotent_only_exact_receipt(self):
        t=p.claim(task(state='READY'),NOW,1,1);r=p.receipt(t,'SUCCEEDED',1,0,None,None)
        done=p.finish(t,r,NOW)
        self.assertEqual(done,p.finish(done,r,NOW))
        with self.assertRaises(ValueError):p.finish(done,dict(r,checkpoint=2),NOW)
    def test_expired_receipt_rejected(self):
        t=p.claim(task(state='READY'),NOW,1,1)
        with self.assertRaises(ValueError):p.finish(t,p.receipt(t,'SUCCEEDED',1,0,None,None),NOW+timedelta(hours=6))
    def test_bounded_exponential_backoff(self):
        t=p.claim(task(state='READY'),NOW,1,1)
        retry=p.fail(t,NOW)
        self.assertEqual(retry['state'],'RETRY_WAIT')
        self.assertEqual(retry['next_retry_at'],queue.iso(NOW+timedelta(minutes=30)))
        self.assertEqual(p.fail(dict(t,attempts=3),NOW)['state'],'FAILED')
    def test_missing_artifact_cannot_advance_checkpoint(self):
        t=p.claim(task(state='READY'),NOW,1,1)
        self.assertEqual(p.fail(t,NOW)['checkpoint'],0)
    def test_checkpoint_hash_and_path_validation(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);blob=b'candidate';(folder/'candidates.jsonl').write_bytes(blob)
            t=p.claim(task(state='READY'),NOW,1,1)
            r=p.receipt(t,'SUCCEEDED',1,1,hashlib.sha256(blob).hexdigest(),None)
            p.verify_output(folder,r)
            (folder/'candidates.jsonl').write_bytes(b'tampered')
            with self.assertRaises(ValueError):p.verify_output(folder,r)
    def test_null_digest_with_candidates_is_rejected_for_v2(self):
        t=p.claim(task(state='READY'),NOW,1,1)
        # Snapshot verification reports checked records, not generated candidates.
        with self.assertRaises(ValueError):p.finish(t,p.receipt(t,'SUCCEEDED',1,1,None,None),NOW)

if __name__=='__main__':unittest.main()
