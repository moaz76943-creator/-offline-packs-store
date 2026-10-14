"""Keep merge-required CI runnable: no skip-prone event/path conditions."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/public_pr_merge_gate.yml'


class MergeWorkflowContractTest(unittest.TestCase):
    def test_required_check_is_unfiltered_pull_request_event(self):
        source = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('  pull_request:', source)
        self.assertNotIn('pull_request_target:', source)
        self.assertNotIn('    paths:', source)
        self.assertNotIn('    paths-ignore:', source)
        self.assertNotIn('    if:', source)  # no conditional skipped required job
        self.assertIn('  public-pr-merge-gate:', source)

    def test_no_credentials_or_publish_permissions(self):
        source = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('permissions:\n  contents: read\n', source)
        self.assertIn('persist-credentials: false', source)
        self.assertNotIn('secrets.', source)
        self.assertNotIn('write', source)
        self.assertIn('verify_pr_tip.py', source)
        self.assertIn('github.event.pull_request.head.sha', source)


if __name__ == '__main__':
    unittest.main()
