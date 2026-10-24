"""Verify privileged merge coordination remains event-driven and trusted-main only."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/public_merge_coordinator.yml"


class TriggerSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_existing_checks_trigger_after_completion(self):
        self.assertIn('workflow_run:', self.workflow)
        self.assertIn('workflows: ["Public PR Merge Gate", "Validate JSON Files"]', self.workflow)
        self.assertIn('types: [completed]', self.workflow)
        self.assertIn("github.event.workflow_run.event == 'pull_request'", self.workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", self.workflow)

    def test_recovery_polling_is_bounded_and_off_peak(self):
        self.assertIn("cron: '13 * * * *'", self.workflow)
        self.assertEqual(self.workflow.count('    - cron:'), 1)

    def test_write_job_runs_trusted_main_only(self):
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("github.repository == 'moaz76943-creator/-offline-packs-store'", self.workflow)
        self.assertIn('persist-credentials: false\n          ref: main', self.workflow)
        self.assertIn('python3 tools/merge_coordinator/protection_gate.py', self.workflow)
        self.assertIn("if: steps.protection.outputs.allowed == 'true'", self.workflow)
        self.assertNotIn('pull_request_target:', self.workflow)


if __name__ == "__main__":
    unittest.main()
