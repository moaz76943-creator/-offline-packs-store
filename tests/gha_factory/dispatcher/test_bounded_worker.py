import json
import time
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from tools.gha_factory.dispatcher import queue, bounded_worker

SHA = 'a' * 64


def make_task(**overrides):
    t = dict(schema_version='1.0', source_sha256=SHA, source_id='public-registry',
             language='de', task_type='registry_validate', shard=0, contract_version='1.0.0',
             state='CLAIMED', attempts=1, next_retry_at=None,
             lease_until=queue.iso(datetime.now(timezone.utc) + timedelta(minutes=30)),
             run_id=777, run_attempt=1, checkpoint=0, receipt=None)
    t.update(overrides)
    t['task_id'] = queue.fingerprint(t)
    return t


class BoundedTests(unittest.TestCase):
    def setUp(self):
        self.t = make_task()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.api = Mock()
        self.api.one.return_value = {'title': queue.PREFIX + self.t['task_id'], 'body': queue.serialize(self.t), 'user': {'login': 'moaz76943-creator'}}

    def test_expired_claim_rejected_before_worker_launch(self):
        self.t['lease_until'] = queue.iso(datetime.now(timezone.utc) - timedelta(minutes=1))
        self.api.one.return_value['body'] = queue.serialize(self.t)
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen') as p:
            with self.assertRaises(ValueError):
                bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
            p.assert_not_called()

    def test_stale_receipt_cannot_be_reused_on_new_execution(self):
        (self.out / 'receipt.json').write_text('\"stale\"')
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen') as p:
            with self.assertRaises(ValueError):
                bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
            p.assert_not_called()

    def test_insufficient_lease_for_timeout_rejected_before_launch(self):
        self.t['lease_until'] = queue.iso(datetime.now(timezone.utc) + timedelta(seconds=5))
        self.api.one.return_value['body'] = queue.serialize(self.t)
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen') as p:
            with self.assertRaises(ValueError):
                bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
            p.assert_not_called()

    def test_actual_subprocess_is_killed_after_timeout(self):
        script = self.out / 'cli.py'
        script.write_text('import time\ntime.sleep(30)\n')
        with patch.object(bounded_worker, '__file__', str(self.out / 'bounded_worker.py')):
            started = time.monotonic()
            receipt = bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1,
                                             self.out, timeout=1)
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(receipt['error_code'], 'TIMEOUT')

    def test_owner_mismatch_rejected_before_spawn(self):
        self.api.one.return_value['user']['login'] = 'attacker'
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen') as p:
            with self.assertRaises(ValueError):
                bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
            p.assert_not_called()

    def test_timeout_terminates_process_group_and_writes_failing_receipt(self):
        from subprocess import TimeoutExpired
        process = Mock(pid=999, returncode=-9)
        process.wait.side_effect = [TimeoutExpired('worker', 2), -9]
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen', return_value=process), \
             patch('tools.gha_factory.dispatcher.bounded_worker.os.killpg') as kill:
            receipt = bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out, timeout=2)
        kill.assert_called_once()
        self.assertEqual(receipt['status'], 'FAILED')
        self.assertEqual(receipt['error_code'], 'TIMEOUT')
        self.assertEqual(json.loads((self.out / 'receipt.json').read_text()), receipt)

    def test_missing_receipt_becomes_bounded_failure(self):
        process = Mock(returncode=1)
        process.wait.return_value = 1
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen', return_value=process):
            receipt = bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
        self.assertEqual(receipt['error_code'], 'EXECUTION')

    def test_wrong_run_receipt_is_never_accepted(self):
        data = dict(schema_version='1.0', task_id=self.t['task_id'], run_id=888,
                    run_attempt=1, status='SUCCEEDED', checkpoint=1,
                    candidate_count=0, candidate_sha256=None, error_code=None)
        process = Mock(returncode=0)
        def spawn(*args, **kwargs):
            (self.out / 'receipt.json').write_text(json.dumps(data))
            return process
        process.wait.return_value = 0
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen', side_effect=spawn):
            receipt = bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
        self.assertEqual(receipt['status'], 'FAILED')
        self.assertEqual(receipt['error_code'], 'INVALID_INPUT')

    def test_worker_success_receipt_preserved(self):
        data = dict(schema_version='1.0', task_id=self.t['task_id'], run_id=777,
                    run_attempt=1, status='SUCCEEDED', checkpoint=1,
                    candidate_count=0, candidate_sha256=None, error_code=None)
        process = Mock(returncode=0)
        def spawn(*args, **kwargs):
            (self.out / 'receipt.json').write_text(json.dumps(data))
            return process
        process.wait.return_value = 0
        with patch('tools.gha_factory.dispatcher.bounded_worker.subprocess.Popen', side_effect=spawn):
            receipt = bounded_worker.execute(self.api, 19, self.t['task_id'], 777, 1, self.out)
        self.assertEqual(receipt, data)

if __name__ == '__main__':
    unittest.main()
