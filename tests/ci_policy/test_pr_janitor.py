"""Janitor checks real gate state and preserves user-supplied squash titles."""
import unittest

from tools.pr_janitor import classify, sanitize_subject


def _pr(**overrides):
    base = {
        "number": 1,
        "title": "feat: example",
        "isDraft": False,
        "state": "OPEN",
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "statusCheckRollup": [
            {"name": "public-pr-merge-gate", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
    }
    base.update(overrides)
    return base


class JanitorContractTest(unittest.TestCase):
    def test_ready_requires_clean_gate(self):
        self.assertEqual(classify(_pr()), "ready")

    def test_behind_gate_failure_and_threads_are_distinct(self):
        self.assertEqual(classify(_pr(mergeStateStatus="BEHIND")), "behind")
        failing = _pr(statusCheckRollup=[
            {"name": "public-pr-merge-gate", "status": "COMPLETED", "conclusion": "FAILURE"},
        ])
        self.assertEqual(classify(failing), "gate")
        self.assertEqual(classify(_pr(mergeStateStatus="BLOCKED")), "threads")
        self.assertEqual(classify(_pr(mergeStateStatus="DIRTY")), "conflict")
        self.assertEqual(classify(_pr(isDraft=True)), "draft")

    def test_extra_failing_check_is_not_ready(self):
        checks = [
            {"name": "public-pr-merge-gate", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "audit", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]
        self.assertEqual(classify(_pr(statusCheckRollup=checks, mergeStateStatus="UNSTABLE")), "unstable")

    def test_successful_status_context_is_ready(self):
        checks = [
            {"name": "public-pr-merge-gate", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"context": "legacy/commit-status", "state": "SUCCESS"},
        ]
        self.assertEqual(classify(_pr(statusCheckRollup=checks)), "ready")
        gate_only = [{"context": "public-pr-merge-gate", "state": "SUCCESS"}]
        self.assertEqual(classify(_pr(statusCheckRollup=gate_only)), "ready")

    def test_squash_subject_keeps_explicit_skip_directives(self):
        subject = sanitize_subject("feat: builder [skip ci]", 342)
        self.assertIn("[skip ci]", subject)
        self.assertIn("#342", subject)
        self.assertIn("skip-checks: true", sanitize_subject("skip-checks: true", 9).lower())


if __name__ == "__main__":
    unittest.main()
