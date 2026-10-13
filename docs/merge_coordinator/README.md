# Smart PR Merge — DEUTSCH بالعربي

Canonical target: public moaz76943-creator/-offline-packs-store, branch main.

## Default: DRY_RUN

The coordinator cannot turn itself on. Independently configure protected main, strict up-to-date status checks, qualified review, no admin bypass, no force pushes and no branch deletion. Require the exact public-pr-merge-gate context plus relevant scoped verification checks. Only after real hosted PASS evidence should the owner set repository variable SMART_MERGE_ENABLED=true. Missing or unreadable protection means fail closed, including 403.

## Operating architecture

- A single GitHub Actions concurrency group serializes writers. Cancel-in-progress is disabled; each reconciliation can merge at most one PR.
- Event-driven workflow_run handling follows Public PR Merge Gate and Validate JSON Files. Scheduled reconciliation every six hours covers missed events, including GITHUB_TOKEN event-trigger restrictions.
- Privileged runs always check out trusted main, never untrusted PR contents. PR test runs use a read-only token. pull_request_target is not used.
- Repository APIs provide paginated PR inventory, exact head commits, files, reviews, check runs, approvals and branch protection. Incomplete inventory prevents every merge.
- Explicit Depends-On: #123 lines form a dependency DAG. Unresolved dependencies block only their dependents.
- Exact touched-file intersections create conservative conflict edges. Only independently verified duplicate head SHA and file sets get DUPLICATE; unverifiable supersession stays a conflict.
- Draft PRs are not bulk promoted. Final head skip-CI directives prohibit merge, and no original branches are destructively rewritten.
- Security workflows, publication, license/source rights, SQLite schemas and migrations, manifests, generated language content and shared high-risk contracts never receive mechanical auto-approval.
- Every output is machine-readable JSON and an Arabic summary. Seven-day Actions artifacts store the full inventory. Once enabled, idempotent changed-decision receipts also persist as PR comments.
- Before merge, the coordinator reloads main SHA, exact PR head, state, qualified reviews, check outcomes, protected branch policy and all pending PR head signatures. Then uses GitHub squash merge pinned to expected PR head.
- GitHub REST has no atomic expected-main-SHA condition on a merge. Strict protection, a unique workflow lease and immediate before/after checks minimize, but cannot fully eliminate, races with external writers. Disable other merge writers before activation.
- Post-merge validation failure causes incident stop, not destructive automatic rollback.

## Human activation blockers

1. Protect main and require current, strict public-pr-merge-gate plus other applicable scoped checks and at least one independent approval.
2. Confirm REST branch-protection inspection is readable to the coordinator identity. The ordinary GITHUB_TOKEN may lack administration-read access. Do not bypass protection or add sensitive secrets casually.
3. Review the new workflow and obtain actual hosted smart-merge-tests PASS on its exact integration head.
4. Establish independent ownership, release, security and licensing verification where changes require them.
5. Only then set SMART_MERGE_ENABLED=true. The Actions report choice stays read-only.

## Testing and phone operation

Run: python3 -m unittest discover -s tests/merge_coordinator -p 'test_*.py' -v

Read-only status: python3 -m tools.merge_coordinator.cli --output merge-status.json

On mobile: GitHub → Actions → Smart PR Merge Coordinator → Run workflow → report. Inspect Arabic job summary and smart-pr-merge artifact.

The new PR has exclusive file scope: tools/merge_coordinator, tests/merge_coordinator, docs/merge_coordinator and the new smart_pr_merge.yml. It modifies no existing CI, production packs, licenses, source datasets or public main history.