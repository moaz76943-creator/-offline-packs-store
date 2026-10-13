# Security verification log — 2026-10-13

Execution environment: isolated local Python 3.13 sandbox, Linux.
Repository target: moaz76943-creator/-offline-packs-store.
Base branch: live main at branch creation (the base advanced during integration).
Scope: only community/contributions, community/review, tools/open_export.

Command:

    python -m unittest discover -s tools/open_export -p test_lifecycle.py -v

Result:

    test_approval_requires_independent_keys_and_hash_binding ... ok
    test_archive_traversal_tar_symlinks_zip_bombs ... ok
    test_cached_export_rejects_compressed_zip_bomb ... ok
    test_concurrent_same_submission_idempotent ... ok
    test_corrections_invalidate_prior_approval ... ok
    test_deterministic_export_and_failed_run_preserves_last_good ... ok
    test_export_blocks_unknown_languages_and_oversized_attribution ... ok
    test_export_reject_unreviewed_tampering_and_ledger_mismatch ... ok
    test_export_unsafe_symlinks_and_bounded_size ... ok
    test_intake_duplicate_keys_and_fixture_rejection ... ok
    test_ledger_artifact_and_kind_must_match ... ok
    test_operator_cli_requires_signed_decisions ... ok
    test_quarantine_preserves_rejected_bytes_and_reason ... ok
    test_reject_path_traversal_and_symlink_in_review ... ok
    test_review_handoff_restart_recovery ... ok
    test_too_many_tar_members_are_rejected ... ok

    ----------------------------------------------------------------------
    Ran 16 tests in 0.206s

    OK

The operator CLI test intentionally exercises and rejects a forged signing token.
That rejection is expected and is not a test failure.

The test suite uses synthetic in-memory/temporary evidence, temporary keys, and
a simulated legal-admission evaluator in its positive-path fixtures. Those
fixtures are NOT proof of any production source rights and must not be promoted.

GitHub-hosted CI was not run because commits were tagged [skip ci] per owner
constraint. The production rights ledger remains empty, so real exports should
continue to fail closed. An integration-coordinator review and independent
repository-runtime verification remain mandatory before merge.
