"""Ensure the existing public gate actually selects community intake regressions."""
import unittest

from tools.ci_policy.run_scoped_pr_tests import select_suites


class CommunityIntakeCiSelectionTests(unittest.TestCase):
    def test_existing_ingest_source_and_regressions_are_routed(self):
        for path in ("community/contributions/ingest.py",
                     "tests/community/contributions/test_ingest.py",
                     "tests/community/contributions/test_ci_selection.py"):
            with self.subTest(path=path):
                self.assertIn("community_intake", select_suites([path]))

    def test_shared_source_ledger_triggers_intake_regression(self):
        self.assertIn("community_intake", select_suites(["legal/ledger/sources.json"]))


if __name__ == "__main__":
    unittest.main()
