# Public PR CI and merge policy — zero-conflict contract

**Scope:** `moaz76943-creator/-offline-packs-store`, canonical `main` only.
This policy resolves the contradiction between a blanket `[skip ci]` habit and
GitHub-required PR checks. It does not change private Flutter CI or authorize
release of unapproved language packs.

## Rule: never skip checks on the final integration commit

- Intermediate draft/WIP commits may include `[skip ci]` to suppress redundant runs.
- **The HEAD commit of a PR intended for review or merge MUST NOT contain**
  `[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]`, `[actions skip]`, or a
  `skip-checks: true` trailer. This is an explicit exception to the old blanket
  commit-tag convention for CI-bearing PRs.
- Never put a skip directive in the final **squash merge commit title/body**;
  otherwise post-merge `push` checks on `main` may also be suppressed. Rewrite
  only the proposed merge message, not Git history.
- Do not rewrite Jules' original branches or bulk-promote 99 draft PRs. For a
  chosen legacy contribution with a skipped tip, create a separate, reviewed
  integration branch from current `main`, apply the selected change and use a
  **non-skipping final integration commit**. Avoid merging superseded proposals.
- Merge only after the PR is out of Draft, GitHub reports no conflicts, the
  latest PR head matches reviewed evidence, all required checks are green,
  relevant scoped tests are verified, and the coordinator rechecks fresh `main`.

## Required check and scope

`.github/workflows/public_pr_merge_gate.yml` defines one unfiltered
`pull_request` job named **`public-pr-merge-gate`**. Because the workflow has no
path filters and the required job has no job-level `if`, a valid non-skipped PR
receives the check even when it only edits documentation or a small isolated
module. It runs on GitHub's ephemeral standard `ubuntu-latest` public runner,
with `contents: read`, no persistently stored checkout credential, no secrets,
no artifact upload and a 12-minute cap.

The job checks out GitHub's synthetic PR merge commit, compares its second
parent with `github.event.pull_request.head.sha`, rejects skip directives on
that exact tip, then runs policy tests, the canonical registry validator and
fixture-only SQLite pack regression. This is a **baseline check**, not proof
that every source-, license-, provenance- or publication-specific test passed.
Required scoped checks and human approvals remain additional integration gates.
Do not interpret `skipped`, `neutral`, `NOT_RUN` or absent evidence as a passing
production verification, even if GitHub allows a skipped job in protection.

## Branch protection setup after first proven hosted run

1. In GitHub Settings → Branches, protect `main` and require the exact
   `public-pr-merge-gate` status check **after** GitHub has successfully run it.
2. Require PR review, restrict destructive pushes/deletions and prefer a strict
   up-to-date check policy for serialized, dependency-aware integration.
3. Keep one authorized merge coordinator. Enable GitHub Auto-merge separately
   if desired; it cannot merge drafts or bypass unsatisfied required checks.
4. Existing path-filtered workflows may remain **additional** evidence but must
   not be the only universally required check. Never weaken an existing
   release/rights gate to clear a queue.

`workflow_dispatch` can help investigate a stalled change, but its workflow-job
check does **not** satisfy branch-protection-required checks on a PR. Avoid
`pull_request_target` for running untrusted PR code. The safe recovery for an
old `[skip ci]` PR is a non-skipping integration tip with standard `pull_request`
checks, rather than a fabricated green check or admin bypass.

## Failure classifications

- `BLOCKED_SKIP_CI`: Latest PR head contains a skip instruction and CI did not run.
- `NOT_RUN`: No exact-head hosted check exists. Do not label PASS.
- `FAIL`: The named job failed; repair before merging.
- `BLOCKED_DEPENDENCY`: CI is green but release/rights/source/compatibility gate fails.
- `READY`: Latest exact SHA has required check PASS, relevant scoped evidence,
  approvals and no merge/dependency conflict; immediately recheck before squash.

GitHub Actions on standard hosted public runners incurs no additional compute
billing; larger runners, private runners, paid services and unbounded artifact
retention are excluded from this policy.
