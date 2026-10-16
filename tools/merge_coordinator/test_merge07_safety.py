"""MERGE-07 red/green regressions for the existing sole public coordinator.

These tests never call GitHub or perform a real merge.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import coordinator
from test_coordinator import SHA_A, SHA_B, checks, entry, pr


def review(state, timestamp):
    return {
        'user': {'login': 'trusted-reviewer'},
        'state': state,
        'commit_id': SHA_A,
        'submitted_at': timestamp,
    }


def decision(**kwargs):
    params = {
        'e': entry(),
        'pr': pr(),
        'checks': checks(),
        'reviews': [review('APPROVED', '2026-10-14T08:00:00Z')],
        'files': [{'filename': 'tools/merge_coordinator/safe.py'}],
        'main_sha': SHA_B,
        'commit_message': 'feat: verified',
        'dependencies': {},
    }
    params.update(kwargs)
    return coordinator.evaluate(**params)


class Merge07PolicyRegressions(unittest.TestCase):
    def test_renaming_out_of_legal_ledger_is_not_an_approved_change(self):
        changed = [{
            'filename': 'tools/merge_coordinator/safe.py',
            'previous_filename': 'legal/ledger/sources.json',
            'status': 'renamed',
        }]
        self.assertEqual(decision(files=changed)[0], 'SCOPE_VIOLATION')

    def test_malformed_unhashable_authorization_never_raises(self):
        bad = entry(paths=[{'directory': 'tools/merge_coordinator/'}])
        self.assertIsNotNone(coordinator.policy_error(bad))
        bad = entry(checks=['public-pr-merge-gate', {'bad': 'scoped-qa'}])
        self.assertIsNotNone(coordinator.policy_error(bad))

    def test_newer_changes_requested_overrules_older_approval_even_if_api_order_is_reversed(self):
        reviews = [
            review('CHANGES_REQUESTED', '2026-10-14T09:00:00Z'),
            review('APPROVED', '2026-10-14T08:00:00Z'),
        ]
        self.assertEqual(decision(reviews=reviews)[0], 'NEEDS_REVIEW')

    def test_skipped_or_missing_exact_head_check_cannot_be_accepted(self):
        self.assertEqual(decision(checks={'check_runs': []})[0], 'NOT_RUN')
        old = dict(checks()['check_runs'][0], id=9, conclusion='failure')
        old['name'] = 'public-pr-merge-gate'
        self.assertEqual(decision(checks={'check_runs': checks()['check_runs'] + [old]})[0], 'NOT_RUN')



class Merge07PathDependencyTests(unittest.TestCase):
    """A dependent PR must not prevent its prerequisite from merging."""

    def test_direct_downstream_overlap_does_not_block_prerequisite(self):
        parent = entry()
        child = entry(number=901, dependencies=[900])
        files = [{'filename': 'tools/merge_coordinator/safe.py'}]
        self.assertEqual(
            coordinator.authorized_file_conflicts(
                FakeGithub(overlap=True), parent, files, [parent, child]),
            [],
        )

    def test_transitive_downstream_overlap_does_not_block_prerequisite(self):
        first = entry()
        second = entry(number=901, dependencies=[900])
        third = entry(number=902, dependencies=[901])
        files = [{'filename': 'tools/merge_coordinator/safe.py'}]
        self.assertEqual(
            coordinator.authorized_file_conflicts(
                FakeGithub(overlap=True), first, files, [first, second, third]),
            [],
        )

    def test_unrelated_overlap_still_blocks(self):
        first = entry()
        unrelated = entry(number=901)
        files = [{'filename': 'tools/merge_coordinator/safe.py'}]
        self.assertEqual(
            coordinator.authorized_file_conflicts(
                FakeGithub(overlap=True), first, files, [first, unrelated]),
            [901],
        )

    def test_upstream_overlap_not_exempt_for_downstream_candidate(self):
        first = entry()
        second = entry(number=901, dependencies=[900])
        files = [{'filename': 'tools/merge_coordinator/safe.py'}]
        self.assertEqual(
            coordinator.authorized_file_conflicts(
                FakeGithub(overlap=True), second, files, [first, second]),
            [900],
        )


class FakeGithub:
    def __init__(self, dependency_changes=False, move_main=False, overlap=False, move_head=False):
        self.dependency_changes = dependency_changes
        self.move_main = move_main
        self.overlap = overlap
        self.move_head = move_head
        self.dependency_calls = 0
        self.main_calls = 0
        self.merged = []
        self.query_calls = 0

    def main_sha(self):
        self.main_calls += 1
        return 'c' * 40 if self.move_main and self.main_calls > 1 else SHA_B

    def authorization_origin(self, sha):
        return None, False

    def query_pr(self, number, sha):
        self.query_calls += 1
        p = pr(number=number)
        if self.move_head and self.query_calls > 1:
            p['head']['sha'] = 'c' * 40
        filename = 'safe.py' if self.overlap or number == 900 else 'unrelated.py'
        return p, checks(), [review('APPROVED', '2026-10-14T08:00:00Z')], [
            {'filename': 'tools/merge_coordinator/' + filename}], 'feat: valid'

    def get(self, path):
        return {'state': 'open'}

    def page(self, path):
        number = int(path.split('/')[2])
        filename = 'safe.py' if self.overlap or number == 900 else 'unrelated.py'
        return [{'filename': 'tools/merge_coordinator/' + filename}]

    def related_pr(self, number):
        self.dependency_calls += 1
        merged = not self.dependency_changes or self.dependency_calls == 1
        return {'state': 'closed' if merged else 'open', 'merged': merged}

    def squash(self, number, head):
        self.merged.append((number, head))
        return {'merged': True, 'sha': SHA_B}


class Merge07RaceAndSerialTests(unittest.TestCase):
    def run_fixture(self, gh, candidates):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'approved.json'
            manifest.write_text(json.dumps({'schema': 1, 'prs': candidates}), encoding='utf-8')
            with patch.object(coordinator, 'INTEGRATION_CONFIG', manifest), \
                 patch.object(coordinator, 'GitHub', return_value=gh), \
                 patch.dict(os.environ, {'INTEGRATOR_APPLY': 'true'}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(coordinator.run(), 0)
        return gh

    def test_dependency_must_still_be_merged_at_final_pre_merge_check(self):
        gh = self.run_fixture(FakeGithub(dependency_changes=True), [entry(dependencies=[88])])
        self.assertEqual(gh.merged, [])
        self.assertGreaterEqual(gh.dependency_calls, 2)

    def test_main_changed_during_review_fails_closed(self):
        gh = self.run_fixture(FakeGithub(move_main=True), [entry()])
        self.assertEqual(gh.merged, [])

    def test_only_one_squash_occurs_per_run_with_two_approved_prs(self):
        gh = self.run_fixture(FakeGithub(), [entry(), entry(number=901)])
        self.assertEqual(gh.merged, [(900, SHA_A)])

    def test_same_file_in_two_open_authorized_prs_blocks_unattended_selection(self):
        gh = self.run_fixture(FakeGithub(overlap=True), [entry(), entry(number=901)])
        self.assertEqual(gh.merged, [])

    def test_pr_head_changed_between_queries_blocks_squash(self):
        gh = self.run_fixture(FakeGithub(move_head=True), [entry()])
        self.assertEqual(gh.merged, [])


class ExpiryBoundaryTests(unittest.TestCase):
    run_fixture = Merge07RaceAndSerialTests.run_fixture

    def boundary(self, draft, expire, inside_promote=False):
        real_promote = coordinator.GitHub.promote
        clock = [datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)]
        expired = datetime(2026, 10, 16, 12, 2, tzinfo=timezone.utc)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0]

        class ExpiringGithub(FakeGithub):
            def __init__(self):
                super().__init__()
                self.promoted = []
                self.get_calls = 0

            def query_pr(self, number, sha):
                p, *rest = super().query_pr(number, sha)
                p['draft'] = draft
                return (p, *rest)

            def get(self, path):
                self.get_calls += 1
                if expire and draft and (not inside_promote or self.get_calls == 2):
                    clock[0] = expired
                return {'head': {'sha': SHA_A}, 'state': 'open', 'node_id': 'PR_fixture'}

            def main_sha(self):
                result = super().main_sha()
                if expire and not draft and self.main_calls == 5:
                    clock[0] = expired
                return result

            def promote(self, number, *args):
                if inside_promote:
                    return real_promote(self, number, *args)
                self.promoted.append(number)

            def request(self, path, method='GET', data=None):
                self.promoted.append(900)
                return {'data': {'markPullRequestReadyForReview': {'pullRequest': {'isDraft': False}}}}

        with patch.object(coordinator, 'datetime', Clock):
            return self.run_fixture(ExpiringGithub(), [entry(expiry='2026-10-16T12:01:00Z')])

    def test_expiry_during_final_promotion_read_blocks_write(self):
        self.assertEqual(self.boundary(draft=True, expire=True).promoted, [])
        self.assertEqual(self.boundary(draft=True, expire=False).promoted, [900])

    def test_expiry_during_final_main_read_blocks_squash(self):
        self.assertEqual(self.boundary(draft=False, expire=True).merged, [])
        self.assertEqual(self.boundary(draft=False, expire=False).merged, [(900, SHA_A)])

    def test_expiry_during_real_promote_method_read_blocks_mutation(self):
        self.assertEqual(self.boundary(draft=True, expire=True, inside_promote=True).promoted, [])
        self.assertEqual(self.boundary(draft=True, expire=False, inside_promote=True).promoted, [900])


if __name__ == '__main__':
    unittest.main()
