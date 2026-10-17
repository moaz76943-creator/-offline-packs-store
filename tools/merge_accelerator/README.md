# DEUTSCH merge-backlog evidence inventory (read-only)

Complements the incumbent `tools/merge_coordinator/` without being a second merge authority. It never writes to GitHub and never marks any PR ready for merge: even `REVIEWED_CANDIDATE_NOT_AUTHORIZED` still requires current branch-policy checks, scoped tests, ownership, exact-HEAD revalidation, and the incumbent coordinator's explicit approval.

From Termux or another authorized shell with `python3`:

```sh
# Public repo only, ten most-recent PRs deeply inspected:
python3 tools/merge_accelerator/inventory.py --deep 10 --output "$HOME/public-merge-audit.json"

# Explicitly opt in to private repository reporting locally. Never publish report:
GH_TOKEN="$(gh auth token)" python3 tools/merge_accelerator/inventory.py --deep 10 --include-private --output "$HOME/private-merge-audit.json"

# Light, comprehensive count: fully records all open PRs, no per-PR API deep scans:
python3 tools/merge_accelerator/inventory.py --deep 0
```

To deeply inspect all PRs, specify `--deep 250` with a GitHub token and allow for GitHub API rate limits. The full audit makes up to five additional GET requests per PR, so **run manually, not on a schedule**, and review API limits first. All scans are bounded and terminate on unproven pagination rather than silently omitting PRs.

`[skip ci]` in a PR **title** is not sufficient evidence of a CI skip: only the final commit message is relevant. No CI check that is absent, failed, stale, pending, or unverified can be counted as PASS. On the private repo (whose policy is not fetched here) the tool always returns `CI_POLICY_UNVERIFIED` rather than guessing.

Run focused tests with:

```sh
python3 -m unittest discover -s tests/merge_accelerator -p 'test_*.py' -v
```

This never changes branch protection, skips review, merges an unapproved PR, changes a Flutter file, or publishes a pack. All private-repo results must stay local. Do not use report content as a substitute for current GitHub evidence.