# Independent-worker handoff contract (isolated, pre-integration)

This extension reuses the existing GHA-02 GitHub Issues ledger, canonical v1 parser
and completed receipt bytes. It uses the proposed PR #74 v2 parser **only when
that code is integrated**. It does not create another queue or modify files
owned by PRs #68, #74 or #81. All task source/language IDs are immutable. The v1
fingerprint omits source ID; v1 source collisions must not be silently migrated.

## Supported contract

- `ticket()` requires a leased existing Issue, source SHA, exact worker run and attempt,
  vetted workflow/commit ref, and unexpired bounded lease.
- `validate_against_issue()` rejects reclaims, stale leases and cross-run replay.
- `receipt()` and `verify_receipt()` preserve controller and worker run provenance,
  output SHA-256, exact checkpoint and result status.
- `durable_checkpoint()` requires actual restored immutable SHA-verified bytes.
  GitHub Actions artifact expiry or a runner-local path never count as durable recovery.
- `fair_claim_candidates()` is read-only. Its caller must first verify live workers
  through authoritative GitHub run/job records. It enforces three global slots,
  source-language locks, retry priority and stable Issue ordering.

The five-hour-worker test is a deterministic **scheduling simulation**: one
long-running external worker occupies one of three slots, leaving two available
for the next hourly claim. It is NOT a live hosted five-hour success result.
The three-worker cap can only rise following measured capacity and safety review.

## Integration blockers and safe boundary

1. The main `gha_dispatcher.yml` still serializes the whole workflow. PR #74
   narrows job-level concurrency but does not yet create independent worker
   **workflow runs**. Its owner must connect an approved fixed-workflow
   dispatch with exact run-ID discovery and shared mutation serialization.
   GitHub Issue PATCH is not compare-and-swap.
2. The new QA workflow is intentionally read-only. It does not start a
   production worker, create queue claims, download content, mutate an Issue
   or publish packs. Long-running workers and short finalizer jobs are a
   separately gated integration; this PR alone cannot complete that mission.
3. The Source Route05 ledger currently has zero approved sources; real
   production work remains blocked. Do not substitute synthetic fixtures.
4. Only existing verification workers are allowed by this contract.
   Morphology, lexical ingestion, examples, SQLite, security and release
   production jobs require audited adapter implementations and source rights.
5. The existing one-day receipt artifact is not a durable checkpoint store.
   Recovery from a multi-hour failed worker needs an immutable storage
   contract with bounded retries and idempotent verified restored bytes.
6. A worker run is trusted only after its workflow/ref/run metadata and
   current Issue owner agree; cancellation/failure are never accepted as
   success. No private code, inputs, credentials, arbitrary URLs, shell
   strings or unrelated repository writes are supported.

## Test and release gate

`python3 -m unittest discover -s tests/factory_extensions/worker_handoff -p 'test_*.py' -v`

21 targeted tests cover duplicate JSON fields before PR #81 merges, v1
historical Issue #58 preservation, malformed and stale claims, cancellation,
five-hour fairness, slots, locks, durable checkpoint verification and receipt
SHA/replay checks. Run unchanged dispatcher tests in the same job.

Commits use `[skip ci]`; an absent automatic run is not proof of success.
Run explicit hosted exact-commit QA and record actual run/check IDs before merge.
Never run `build_store.yml`.