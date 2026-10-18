# Read-only engineering evidence verifier

This module verifies engineering task execution evidence, not release eligibility. It does not modify the GitHub repositories, CI policies, source-rights ledger, dispatcher, or release finalizer. No assertions from PR bodies, comments, Issue receipts, or self-reported test counts qualify as CI success.

## Use

Requires Python 3 and authenticated GitHub CLI (gh auth status). Run from the repository root:

    python3 -m tools.engineering_evidence.cli \
      --repo moaz76943-creator/-offline-packs-store \
      --pr 177 --task-id DEUTSCH-RECOVERY-06 --owner reviewer \
      --output-dir "$HOME/deutsch-reports/engineering-evidence" \
      --verify-artifacts

API reads use gh api --method GET; GitHub permissions must independently allow the target private repository. Artifact verification downloads archives only when --verify-artifacts is supplied; each archive is streamed and capped at 32 MiB. If an archive exceeds this limit or its provider SHA256 is unavailable, the report is blocked. No Tokens or raw private-file contents are written to the public repository. Optional --private-url adds only a link and a SHA256 of the link to the local report; **do not commit reports about private work to a public repository**.

Reports are JSON and Markdown with content-hash filenames, created atomically and never overwritten. Statuses: VERIFIED (matching PR-head successful GitHub workflow evidence, eligible check runs, all recorded artifacts verified), NOT_RUN (no matching workflow), FAIL, STALE_EVIDENCE, and BLOCKED. VERIFIED means independently confirmed execution evidence, **not** branch protection, all required checks, source licensing, release readiness, or authorization to merge. The observed workflow name and GitHub run/attempt IDs are reported; the precise shell test_commands cannot be authenticated from an API run summary and therefore remain [] rather than invented. CI checks are evaluated only for the exact PR SHA. Fail-closed on incomplete file/run/check/artifact lists and changing base or PR head.

## Evidence fields

schema_version, task_id, repository, base_branch, base_head_sha, pr_head_sha, pr_number, pr_url, agent_owner, changed_files, test_commands, test_results, ci_run_id, ci_run_attempt, ci_runs, artifact_sha256, artifacts, execution_timestamp, final_status, reasons, private_evidence, publication_approved=false, merge_authorized=false, command_execution_independently_verified=false.

artifact_sha256 is populated for one independently verified artifact. For multiple artifacts, see artifacts[].sha256; no digest is promoted solely from an API metadata claim.

Local tests:

    python3 -m unittest discover -s tests/engineering_evidence -p 'test_*.py' -q

## Existing systems retained

- PR #171: content release evidence compiler (not an engineering task execution ledger)
- PR #148: source-blocked offline audit; correctly distinguishes NOT_RUN
- PR #146: impacted-test discovery, not hosted proof of execution
- Private PR #140: production app acceptance gate, not public CI attestation

This adapter does not replace or merge those systems. To consider release or deployment, separately apply the authoritative Source Ledger, Finalizer, private ProductionAcceptanceGate, and branch protection checks.
