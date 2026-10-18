"""Regression: trusted repo automation issues must not be silently ignored."""
import unittest
from tools.gha_factory.dispatcher import controller
from tools.gha_factory.dispatcher import queue


class TrustedIssueTests(unittest.TestCase):
    def issue(self, actor):
        return {'number': 21, 'title': queue.PREFIX + 'a' * 64,
                'user': {'login': actor}}

    def test_owner_and_repo_actions_bot_are_allowed(self):
        self.assertTrue(controller.owned_queue_issue(self.issue(controller.OWNER)))
        self.assertTrue(controller.owned_queue_issue(self.issue('github-actions[bot]')))

    def test_ordinary_users_and_wrong_titles_are_rejected(self):
        self.assertFalse(controller.owned_queue_issue(self.issue('another-user')))
        self.assertFalse(controller.owned_queue_issue(self.issue('dependabot[bot]')))
        bad = self.issue('github-actions[bot]')
        bad['title'] = 'other-task'
        self.assertFalse(controller.owned_queue_issue(bad))

    def test_issue_discovery_includes_actions_bot(self):
        api = controller.GitHub(token='synthetic-test-token')
        owner = self.issue(controller.OWNER)
        owner['number'] = 1
        bot = self.issue('github-actions[bot]')
        bot['number'] = 2
        stranger = self.issue('stranger')
        stranger['number'] = 3
        api.request = lambda path, patch=None: [owner, bot, stranger]
        self.assertEqual([x['number'] for x in api.issues()], [1, 2])

    def test_pull_requests_are_never_queue_issues(self):
        bot = self.issue('github-actions[bot]')
        bot['pull_request'] = {'url': 'https://example.invalid/PR'}
        self.assertFalse(controller.owned_queue_issue(bot))


if __name__ == '__main__':
    unittest.main()
