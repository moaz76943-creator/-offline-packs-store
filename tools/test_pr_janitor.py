import json
import subprocess
import unittest
from unittest.mock import patch, call

from tools import pr_janitor


class TestPRJanitor(unittest.TestCase):

    def test_sanitize_subject(self):
        # Basic cases
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug (#42)", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug #42", 42), "Fix bug #42")

        # Skip CI instructions
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug [skip ci]", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("[CI SKIP] Fix bug", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug [no ci]", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug [skip actions]", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug [actions skip]", 42), "Fix bug (#42)")

        # Skip trailer
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug\nskip-checks: true", 42), "Fix bug (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("Fix bug\nskip-checks: true\n", 42), "Fix bug (#42)")

        # Empty/None titles
        self.assertEqual(pr_janitor.sanitize_subject(None, 42), "PR 42 (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("", 42), "PR 42 (#42)")
        self.assertEqual(pr_janitor.sanitize_subject("   ", 42), "PR 42 (#42)")

        # Truncation
        long_title = "A" * 300
        result = pr_janitor.sanitize_subject(long_title, 42)
        self.assertEqual(len(result), 240)
        self.assertTrue(result.startswith("A" * 200))

    def test_classify(self):
        # Draft
        self.assertEqual(pr_janitor.classify({"isDraft": True}), "draft")
        self.assertEqual(pr_janitor.classify({"state": "DRAFT"}), "draft")

        # Conflict
        self.assertEqual(pr_janitor.classify({"mergeStateStatus": "DIRTY"}), "conflict")
        self.assertEqual(pr_janitor.classify({"mergeStateStatus": "CONFLICTING"}), "conflict")
        self.assertEqual(pr_janitor.classify({"mergeable": "CONFLICTING"}), "conflict")

        # Gate failure
        self.assertEqual(
            pr_janitor.classify({
                "statusCheckRollup": [{"name": "public-pr-merge-gate", "conclusion": "FAILURE"}]
            }),
            "gate"
        )
        self.assertEqual(
            pr_janitor.classify({
                "statusCheckRollup": [{"context": "public-pr-merge-gate", "state": "failure"}]
            }),
            "gate"
        )

        # Unstable
        self.assertEqual(
            pr_janitor.classify({
                "statusCheckRollup": [{"name": "other-check", "conclusion": "FAILURE"}]
            }),
            "unstable"
        )

        # Behind
        self.assertEqual(pr_janitor.classify({"mergeStateStatus": "BEHIND"}), "behind")

        # Threads
        self.assertEqual(pr_janitor.classify({"mergeStateStatus": "BLOCKED"}), "threads")

        # Ready
        self.assertEqual(
            pr_janitor.classify({
                "mergeStateStatus": "CLEAN",
                "statusCheckRollup": [{"name": "public-pr-merge-gate", "conclusion": "SUCCESS", "status": "COMPLETED"}]
            }),
            "ready"
        )

        # Ready with pending other checks prevents ready
        self.assertNotEqual(
            pr_janitor.classify({
                "mergeStateStatus": "CLEAN",
                "statusCheckRollup": [
                    {"name": "public-pr-merge-gate", "conclusion": "SUCCESS"},
                    {"name": "other", "conclusion": "PENDING"}
                ]
            }),
            "ready"
        )

        # Unknown fallback
        self.assertEqual(pr_janitor.classify({}), "unknown")

    def test_label_for(self):
        self.assertEqual(pr_janitor.label_for("behind"), "blocked:behind")
        self.assertEqual(pr_janitor.label_for("gate"), "blocked:gate")
        self.assertEqual(pr_janitor.label_for("threads"), "blocked:threads")
        self.assertEqual(pr_janitor.label_for("conflict"), "blocked:conflict")
        self.assertEqual(pr_janitor.label_for("draft"), "blocked:draft")
        self.assertEqual(pr_janitor.label_for("unstable"), "blocked:unstable")
        self.assertIsNone(pr_janitor.label_for("ready"))
        self.assertIsNone(pr_janitor.label_for("unknown"))

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_main_dry_run(self, mock_check_call, mock_call, mock_check_output):
        # Setup mock gh list and view responses
        mock_check_output.side_effect = [
            json.dumps([{"number": 42}]),  # gh pr list
            json.dumps({"isDraft": True})  # gh pr view
        ]

        pr_janitor.main(["--dry-run"])

        mock_call.assert_not_called()
        mock_check_call.assert_not_called()
        self.assertEqual(mock_check_output.call_count, 2)

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_sharded_scouts_cover_all_prs_once(self, mock_write, mock_remove, mock_read):
        items = [{"number": n} for n in range(1, 9)]
        for index, expected in [(0, (2, 4, 6, 8)), (1, (1, 3, 5, 7))]:
            with self.subTest(shard=index):
                mock_read.reset_mock()
                mock_read.side_effect = [json.dumps(items)] + [
                    json.dumps({"number": n, "isDraft": True}) for n in expected
                ]
                pr_janitor.main(["--dry-run", "--shard-count", "2",
                                 "--shard-index", str(index)])
                self.assertEqual(mock_read.call_count, 1 + len(expected))
                self.assertIn("--limit", mock_read.call_args_list[0].args[0])
                cmd = mock_read.call_args_list[0].args[0]
                self.assertGreaterEqual(int(cmd[cmd.index("--limit") + 1]), 200)
        mock_write.assert_not_called()
        mock_remove.assert_not_called()

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_existing_correct_blocker_label_is_idempotent(self, mock_write, mock_remove, mock_read):
        mock_read.side_effect = [
            json.dumps([{"number": 42}]),
            json.dumps({"number": 42, "isDraft": True,
                        "labels": [{"name": "blocked:draft"}]})
        ]
        pr_janitor.main([])
        mock_write.assert_not_called()
        mock_remove.assert_not_called()

    def test_shard_settings_fail_closed(self):
        for arguments in [
            ["--shard-count", "0"],
            ["--shard-count", "3", "--shard-index", "3"],
            ["--shard-count", "1000"],
        ]:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                pr_janitor.main(arguments)

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_main_label_update(self, mock_check_call, mock_call, mock_check_output):
        # Behind PR scenario
        mock_check_output.side_effect = [
            json.dumps([{"number": 42}]),
            json.dumps({"mergeStateStatus": "BEHIND"})
        ]

        pr_janitor.main([])

        # Verify labels were created/removed/added
        self.assertTrue(mock_call.called)
        self.assertTrue(mock_check_call.called)

        # Check call arguments verify label "blocked:behind" was added
        added = False
        for args, kwargs in mock_check_call.call_args_list:
            if "edit" in args[0] and "--add-label" in args[0] and "blocked:behind" in args[0]:
                added = True
        self.assertTrue(added, "Should have added blocked:behind label")

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_main_merge_one(self, mock_check_call, mock_call, mock_check_output):
        # Ready PR scenario
        mock_check_output.side_effect = [
            json.dumps([{"number": 42}]),
            json.dumps({
                "title": "Clean PR",
                "mergeStateStatus": "CLEAN",
                "statusCheckRollup": [{"name": "public-pr-merge-gate", "conclusion": "SUCCESS", "status": "COMPLETED"}]
            })
        ]

        pr_janitor.main(["--merge-one"])

        # Verify merge was called
        merged = False
        for args, kwargs in mock_check_call.call_args_list:
            if "merge" in args[0] and "--squash" in args[0] and "42" in args[0]:
                merged = True
        self.assertTrue(merged, "Should have squashed merged PR 42")

    @patch("tools.pr_janitor.subprocess.check_output")
    @patch("tools.pr_janitor.subprocess.call")
    @patch("tools.pr_janitor.subprocess.check_call")
    def test_main_skip_directive_aborts_merge(self, mock_check_call, mock_call, mock_check_output):
        # Ready PR scenario but subject has skip ci
        mock_check_output.side_effect = [
            json.dumps([{"number": 42}]),
            json.dumps({
                "title": "Clean PR",
                "mergeStateStatus": "CLEAN",
                "statusCheckRollup": [{"name": "public-pr-merge-gate", "conclusion": "SUCCESS", "status": "COMPLETED"}]
            })
        ]

        # We mock sanitize_subject to simulate a scenario where a skip directive is
        # somehow retained in the subject to trigger the SystemExit check.
        with patch("tools.pr_janitor.sanitize_subject", return_value="Clean PR [skip ci] (#42)"):
            with self.assertRaises(SystemExit) as cm:
                pr_janitor.main(["--merge-one"])

        self.assertIn("refusing skip directive", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
