# DEUTSCH public Smart Merge Coordinator

Scope: \`moaz76943-creator/-offline-packs-store\` on exact live \`main\`.
No access to the private Flutter app, production pack publishing or license approvals.

## Live behavior

The \`Public Smart Merge Controller\` workflow is the sole scheduled integration
writer. Pull-request runs are read-only and test the complete current backlog.
Default-branch runs (on push, hourly schedule, or workflow_dispatch) compute a
paged live inventory of open PRs and changed paths, conflict graph, supersession
candidates, risk classifications and exact PR HEADs. JSON is retained as an
Actions artifact and the stable \`[MERGE-CONTROL]\` GitHub Issue is updated only
when snapshot status changes.

The default is **AUDIT**. Set repository Actions variable
\`SMART_MERGE_MODE=apply\` to opt into merging after the documented GitHub
branch-protection rule is enabled and the hosted audit passes. No variable is
needed to start read-only inventory. To stop merges, unset variable or set
\`SMART_MERGE_MODE=audit\`.

## Mandatory GitHub repository settings

The current public \`main\` was observed unprotected on 2026-10-13. The
coordinator cannot grant itself administrative repository protection permissions.
Configure Settings → Branches → branch protection rule for \`main\`:

- Require pull requests and at least one genuine approving human review.
- Require \`public-pr-merge-gate\` with strict up-to-date checks.
- Apply branch protection to admins; do not allow bypass.
- Disable force push and branch deletion.
- Ensure workflow \`GITHUB_TOKEN\` has the required allowed write permissions
  for PR squash merges and updating the ledger Issue.

The controller verifies this exact protection via the GitHub REST API; if
protection is absent or unreadable, **no PR is merged**. Existing rulesets
are not a substitute without a verified equivalent safety contract.
GitHub's Actions token might not be authorized to read branch protection;
this is a **hard blocker**, not permission to assume safety.

## Safety and semantic reconciliation

- Only non-Draft, unskipped final PR commits on current main can be candidates.
- PR SHA and main SHA are re-fetched immediately before any merge.
- Require actual \`success\`, not \`skipped\` or \`neutral\`, for the exact
  \`public-pr-merge-gate\` check from GitHub Actions and all required checks.
- Check the verified current head is not behind main and has approved
  exact-head independent human review.
- Never merge competing or overlapping open PR scopes on speculation; create
  an explicit reconciliation path and retain original PR history.
- Code changes require \`merge-safe-approved\` metadata and critical source
  rights / publication / CI changes require independent human review.
- The controller uses GitHub REST squash with \`sha\` lease; at most one merge
  per controller run, despite the configured upper bound, and then stops.
  The next run recomputes main and all other decisions from scratch.
- No force-push, auto-closing duplicate PRs, fabricated source approvals,
  release promotions, arbitrary PR script execution, or token use from
  untrusted pull_request code.

A completed read-only inventory is not equivalent to a successful merge.
Evidence records must explicitly distinguish verified outcomes from blockers.

## CI economics / availability

Use standard public \`ubuntu-latest\` and stdlib-only Python. Controller
timeout is 15 minutes with 4 bounded inventory readers. Event-based check
on coordinator changes plus one hourly reconciliation; no permanent server,
paid vendor, cache, secrets, or costly full-scale language compilation.
\`[skip ci]\` is permitted for intermediate commits, never the final
integration tip/squash message (per PR #161).

## Operational references

Live inventory: GitHub Actions → Public Smart Merge Controller → latest run
and attached \`smart-merge-ledger\` JSON artifact.
Stable issue: search open Issues for \`[MERGE-CONTROL]\`.
Fix order: missing branch protection → CI or approval missing → stale branch →
overlap/supersession reconciliation → re-run exact HEAD tests → controlled merge.

The workflow's PR check is **supplemental**; it is not added to required branch
checks to avoid gate circularity. Only the established \`public-pr-merge-gate\`
is the universal required check. Other critical gates remain mandatory.
