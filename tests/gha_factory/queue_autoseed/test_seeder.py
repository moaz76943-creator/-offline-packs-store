"""Fail-closed tests for autonomous source partition issue seeding.

All sources and partitions below are synthetic; no public corpus is admitted.
"""
import copy
import json
import unittest
from pathlib import Path
from tools.gha_factory.dispatcher import queue
from tools.gha_factory.queue_autoseed import seeder

SHA = 'a' * 64
REGISTRY_SHA = 'b' * 64
SOURCE = 'reviewed.fixture'


def context(parts=3):
    source = {'source_id': SOURCE, 'kind': 'dictionary',
              'status': 'APPROVED_FOR_REDISTRIBUTION',
              'retrieval': {'sha256': SHA, 'artifact_path': 'safe/input.jsonl'},
              'review': {'reviewer': 'fixture'},
              'license': {'id': 'CC0-1.0'}}
    jobs = {}
    for i in range(parts):
        jobs[(SOURCE, 'de', SHA, i)] = {
            'job': {'partition_index': i, 'sha256': 'c' * 64, 'record_count': 2},
            'report': {'status': 'ACCEPTED_FOR_QUEUE', 'publication_approved': False},
            'folder': None}
    return {'languages': frozenset(('de', 'ar')), 'sources': [source],
            'admissions': jobs}


def as_existing(task):
    return {'number': 55, 'title': queue.PREFIX + task['task_id'],
            'body': queue.serialize(task), 'user': {'login': seeder.OWNER},
            'state': 'open'}


