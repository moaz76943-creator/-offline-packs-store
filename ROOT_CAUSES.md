# Root causes

Grouped from the open PR queue on 2026-10-18. The required check `public-pr-merge-gate` was not flaky: the last 30 runs succeeded. What repeated was a fixture and ruleset problem.

## 1. Hand-copied ledger fixtures drift from the schema

Almost every tool builds its own `APPROVED_FOR_REDISTRIBUTION` dict. `legal/ledger/sources.json` is an empty list, so there is no shared source to regenerate. When admission gains a field, suites that call `evaluate` fail closed as `source_not_approved` and drop the audio checks the test was written for. That is why tightening `author` turned the pronunciation suite red.

**Fix:** `legal/ledger/synthetic.py` is the one fixture. It includes every schema-required field and `author` (`synthetic-fixture`, not a redistribution approval). `tests/ci_policy/test_synthetic_ledger.py` fails the merge gate if a new required field is missing or admission rejects the fixture. The pronunciation tests now call the builder. If the record is already blocked, audio faults are still recorded and the asset is still not accepted.

**PR:** #359

The search QA suite still built its own approved source. After `author` became required, `admission.evaluate` rejected that copy, and `audit_manifest` reported the generic error `production packs advertised with no approved source` before the archive check. `SearchAuditTests.reviewed_source` now calls `synthetic_source`. `tests/ci_policy/test_synthetic_ledger.py` fails the merge gate if that helper stops clearing admission. That migration is the follow-up PR on `cursor/search-ledger-fixture-67d8`.

## 2. Strict ruleset invalidates every other green PR after one squash

Ruleset `25041495` (`DEUTSCH verified main protection`) requires `public-pr-merge-gate` with `strict_required_status_checks_policy: true` and `required_review_thread_resolution: true`. After one squash, every other PR is behind and the check is reported as expected until a merge commit lands. Classic branch protection `GET` returned 403. `PUT` on the ruleset, changing only those two flags and keeping the required check, also returned 403. They were not changed.

A scheduled janitor cannot push that merge commit with `GITHUB_TOKEN`: the push would not retrigger the required `pull_request` check. `.github/workflows/pr_janitor.yml` only labels blockers and squash-merges one PR that is already up to date and green, with a subject that cannot carry a CI-skip instruction.

**PR:** #359 documents the 403. The ruleset is unchanged.
