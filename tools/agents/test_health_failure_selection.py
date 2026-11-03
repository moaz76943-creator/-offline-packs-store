"""Regression tests for evidence-driven, bounded health task discovery."""
import unittest

from tools.agents.root_cause import select_active_failures


def run(run_id, name, conclusion, status="completed"):
    return {"databaseId": run_id, "name": name, "conclusion": conclusion, "status": status}


class ActiveFailureSelectionTests(unittest.TestCase):
    def test_newer_success_suppresses_old_failure(self):
        rows = [
            run(51, "Public Merge Gate", "success"),
            run(50, "Public Merge Gate", "failure"),
            run(49, "Agent QA", "failure"),
        ]
        self.assertEqual(select_active_failures(rows), [
            {"databaseId": 49, "name": "Agent QA"}
        ])

    def test_stable_workflow_name_groups_dynamic_run_titles(self):
        rows = [
            {"databaseId": 85, "name": "Queue 85", "workflowName": "Public GHA issue dispatcher",
             "status": "completed", "conclusion": "success"},
            {"databaseId": 82, "name": "Queue 82", "workflowName": "Public GHA issue dispatcher",
             "status": "completed", "conclusion": "failure"},
        ]
        self.assertEqual(select_active_failures(rows), [])

    def test_newer_running_job_blocks_stale_failure(self):
        rows = [
            run(51, "Agent QA", None, "in_progress"),
            run(50, "Agent QA", "failure"),
        ]
        self.assertEqual(select_active_failures(rows), [])

    def test_ignores_own_health_and_skipped_jobs(self):
        rows = [
            run(53, "Agent health", "failure"),
            run(52, "Agent watchdog", "skipped"),
            run(51, "Agent legal", "failure"),
        ]
        self.assertEqual(select_active_failures(rows), [
            {"databaseId": 51, "name": "Agent legal"}
        ])

    def test_one_latest_failure_per_workflow_and_max_three(self):
        rows = [
            run(55, "W1", "failure"),
            run(54, "W1", "failure"),
            run(53, "W2", "failure"),
            run(52, "W3", "failure"),
            run(51, "W4", "failure"),
        ]
        self.assertEqual(select_active_failures(rows), [
            {"databaseId": 55, "name": "W1"},
            {"databaseId": 53, "name": "W2"},
            {"databaseId": 52, "name": "W3"},
        ])
        self.assertEqual(select_active_failures(rows, cap=1), [
            {"databaseId": 55, "name": "W1"}
        ])

    def test_unknown_rows_and_invalid_run_ids_are_not_tasks(self):
        rows = [None, {}, "invalid", run(True, "W0", "failure"),
                run(-1, "W1", "failure"), run(1, "", "failure"),
                run(4, "W2", "success")]
        self.assertEqual(select_active_failures(rows), [])
        self.assertEqual(select_active_failures([], cap=3), [])

    def test_independent_pull_requests_never_supersede_each_other(self):
        rows = [
            {"databaseId": 105, "workflowName": "Public PR Merge Gate",
             "event": "pull_request", "pullRequest": 202,
             "name": "Change B", "status": "completed", "conclusion": "success"},
            {"databaseId": 104, "workflowName": "Public PR Merge Gate",
             "event": "pull_request", "pullRequest": 201,
             "name": "Change A", "status": "completed", "conclusion": "failure"},
            {"databaseId": 103, "workflowName": "Public PR Merge Gate",
             "event": "pull_request", "pullRequest": 201,
             "name": "Change A old", "status": "completed", "conclusion": "failure"},
        ]
        self.assertEqual(select_active_failures(rows), [
            {"databaseId": 104, "name": "Public PR Merge Gate PR #201"}
        ])

    def test_fork_prs_with_same_branch_name_remain_isolated(self):
        rows = [
            {"databaseId": 95, "workflowName": "Gate", "event": "pull_request",
             "headRepository": "external/fork-b", "headBranch": "fix",
             "status": "completed", "conclusion": "success"},
            {"databaseId": 94, "workflowName": "Gate", "event": "pull_request",
             "headRepository": "external/fork-a", "headBranch": "fix",
             "status": "completed", "conclusion": "failure"},
        ]
        selected = select_active_failures(rows)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["databaseId"], 94)
        self.assertIn("external/fork-a", selected[0]["name"])

    def test_skip_is_not_evidence_that_older_failure_was_fixed(self):
        rows = [
            run(99, "Agent legal", "skipped"),
            run(98, "Agent legal", "failure"),
        ]
        self.assertEqual(select_active_failures(rows), [
            {"databaseId": 98, "name": "Agent legal"}
        ])

    def test_unscoped_pull_request_run_does_not_make_unsafe_issue(self):
        rows = [{"databaseId": 101, "workflowName": "Gate", "event": "pull_request",
                 "status": "completed", "conclusion": "failure"}]
        self.assertEqual(select_active_failures(rows), [])

    def test_bad_input_and_caps_fail_closed(self):
        for bad in (None, {}, "runs"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    select_active_failures(bad)
        for bad_cap in (0, 4, True, "3"):
            with self.subTest(bad_cap=bad_cap):
                with self.assertRaises(ValueError):
                    select_active_failures([], cap=bad_cap)


if __name__ == "__main__":
    unittest.main()