class SeederTests(unittest.TestCase):
    def test_empty_unapproved_ledger_creates_no_queue_work(self):
        ctx = {'languages': frozenset(('de',)), 'sources': [], 'admissions': {}}
        self.assertEqual(seeder.plan(ctx, REGISTRY_SHA, []), [])

    def test_deterministic_partition_ids_and_safe_task_schema(self):
        planned = seeder.plan(context(), REGISTRY_SHA, [])
        self.assertEqual(len(planned), 3)
        self.assertEqual([item['shard'] for item in planned], [0, 1, 2])
        for item in planned:
            self.assertEqual(item['task_id'], queue.fingerprint(item))
            self.assertEqual(item['task_type'], 'admission_partition_verify')
            self.assertEqual(item['state'], 'READY')
            self.assertEqual(item['source_sha256'], SHA)
            self.assertEqual(item['attempts'], 0)
            self.assertEqual(queue.validate(item, {'ar', 'de'}), item)

    def test_existing_success_is_not_enqueued_again(self):
        target = seeder.plan(context(), REGISTRY_SHA, [])[0]
        original = copy.deepcopy(target)
        original['state'] = 'SUCCEEDED'
        planned = seeder.plan(context(), REGISTRY_SHA, [as_existing(original)])
        self.assertEqual([t['shard'] for t in planned], [1, 2])

    def test_closed_issue_is_still_deduped(self):
        existing = as_existing(seeder.plan(context(), REGISTRY_SHA, [])[0])
        existing['state'] = 'closed'
        self.assertEqual([x['shard'] for x in seeder.plan(context(), REGISTRY_SHA, [existing])], [1, 2])

    def test_bounded_batch_limits_new_issue_creation(self):
        planned = seeder.plan(context(parts=12), REGISTRY_SHA, [], limit=3)
        self.assertEqual(len(planned), 3)

    def test_unreviewed_license_is_blocked(self):
        ctx = context()
        ctx['sources'][0]['status'] = 'CANDIDATE_ONLY'
        self.assertEqual(seeder.plan(ctx, REGISTRY_SHA, []), [])

    def test_unknown_registered_language_is_blocked(self):
        ctx = context()
        ctx['languages'] = frozenset(('ar',))
        self.assertEqual(seeder.plan(ctx, REGISTRY_SHA, []), [])

    def test_ambiguous_sha_source_identity_is_rejected_not_reused(self):
        existing = seeder.plan(context(), REGISTRY_SHA, [])[0]
        collision = copy.deepcopy(existing)
        collision['source_id'] = 'different.source'
        with self.assertRaisesRegex(ValueError, 'collision'):
            seeder.plan(context(), REGISTRY_SHA, [as_existing(collision)])

    def test_malformed_owner_issue_is_reserved_without_stalling_other_ready_shards(self):
        tasks = seeder.plan(context(), REGISTRY_SHA, [])
        bad = as_existing(tasks[0])
        bad['body'] = 'untrusted malformed content'
        self.assertEqual([x['shard'] for x in seeder.plan(context(), REGISTRY_SHA, [bad])], [1, 2])
        self.assertEqual(seeder.verified_context(
            {'languages': frozenset(('de',)), 'sources': [], 'admissions': {}},
            Path('.'), [bad])['admissions'], {})

    def test_title_body_mismatch_reserves_both_fingerprints(self):
        tasks = seeder.plan(context(), REGISTRY_SHA, [])
        bad = as_existing(tasks[1])
        bad['title'] = queue.PREFIX + tasks[0]['task_id']
        self.assertEqual([x['shard'] for x in seeder.plan(context(), REGISTRY_SHA, [bad])], [2])

    def test_invalid_owner_issue_does_not_suppress_existing_collision_guard(self):
        tasks = seeder.plan(context(), REGISTRY_SHA, [])
        duplicate = as_existing(tasks[0])
        with self.assertRaisesRegex(ValueError, 'duplicate pre-existing queue issue'):
            seeder.plan(context(), REGISTRY_SHA, [duplicate, dict(duplicate, number=56)])

    def test_issue_filter_ignores_pull_requests_and_other_owner(self):
        example = as_existing(seeder.plan(context(), REGISTRY_SHA, [])[0])
        foreign = copy.deepcopy(example)
        foreign['user']['login'] = 'another-user'
        pr = copy.deepcopy(example)
        pr['pull_request'] = {'url': 'https://example.org'}
        self.assertEqual(len(seeder.plan(context(), REGISTRY_SHA, [foreign, pr])), 3)

    def test_bad_limits_never_seed(self):
        for value in (0, 6, True, '3'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    seeder.plan(context(), REGISTRY_SHA, [], limit=value)

    def test_invalid_title_still_reserves_validated_body_partition(self):
        tasks = seeder.plan(context(), REGISTRY_SHA, [])
        bad = as_existing(tasks[0])
        bad['title'] = queue.PREFIX + 'broken'
        self.assertEqual([x['shard'] for x in seeder.plan(context(), REGISTRY_SHA, [bad])], [1, 2])

    def test_mismatched_v2_title_reserves_partition_across_fingerprint_versions(self):
        from tools.gha_factory.orchestration import protocol as proto
        v2_task = proto.new(SOURCE, SHA, 'de', 'approved_snapshot_verify', 0)
        mismatched = {
            'number': 56,
            'title': queue.PREFIX + ('ab' * 32),
            'body': proto.serialize(v2_task),
            'user': {'login': seeder.OWNER},
            'state': 'open',
        }
        self.assertNotEqual(v2_task['task_id'], 'ab' * 32)
        self.assertEqual(
            [t['shard'] for t in seeder.plan(context(), REGISTRY_SHA, [mismatched])],
            [1, 2])

    def test_v2_task_in_existing_issues_deduplicates_partition(self):
        from tools.gha_factory.orchestration import protocol as proto
        v2_task = proto.new(SOURCE, SHA, 'de', 'approved_snapshot_verify', 0)
        v2_issue = {
            'number': 56,
            'title': queue.PREFIX + v2_task['task_id'],
            'body': proto.serialize(v2_task),
            'user': {'login': seeder.OWNER},
            'state': 'open',
        }
        planned = seeder.plan(context(), REGISTRY_SHA, [v2_issue])
        self.assertEqual([t['shard'] for t in planned], [1, 2])


    def test_historical_v1_fingerprint_cannot_hide_source_id_collision(self):
        original = seeder.plan(context(parts=1), REGISTRY_SHA, [])[0]
        conflicting = copy.deepcopy(original)
        # v1 fingerprint omits source_id; same fingerprint now names another source.
        conflicting['source_id'] = 'different.source'
        self.assertEqual(original['task_id'], queue.fingerprint(conflicting))
        with self.assertRaisesRegex(ValueError, 'collision'):
            seeder.verified_context(context(parts=1), Path('.'), [as_existing(conflicting)])

    def test_historical_v2_same_partition_different_source_is_rejected(self):
        from tools.gha_factory.orchestration import protocol as proto
        prior = proto.new('different.source', SHA, 'de',
                          'approved_snapshot_verify', 0)
        issue = {'number': 96, 'title': queue.PREFIX + prior['task_id'],
                 'body': proto.serialize(prior),
                 'user': {'login': seeder.OWNER}, 'state': 'closed'}
        with self.assertRaisesRegex(ValueError, 'collision'):
            seeder.plan(context(parts=1), REGISTRY_SHA, [issue])


if __name__ == '__main__':
    unittest.main()
