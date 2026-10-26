# Verified public merge coordinator

This coordinator integrates exact-SHA authorized PRs from the existing
`approved.json` record; when it is empty, the incumbent coordinator may also
select tightly scoped low-risk PRs with real hosted evidence. No extra merge writer is introduced.

For every entry, pin PR number, exact head SHA, preceding main SHA,
`integration-coordinator` ownership, permitted paths, exact passing check names
(at minimum the required `public-pr-merge-gate`, which already runs
changed-path-selected scoped regressions),
independent reviewer logins, dependencies, and mutually exclusive PR IDs.

A sample record (illustration only; do not enroll blindly):

```json
{"number":900,"head_sha":"<40-hex>","main_sha":"<40-hex>",
 "owner":"integration-coordinator","paths":["tools/safe_module/"],
 "checks":["public-pr-merge-gate"],
 "reviewers":["independent-reviewer"],"dependencies":[],"excludes":[]}
```

Extra check names may still be listed for genuinely separate verification;
all such listed checks must pass on the exact PR SHA. No manufactured second
status is required. The authorization update follows existing PR rules.
The authorization-only change to `approved.json` may advance main by exactly
one commit after its recorded SHA. All other main changes invalidate approvals.

The hourly scheduled workflow uses standard public GitHub-hosted runners,
checks and re-checks PR and main SHA, reviews, exact-head hosted check runs,
changed paths and dependencies. It can promote an otherwise-verified draft
but never merges in the same run as the promotion. Only one SHA-guarded
squash may be executed per run. No published asset, license ledger,
production pack, workflow or shared source path is eligible for this generic
automation.

To run contracts locally:

```sh
python3 -m unittest discover -s tools/merge_coordinator -p 'test_*.py' -v
```

**Known restriction:** The connector cannot access branch-protection settings
(403). GitHub REST merge requests atomically guard the PR head, but not
the expected main SHA, so external writers must be restricted using repository
branch protection or a trusted exclusive merge authority. Do not treat
`skipped`, `neutral`, `NOT_RUN` or missing CI as passing checks.
