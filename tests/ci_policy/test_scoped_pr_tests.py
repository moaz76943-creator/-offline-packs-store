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
        self.assertEqual(select_suites(["tools/pack_manifest/builder.py"]), ("pack_manifest",))
        self.assertEqual(select_suites(["tools/lexical_quality/validator.py"]), ("lexical_quality",))
        self.assertEqual(select_suites(["tools/open_export/exporter.py"]), ("open_export",))
        self.assertEqual(select_suites(["tools/community_automation/gate.py"]), ("community_automation",))
        self.assertEqual(select_suites(["community/contributions/ingest.py"]), ("community_intake",))
        self.assertEqual(select_suites(["tests/community/contributions/test_ingest.py"]), ("community_intake",))
        self.assertEqual(select_suites(["legal/licensing/ledger.py"]), ("licensing",))
        self.assertEqual(select_suites(["legal/licensing/test_ledger.py"]), ("licensing",))
        self.assertEqual(select_suites(["catalog/test_registry.py"]), ("registry_unit",))
        self.assertEqual(select_suites(["catalog/validate_registry.py"]), ("registry_unit",))
        self.assertEqual(select_suites(["utils.py"]), ("utils",))
        self.assertEqual(select_suites(["tests/test_utils.py"]), ("utils",))
        self.assertEqual(select_suites(["tools/merge_accelerator/inventory.py"]), ("inventory",))
        self.assertEqual(select_suites(["tests/merge_accelerator/test_inventory.py"]), ("inventory",))

    def test_shared_provenance_logic_runs_all_affected_tests(self):
        self.assertEqual(select_suites(["legal/ledger/admission.py"]),
                         ("media", "pronunciation", "audio", "ingestion", "final_evidence", "corpus_dedupe", "provenance_release", "lexicon_sanitizer", "artifact_digest", "open_index", "repro_build", "pack_manifest", "lexical_quality", "open_export", "community_automation", "community_intake", "ledger", "registry_unit"))
        self.assertEqual(select_suites(["tools/contribution_gate/evidence.py"]),
                         ("pronunciation", "audio"))

    def test_ledger_evidence_uses_existing_ledger_suite_not_unrelated_missing_licensing(self):
        for path in ("legal/ledger/admission.py",
                     "legal/ledger/evidence/agent-harvest-20261025-batch6/receipt.json"):
            selected = select_suites([path])
            self.assertIn("ledger", selected)
            self.assertNotIn("licensing", selected)
            self.assertEqual(selected.count("ledger"), 1)
            self.assertEqual(select_baseline_checks([path]), ("policy", "registry", "sqlite"))
        self.assertEqual(select_suites(["legal/licensing/ledger.py"]), ("licensing",))
        self.assertEqual(
            select_suites(["legal/ledger/sources.json", "legal/licensing/ledger.py"]).count("licensing"), 1)

    def test_community_intake_keeps_sensitive_baseline_and_is_not_skipped(self):
        self.assertEqual(
            select_baseline_checks(["community/contributions/ingest.py"]),
            ("policy", "registry", "sqlite"))
        self.assertEqual(
            select_baseline_checks(["tests/community/contributions/test_ingest.py"]), ())
        self.assertEqual(
            select_suites(["legal/ledger/sources.json",
                           "tests/community/contributions/test_ingest.py"]).count("community_intake"),
            1)

    def test_licensing_regressions_keep_full_safety_baseline(self):
        sensitive = ("policy", "registry", "sqlite")
        for path in ("legal/licensing/ledger.py", "legal/licensing/test_ledger.py"):
            self.assertEqual(select_baseline_checks([path]), sensitive)
            self.assertEqual(select_suites([path]), ("licensing",))
        self.assertEqual(
            select_suites(["legal/licensing/ledger.py",
                           "legal/licensing/test_ledger.py"]).count("licensing"), 1)
        self.assertEqual(
            select_suites(["legal/ledger/admission.py",
                           "legal/licensing/ledger.py"]).count("licensing"), 1)

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

    def test_root_prose_docs_need_no_global_database_or_catalog_tests(self):
        for path in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md"):
            self.assertEqual(select_baseline_checks([path]), ())
        self.assertEqual(
            select_baseline_checks(["README.md", "docs/design/notes.md"]), ())

    def test_sensitive_root_files_and_mixed_code_still_require_full_baseline(self):
        baseline = ("policy", "registry", "sqlite")
        for path in ("LICENSE", "CODEOWNERS", "pubspec.yaml",
                     "README.md/another.md", "tools/other/new.py"):
            self.assertEqual(select_baseline_checks(["README.md", path]), baseline)
        self.assertEqual(select_baseline_checks(["docs/security/review.md"]), baseline)

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

    def test_merge_orchestration_changes_use_focused_contracts(self):
        self.assertEqual(
            select_baseline_checks(["tools/merge_coordinator/auto_policy.py"]),
            ("coordinator",))
        self.assertEqual(
            select_baseline_checks([".github/workflows/public_merge_coordinator.yml"]),
            ("coordinator",))
        self.assertEqual(
            select_baseline_checks([".github/workflows/validate_json.yml"]),
            ("coordinator", "json_security"))
        self.assertEqual(
            select_baseline_checks(["tests/ci_security/test_validate_json.py"]),
            ("json_security",))
        self.assertEqual(
            select_baseline_checks(["tools/ci_policy/run_scoped_pr_tests.py",
                                    "tools/merge_coordinator/auto_policy.py",
                                    ".github/workflows/validate_json.yml"]),
            ("policy", "coordinator", "json_security"))

    def test_advisory_janitor_uses_one_required_gate_with_focused_tests(self):
        for path in ("tools/pr_janitor.py", "tools/test_pr_janitor.py",
                     ".github/workflows/pr_janitor.yml"):
            self.assertEqual(select_baseline_checks([path]), ("janitor",))
        self.assertEqual(
            select_baseline_checks(["tools/pr_janitor.py",
                                    ".github/workflows/public_merge_coordinator.yml"]),
            ("coordinator", "janitor"))
        self.assertEqual(
            select_baseline_checks([".github/workflows/pr_janitor.yml",
                                    "tools/ci_policy/run_scoped_pr_tests.py"]),
            ("policy", "janitor"))

    def test_janitor_changes_do_not_bypass_shared_safety_baseline(self):
        self.assertEqual(
            select_baseline_checks(["tools/pr_janitor.py", "legal/ledger/sources.json"]),
            ("policy", "registry", "sqlite"))

    def test_advisory_scout_has_no_separate_pr_verification_runner(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] /
                  ".github/workflows/pr_janitor.yml").read_text(encoding="utf-8")
        self.assertNotIn("  pull_request:", source)
        self.assertNotIn("  verify:", source)
        self.assertIn("  schedule:", source)
        self.assertIn("  workflow_dispatch:", source)
        self.assertIn("    - cron: '17 */4 * * *'", source)
        self.assertIn("      pull-requests: write", source)

    def test_sensitive_shared_change_with_coordinator_still_runs_full_baseline(self):
        self.assertEqual(
            select_baseline_checks(["tools/merge_coordinator/auto_policy.py",
                                    "legal/ledger/sources.json"]),
            ("policy", "registry", "sqlite"))

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
