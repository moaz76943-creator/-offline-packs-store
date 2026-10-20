"""Regression tests for precise public PR scoped test selection."""
import unittest
from unittest.mock import patch

from tools.ci_policy.run_scoped_pr_tests import select_suites, execute_suites


class ScopedTestSelectionTests(unittest.TestCase):
    def test_single_subsystem_runs_only_its_own_tests(self):
        self.assertEqual(select_suites(["tools/media_optimizer/test_compiler.py"]), ("media",))
        self.assertEqual(select_suites(["tools/pronunciation_metadata/test_metadata.py"]), ("pronunciation",))
        self.assertEqual(select_suites(["tools/audio_pronunciation/test_admission.py"]), ("audio",))
        self.assertEqual(select_suites(["tools/ingestion_circuit_breaker/test_gate.py"]), ("ingestion",))
        self.assertEqual(select_suites(["tools/final_release_evidence/test_compiler.py"]), ("final_evidence",))

    def test_shared_provenance_logic_runs_all_affected_tests(self):
        self.assertEqual(select_suites(["legal/ledger/admission.py"]),
                         ("media", "pronunciation", "audio", "ingestion", "final_evidence"))
        self.assertEqual(select_suites(["tools/contribution_gate/evidence.py"]),
                         ("pronunciation", "audio"))

    def test_unrelated_or_unsafe_path_does_not_run_incorrect_suite(self):
        self.assertEqual(select_suites(["docs/readme.md", "tools/other/module.py"]), ())
        self.assertEqual(select_suites(["tools/media_optimizer_backup/file.py"]), ())
        self.assertEqual(select_suites(["tools\\media_optimizer\\test_compiler.py"]), ())

    def test_multiple_paths_run_each_suite_once_in_stable_order(self):
        self.assertEqual(select_suites(["tools/audio_pronunciation/test_admission.py",
                                       "tools/media_optimizer/compiler.py",
                                       "tools/audio_pronunciation/admission.py"]),
                         ("media", "audio"))

    @patch("tools.ci_policy.run_scoped_pr_tests.subprocess.run")
    def test_failing_targeted_suite_does_not_get_swallowed(self, run):
        from subprocess import CalledProcessError
        run.side_effect = CalledProcessError(1, ["python", "-m", "unittest"])
        with self.assertRaises(CalledProcessError):
            execute_suites(("media",))

    @patch("tools.ci_policy.run_scoped_pr_tests.subprocess.run")
    def test_empty_selection_runs_nothing(self, run):
        execute_suites(())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
