"""Guard the single-writer contract for scheduled public PR automation."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github' / 'workflows'


class SingleScheduledMergeWriterTests(unittest.TestCase):
    def test_legacy_label_janitor_does_not_merge(self):
        text = (WORKFLOWS / 'pr_janitor.yml').read_text(encoding='utf-8')
        self.assertIn('python3 tools/pr_janitor.py', text)
        self.assertNotIn('--merge-one', text)
        self.assertIn('schedule:', text)

    def test_agent_janitor_is_advisory_only(self):
        text = (WORKFLOWS / 'agent_janitor.yml').read_text(encoding='utf-8')
        self.assertIn('python3 -m tools.agents.cli janitor', text)
        self.assertNotIn("'gh', 'pr', 'merge'", text)
        self.assertNotIn('pulls/{number}/update-branch', text)
        self.assertIn('pull-requests: read', text)
        self.assertIn('schedule:', text)

    def test_incumbent_merge_coordinator_stays_scheduled(self):
        text = (WORKFLOWS / 'public_merge_coordinator.yml').read_text(encoding='utf-8')
        self.assertIn('python3 tools/merge_coordinator/coordinator.py', text)
        self.assertIn('public-canonical-main-integration-authority', text)
        self.assertIn('schedule:', text)


if __name__ == '__main__':
    unittest.main()
