#!/usr/bin/env python3
import unittest
import sys, os
sys.path.insert(0, os.path.abspath('.'))

from tools.merge_coordinator.coordinator import compute_pr_lifecycle_state, CoordinatorPrState

class TestStateComputation(unittest.TestCase):
    def test_draft_is_skipped(self):
        state, reason = compute_pr_lifecycle_state({'isDraft': True, 'mergeable': 'MERGEABLE'})
        self.assertEqual(state, CoordinatorPrState.SKIPPED)
        self.assertEqual(reason, 'DRAFT_STATUS')

    def test_skip_ci_is_skipped(self):
        state, reason = compute_pr_lifecycle_state({'title': 'feat: something [skip ci]', 'isDraft': False, 'mergeable': 'MERGEABLE'})
        self.assertEqual(state, CoordinatorPrState.SKIPPED)
        self.assertEqual(reason, 'SKIP_CI_REQUESTED')

    def test_conflict_is_blocked(self):
        state, reason = compute_pr_lifecycle_state({'isDraft': False, 'mergeable': 'CONFLICTING'})
        self.assertEqual(state, CoordinatorPrState.BLOCKED)
        self.assertEqual(reason, 'MERGE_CONFLICT')

    def test_failing_checks_is_blocked(self):
        checks = [{'name': 'public-pr-merge-gate', 'conclusion': 'failure'}]
        state, reason = compute_pr_lifecycle_state({'isDraft': False, 'mergeable': 'MERGEABLE'}, checks)
        self.assertEqual(state, CoordinatorPrState.BLOCKED)
        self.assertEqual(reason, 'CI_CHECK_FAILURE')

    def test_qualified_pr_is_ready(self):
        checks = [{'name': 'public-pr-merge-gate', 'conclusion': 'success'}]
        state, reason = compute_pr_lifecycle_state({'isDraft': False, 'mergeable': 'MERGEABLE'}, checks)
        self.assertEqual(state, CoordinatorPrState.READY)
        self.assertEqual(reason, 'QUALIFIED_FOR_MERGE')

if __name__ == '__main__':
    unittest.main()
