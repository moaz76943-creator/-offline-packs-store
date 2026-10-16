"""Read-only independent run compatibility, fairness and adversarial fixtures."""
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from tools.gha_factory.dispatcher import queue
from tools.factory_extensions.worker_handoff import protocol as p

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
SHA = 'a' * 64
CODE = 'b' * 64


def sample(shard=0, language='de', source='fixture.test', kind='admission_partition_verify'):
    t = dict(schema_version='1.0', task_id='', source_sha256=SHA, source_id=source,
             language=language, task_type=kind, shard=shard, contract_version='1.0.0',
             state='READY', attempts=0, next_retry_at=None, lease_until=None,
             run_id=None, run_attempt=None, checkpoint=0, receipt=None)
    t['task_id'] = queue.fingerprint(t)
    return t


def leased():
    return queue.claim(sample(), NOW, 99, 1)


def issue(t=None):
    t = t or leased()
    return dict(number=20, title=p.v1.PREFIX + t['task_id'], body=queue.serialize(t),
                user={'login': 'moaz76943-creator'})


def run(id=101, attempt=1, status='in_progress'):
    return dict(id=id, run_attempt=attempt, path=p.WORKFLOW, event='workflow_dispatch',
                head_branch='main', head_sha=CODE, status=status)


class WorkerHandoffTests(unittest.TestCase):
    def test_v1_history_roundtrip_unmodified(self):
        t = leased()
        self.assertEqual(queue.parse(issue(t)['body']), t)
        self.assertEqual(p.ticket(issue(t), run(), CODE, NOW)['task_id'], t['task_id'])

    def test_v1_duplicate_json_envelope_fails_closed_before_pr81_merges(self):
        x = issue()
        x['body'] = x['body'].replace('"language":"de"',
            '"language":"zz","language":"de"', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            p.trusted_task(x)

    def test_cancelled_and_failed_completed_workers_never_attest_success(self):
        for conclusion in ('cancelled', 'failure', 'timed_out'):
            meta = dict(run(status='completed'), conclusion=conclusion)
            with self.assertRaisesRegex(ValueError, 'unverified'):
                p.ticket(issue(), meta, CODE, NOW)

    def test_worker_different_run_and_pin(self):
        handoff = p.ticket(issue(), run(), CODE, NOW)
        self.assertEqual(handoff['controller_run_id'], 99)
        self.assertEqual(handoff['worker_run_id'], 101)
        self.assertEqual(handoff['source_sha256'], SHA)

    def test_reject_same_run_as_controller(self):
        with self.assertRaisesRegex(ValueError, 'not independent'):
            p.ticket(issue(), run(id=99), CODE, NOW)

    def test_reject_unverified_other_workflow_ref(self):
        bad = run()
        bad['path'] = '.github/workflows/build_store.yml'
        with self.assertRaisesRegex(ValueError, 'unverified'):
            p.ticket(issue(), bad, CODE, NOW)

    def test_reject_untrusted_issue_creator(self):
        x = issue()
        x['user']['login'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'untrusted'):
            p.ticket(x, run(), CODE, NOW)

    def test_reject_replay_after_new_attempt(self):
        handoff = p.ticket(issue(), run(), CODE, NOW)
        changed = queue.claim(sample(), NOW, 105, 2)
        with self.assertRaisesRegex(ValueError, 'stale'):
            p.validate_against_issue(handoff, issue(changed), run(), NOW)

    def test_stale_lease_fails_even_if_run_metadata_still_alive(self):
        with self.assertRaisesRegex(ValueError, 'lease'):
            p.ticket(issue(), run(), CODE, NOW + timedelta(hours=6))

    def test_unsupported_kind_no_arbitrary_exec(self):
        x = leased()
        x['task_type'] = 'shell'
        x['task_id'] = queue.fingerprint(x)
        with self.assertRaises(ValueError):
            p.ticket(issue(x), run(), CODE, NOW)

    def test_duplicate_identity_fails_closed(self):
        a, b = sample(), sample()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            p.fair_claim_candidates([(1, a), (2, b)], [])

    def test_global_three_and_source_language_locks(self):
        entries = [(1, sample(0)), (2, sample(1)), (3, sample(2, 'en')),
                   (4, sample(3, 'fr')), (5, sample(4, 'ar'))]
        picked = p.fair_claim_candidates(entries, [])
        self.assertEqual([number for number, _ in picked], [1, 3, 4])
        self.assertEqual(len(picked), 3)

    def test_five_hour_active_worker_does_not_block_next_hour(self):
        active = dict(leased(), state='RUNNING')
        candidates = [(3, sample(1, 'en')), (4, sample(2, 'fr')), (5, sample(3, 'ar'))]
        self.assertEqual([n for n, _ in p.fair_claim_candidates(candidates, [active])], [3, 4])
        self.assertEqual(len(p.fair_claim_candidates(candidates, [active])), 2)

    def test_already_full_global_capacity(self):
        active = [dict(leased(), language=l, task_id=c * 64)
                  for l, c in [('de', 'a'), ('en', 'b'), ('fr', 'c')]]
        self.assertEqual(p.fair_claim_candidates([(4, sample(4, 'ar'))], active), [])

    def test_full_issue_inventory_including_active_worker_is_safe(self):
        active = dict(leased(), state='RUNNING')
        ready = sample(5, 'en')
        inventory = [(1, active), (2, ready)]
        self.assertEqual([n for n, _ in p.fair_claim_candidates(inventory, [active])], [2])

    def test_retry_priority_and_issue_number_stable(self):
        first, retry = sample(10), sample(11, 'en')
        retry['attempts'] = 1
        self.assertEqual([n for n, _ in p.fair_claim_candidates([(22, retry), (40, first)], [])], [40, 22])

    def test_no_unreviewed_capacity_escalation(self):
        with self.assertRaisesRegex(ValueError, 'capacity'):
            p.fair_claim_candidates([], [], limit=4)

    def test_durable_checkpoint_requires_actual_bytes(self):
        t = p.ticket(issue(), run(), CODE, NOW)
        blob = b'verified resume state'
        manifest = dict(task_id=t['task_id'], source_sha256=SHA, checkpoint=0,
                        sha256=hashlib.sha256(blob).hexdigest())
        self.assertEqual(p.durable_checkpoint(t, manifest, blob), 0)
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            p.durable_checkpoint(t, manifest, b'tampered')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            p.durable_checkpoint(t, manifest, b'')

    def test_receipt_separate_run_provenance_and_replay_protected(self):
        handoff = p.ticket(issue(), run(), CODE, NOW)
        raw = b'{"ok":true}\n'
        result = p.receipt(handoff, 'SUCCEEDED', raw, 1)
        self.assertTrue(p.verify_receipt(result, handoff, raw))
        bad_run = dict(handoff, worker_run_id=202)
        with self.assertRaisesRegex(ValueError, 'replay'):
            p.verify_receipt(result, bad_run, raw)
        with self.assertRaisesRegex(ValueError, 'digest'):
            p.verify_receipt(result, handoff, b'changed')

    def test_no_silent_success_if_worker_output_missing(self):
        handoff = p.ticket(issue(), run(), CODE, NOW)
        result = p.receipt(handoff, 'SUCCEEDED', b'nonempty', 1)
        with self.assertRaisesRegex(ValueError, 'digest'):
            p.verify_receipt(result, handoff, b'')

    def test_completed_v1_receipt_is_immutable(self):
        historical = dict(sample(source='public-registry', kind='registry_validate'),
                          source_sha256='ed8c5331af31776c891a025c4f086ee40ec170d4adbe380849f9e3f4d4bc75ea',
                          state='SUCCEEDED', attempts=1, checkpoint=1, run_id=38328584584,
                          run_attempt=1, lease_until=None, receipt=dict(candidate_count=0,
                          candidate_sha256=None, checkpoint=1, error_code=None, status='SUCCEEDED'))
        historical['task_id'] = queue.fingerprint(historical)
        self.assertEqual(historical['task_id'], '55935327c9e6e45b4690034140e75674ca1b7d1a16db79feccacfd52a9b49673')
        body = queue.serialize(historical)
        preserved = p.trusted_task(issue(historical))
        self.assertEqual(queue.serialize(preserved), body)
        with self.assertRaisesRegex(ValueError, 'not leased'):
            p.ticket(issue(historical), run(), CODE, NOW)

    def test_v2_malformed_envelope_rejected_by_integrated_parser(self):
        with self.assertRaisesRegex(ValueError, 'envelope/version mismatch'):
            p.trusted_task({'number': 1, 'title': p.v1.PREFIX + SHA,
                            'body': '```gha-task-v2\n{}\n```',
                            'user': {'login': 'moaz76943-creator'}})


if __name__ == '__main__':
    unittest.main()
