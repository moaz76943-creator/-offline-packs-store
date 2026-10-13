"""Fast safety regressions for the canonical public PR merge gate."""
import unittest
from unittest.mock import patch

from tools.ci_policy.verify_pr_tip import verify_pr_checkout, skip_directive


class SkipPolicyTest(unittest.TestCase):
    def test_unskipped_tip_is_eligible(self):
        self.assertIsNone(skip_directive('ci: verify public PR before merge\n'))

    def test_all_github_skip_forms_block_a_mergable_tip(self):
        for token in ('[skip ci]', '[ci skip]', '[no ci]', '[skip actions]', '[actions skip]'):
            with self.subTest(token=token):
                self.assertIsNotNone(skip_directive(f'feat: code {token}\n'))

    def test_skip_directive_anywhere_in_commit_message_blocks(self):
        self.assertIsNotNone(skip_directive('Fix importer\n\nCo-authored details: [SKIP CI]\n'))

    def test_skip_checks_trailer_is_rejected(self):
        self.assertIsNotNone(skip_directive('feat: gate\n\n\nskip-checks: true\n'))
        self.assertIsNone(skip_directive('Docs: skip-checks: true is disallowed'))


class ExactShaTest(unittest.TestCase):
    EXPECTED = 'a' * 40

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_exact_merge_parent_and_tip_without_skip_pass(self, run):
        run.side_effect = [self.EXPECTED + '\n', 'ci: verify\n']
        self.assertEqual(verify_pr_checkout(self.EXPECTED), self.EXPECTED)
        self.assertEqual(run.call_count, 2)

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_mismatched_head_fails_closed(self, run):
        run.return_value = 'b' * 40 + '\n'
        with self.assertRaisesRegex(ValueError, 'wrong PR head'):
            verify_pr_checkout(self.EXPECTED)
        self.assertEqual(run.call_count, 1)

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_skipped_tip_fails_closed(self, run):
        run.side_effect = [self.EXPECTED + '\n', 'fix: flaky [skip ci]\n']
        with self.assertRaisesRegex(ValueError, 'skip directive'):
            verify_pr_checkout(self.EXPECTED)

    @patch('tools.ci_policy.verify_pr_tip.git_output')
    def test_invalid_expected_sha_never_runs_git(self, run):
        with self.assertRaisesRegex(ValueError, 'invalid expected SHA'):
            verify_pr_checkout('refs/heads/main; echo unsafe')
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
