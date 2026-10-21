"""Regression tests for precise public PR scoped test selection."""
import unittest
from unittest.mock import patch

from tools.ci_policy.run_scoped_pr_tests import (select_suites, execute_suites,
    select_baseline_checks, execute_baseline_checks)


class ScopedTestSelectionTests(unittest.TestCase):
    def test_single_subsystem_runs_only_its_own_tests(self):
        self.assertEqual(select_suites(["tools/media_optimizer/test_compiler.py"]), ("media",))
        self.assertEqual(select_suites(["tools/pronunciation_metadata/test_metadata.py"]), ("pronunciation",))
        self.assertEqual(select_suites(["tools/audio_pronunciation/test_admission.py"]), ("audio",))
        self.assertEqual(select_suites(["tools/ingestion_circuit_breaker/test_gate.py"]), ("ingestion",))
        self.assertEqual(select_suites(["tools/final_release_evidence/test_compiler.py"]), ("final_evidence",))
        self.assertEqual(select_suites(["tools/corpus_dedupe/dedupe.py"]), ("corpus_dedupe",))
        self.assertEqual(select_suites(["tools/corpus_dedupe/test_dedupe.py"]), ("corpus_dedupe",))
        self.assertEqual(select_suites(["tools/provenance_release/compiler.py"]), ("provenance_release",))
        self.assertEqual(select_suites(["tools/lexicon_sanitizer/engine.py"]), ("lexicon_sanitizer",))
        self.assertEqual(select_suites(["tools/artifact_digest/engine.py"]), ("artifact_digest",))
        self.assertEqual(select_suites(["tools/open_index/builder.py"]), ("open_index",))
        self.assertEqual(select_suites(["tools/repro_build/compiler.py"]), ("repro_build",))

    def test_shared_provenance_logic_runs_all_affected_tests(self):
        self.assertEqual(select_suites(["legal/ledger/admission.py"]),
                         ("media", "pronunciation", "audio", "ingestion", "final_evidence", "corpus_dedupe", "provenance_release", "lexicon_sanitizer", "artifact_digest", "open_index", "repro_build"))
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

    def test_independent_scoped_code_avoids_unrelated_global_fixtures(self):
        self.assertEqual(
            select_baseline_checks(["tools/open_index/builder.py",
                                    "tools/open_index/test_builder.py"]), ())
        self.assertEqual(
            select_baseline_checks(["tools/artifact_digest/engine.py"]), ())
        self.assertEqual(
            select_baseline_checks(["docs/design/notes.md"]), ())

    def test_ci_policy_edits_run_policy_without_sqlite_or_catalog(self):
        self.assertEqual(
            select_baseline_checks(["tools/ci_policy/run_scoped_pr_tests.py"]),
            ("policy",))
        self.assertEqual(
            select_baseline_checks(["tools/media_optimizer/compiler.py",
                                    "tests/ci_policy/test_scoped_pr_tests.py"]),
            ("policy",))
        self.assertEqual(
            select_baseline_checks([".github/workflows/public_pr_merge_gate.yml"]),
            ("policy",))

    def test_shared_sensitive_or_unrecognized_changes_still_require_full_baseline(self):
        mandatory = ("policy", "registry", "sqlite")
        for paths in ([], ["tools/pack_v2/pipeline.py"],
                      ["catalog/language_registry.v1.json"],
                      ["legal/ledger/sources.json"],
                      ["tools/unclassified/new.py"],
                      ["docs/security/review.md"],
                      ["README.md", "tools/other/new.py"],
                      ["tools\\open_index\\builder.py"],
                      ["tools/open_index/../../secrets.txt"]):
            with self.subTest(paths=paths):
                self.assertEqual(select_baseline_checks(paths), mandatory)

    @patch("tools.ci_policy.run_scoped_pr_tests.subprocess.run")
    def test_no_baseline_does_not_spawn_extraneous_checks(self, run):
        execute_baseline_checks(())
        run.assert_not_called()

    @patch("tools.ci_policy.run_scoped_pr_tests.subprocess.run")
    def test_failed_required_baseline_propagates(self, run):
        from subprocess import CalledProcessError
        run.side_effect = CalledProcessError(1, ["python", "-m", "unittest"])
        with self.assertRaises(CalledProcessError):
            execute_baseline_checks(("policy",))
        self.assertTrue(run.call_args.kwargs["check"])

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
