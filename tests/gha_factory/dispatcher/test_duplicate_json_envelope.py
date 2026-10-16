"""Reject ambiguous JSON duplicate-key queue issue envelopes (GHA-02)."""
import unittest

from tools.gha_factory.dispatcher import queue


def approved_task():
    task = {
        'schema_version': queue.VERSION,
        'task_id': None,
        'source_sha256': 'a' * 64,
        'source_id': 'attested.fixture',
        'language': 'de',
        'task_type': 'admission_partition_verify',
        'shard': 0,
        'contract_version': queue.CONTRACT,
        'state': 'READY',
        'attempts': 0,
        'next_retry_at': None,
        'lease_until': None,
        'run_id': None,
        'run_attempt': None,
        'checkpoint': 0,
        'receipt': None,
    }
    task['task_id'] = queue.fingerprint(task)
    return task


class DuplicateJsonKeyEnvelopeTests(unittest.TestCase):
    def test_ordinary_v1_envelope_round_trips(self):
        task = approved_task()
        self.assertEqual(queue.parse(queue.serialize(task)), task)

    def test_duplicate_source_id_is_not_accepted_even_if_last_value_is_valid(self):
        valid = queue.serialize(approved_task())
        changed = valid.replace(
            '"source_id":"attested.fixture"',
            '"source_id":"forged.fixture","source_id":"attested.fixture"',
            1,
        )
        self.assertNotEqual(changed, valid)
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            queue.parse(changed)

    def test_duplicate_nested_receipt_field_is_rejected(self):
        task = approved_task()
        task['receipt'] = {
            'status': 'SUCCEEDED',
            'checkpoint': 0,
            'candidate_count': 0,
            'candidate_sha256': None,
            'error_code': None,
        }
        valid = queue.serialize(task)
        changed = valid.replace(
            '"status":"SUCCEEDED"',
            '"status":"FAILED","status":"SUCCEEDED"',
            1,
        )
        self.assertNotEqual(changed, valid)
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            queue.parse(changed)


if __name__ == '__main__':
    unittest.main()
