# Public PR CI and merge policy — skip-marker-neutral

**Scope:** `moaz76943-creator/-offline-packs-store`, canonical `main`.

## Commit messages

The repository does **not** ban `[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]`, `[actions skip]`, or `skip-checks: true` in existing or new commits. Neither PR eligibility, merge-coordinator authorization, nor read-only backlog classification rejects a commit solely because it contains such text.

**GitHub scheduling is a separate matter:** native `push` and `pull_request` Actions workflows may not start for a tip carrying a recognized skip instruction. This repository cannot declare a job that never ran successful. The existing required `public-pr-merge-gate`, any relevant scoped checks, and applicable release, security and licensing checks must actually complete successfully on the exact current head SHA.

For skipped legacy tips with missing checks, preserve original commits and use a reviewed follow-up/integration tip with no skip instruction when a required GitHub-hosted check needs to run. This is a scheduling workaround, **not** a requirement to rewrite the original message or a prohibition of skip markers. Do not force-push or fabricate a successful status. When squashing an eligible PR, the merge message may be normalized to allow the real post-merge `main` workflows to run.

## Required hosted gate

`.github/workflows/public_pr_merge_gate.yml` defines one mandatory unfiltered `pull_request` job named `public-pr-merge-gate`. If GitHub schedules it, the job checks the second parent of the synthetic PR merge tree against the exact expected PR head SHA and runs the selected real regression suites. It does not inspect or reject skip tokens in the source message. It uses public standard GitHub-hosted runners, read-only contents, no persisted checkout credentials, and a 12-minute timeout.

An absent, skipped, pending, stale or failing result is **not** a PASS. Scope-specific pack integrity, source rights, provenance, licensing and release admission remain independent requirements; a low-risk docs PR does not need unrelated heavy checks. `workflow_dispatch` does not automatically satisfy the PR's required status check. Never use `pull_request_target` to execute untrusted PR code.

## Protected merge

- Keep the canonical branch protection and exact-head `public-pr-merge-gate` requirement.
- Merge only a ready, conflict-free, authorized PR after actually required checks and reviews have passed and the current target SHA is rechecked.
- Do not claim a pack is production-ready without license provenance, integrity checks and verified receipts.
- Reuse the existing coordinator; do not introduce new approvals, workers or blocking paperwork to manage skip-token messages.
- Do not reinterpret GitHub's own workflow scheduling as a repository policy veto against the original commit.

## Diagnostic states

- `NOT_RUN`: Required exact-head hosted check absent, regardless of commit-message text.
- `FAIL`: Required real check failed.
- `BLOCKED_DEPENDENCY`: Real release/rights/source/compatibility gate failed.
- `READY`: Correct SHA, required passing checks, applicable review, and no merge/dependency conflict.

Use targeted regressions and bounded CI rather than turning skipped jobs into fictitious successes. The zero-additional-billing constraint remains in force.
