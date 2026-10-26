"""Fast safety regressions for the canonical public PR merge gate."""
import unittest
from unittest.mock import patch

from tools.ci_policy.verify_pr_tip import verify_pr_checkout


class ExactShaTest(unittest.TestCase):
    EXPECTED = 'a' * 40

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_exact_merge_parent_passes(self, run):
        run.return_value = self.EXPECTED + '\n'
        self.assertEqual(verify_pr_checkout(self.EXPECTED), self.EXPECTED)
        self.assertEqual(run.call_count, 1)

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_mismatched_head_fails_closed(self, run):
        run.return_value = 'b' * 40 + '\n'
        with self.assertRaisesRegex(ValueError, 'wrong PR head'):
            verify_pr_checkout(self.EXPECTED)
        self.assertEqual(run.call_count, 1)

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_no_git_log_lookup_needed_for_skip_text(self, run):
        run.return_value = self.EXPECTED + '\n'
        self.assertEqual(verify_pr_checkout(self.EXPECTED), self.EXPECTED)
        run.assert_called_once_with('rev-parse', '--verify', 'HEAD^2')

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_invalid_expected_sha_never_runs_git(self, run):
        with self.assertRaisesRegex(ValueError, 'invalid expected SHA'):
            verify_pr_checkout('refs/heads/main; echo unsafe')
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
