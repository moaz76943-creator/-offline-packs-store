# Versioned orchestration integration (candidate, not production readiness)

This compatibility layer leaves every dispatcher v1 source file and fingerprint
unchanged. It is independent of the actively owned PR #68 seeder/controller files.
New v2 IDs also bind source ID, schema version and dependency IDs. Completed v1
receipts are never migrated or overwritten. Run via `python3 -m
tools.gha_factory.orchestration.cli`.

## Execution and authority

The modified dispatcher retains its hourly `11 * * * *` schedule. It removes
workflow-wide serialization: controller and finalizer alone share job concurrency
`public-issue-queue-mutations` with `queue: max`. Workers run in separate jobs,
with task-ID locks. Successive scheduled workflow runs can therefore claim another
independent task while earlier workers execute. Workers are NOT separate manually
dispatched workflow runs; that further separation is an outstanding integration
requirement. No recursive events, API dispatches, or polling loops are introduced.

The serialized controller reads all issues, including closed ones, with a hard
2000-issue bound. An incomplete scan fails closed. It verifies approved local
snapshot/license evidence, source and partition SHA-256, canonical language IDs,
versions, declared expiry and dependencies. It creates at most five missing v2
verification tasks. Historical v1 admission identities are reused. Bounded source
inspection rotates hourly to avoid starvation by blocked old tasks. Cheap registry
checks do not hash large source files.

Claims occupy one of three global slots and lock source/language. An expired lease
is NOT enough to replay: the authoritative GitHub run must also be completed at
the exact recorded attempt. An unverifiable/still-live run retains its slot.
Actual started worker-job metadata permits RUNNING state. Issue PATCH is not CAS:
all queue mutations MUST use the shared Actions job-concurrency lock. A reread
also rejects an observed ownership change; arbitrary external writers do not have
an atomic claim guarantee. Do not run the controller as an independent CLI writer.

Only repository-owner and github-actions[bot] queue issues are trusted; PRs,
extra body fields, paths, commands and URLs are not execution instructions.
Workers have read-only issues/content tokens. Controller/finalizer receive
issues:write and actions:read only on main schedule/manual jobs. Validation runs
read-only on PRs or manual `tests_only=true`.

## Worker contracts and current blockers

The v2 enum includes all requested types. Only `registry_validate`,
`admission_partition_verify`, and `approved_snapshot_verify` have executable fixed
adapters. The latter verifies admitted bytes; it creates NO lexical candidates.
Lexical, morphology, sentences, exercises, SQLite candidate, Unicode search,
security fuzz and release evidence contracts are BLOCKED_DEPENDENCY until their
owners provide audited, immutable input/receipt interfaces. Unsupported kinds are
never replaced with fixture generation or arbitrary shell commands.

Legal source ledger is empty at the checked main revision. Production tasks stay
BLOCKED_SOURCE; published/accepted production corpus counts remain zero. For v1,
a new dependency block maps to its already-supported BLOCKED_SOURCE state; its
schema is not silently extended.

## Checkpoints and retention

Currently executable workers are repeatable verifications. Reviewed source,
license evidence and accepted partition bytes MUST be available in the pinned
checkout; controller snapshot/evidence limit is 64 MiB each and partition limit
40 MB. Larger external snapshots are BLOCKED_DEPENDENCY pending the separately
owned durable source handoff. No source URLs are fetched by orchestration.

A worker uploads a compact receipt for ONE day only. Finalizer checks matching
run/attempt/task, bounded counters, lease deadline and candidate hash (if present),
then stores the authoritative compact completion in its Issue. Artifacts are a
transient receipt transport, never durable corpus/checkpoint storage. Lost receipts
cause bounded backoff, not success. Failed attempts never advance a non-durable
partial checkpoint. Full corpus processing, content-addressed permanent checkpoint
handoff and recovery after artifact expiry remain blockers before those worker
contracts can execute. Missing/tampered receipts preserve ownership or retry safely.

## Validation and PR #68 review

Local: 43 orchestration tests + 13 unchanged dispatcher tests PASS. Includes an
actual SHA-checked temporary admission fixture through claim/worker/finalizer,
closed-success dedup, expiry, byte tamper, cancellation, stale live leases, three
slots, independent work and a 700-task finite fairness simulation. Synthetic test
fixtures never enter the production ledger. YAML parse and permission/concurrency
assertions PASS locally, not hosted Actions syntax/execution verification.

PR #68 exact head 6735cc481a259d41819c77f775e2156acce5d33b:
15 seeder tests + 13 dispatcher tests PASS locally; hosted checks absent.
Independent negative probe passed missing source bytes and UNLICENSED metadata to
`seeder.plan`: it returned one READY proposal. Its existing metadata gate does not
verify source/evidence bytes or license family before enqueueing. Do not merge #68
until its owner adds these gates and negative tests and hosted validation passes.
No files owned by that PR were modified here.

Confirmed historical run 38328584584 (attempt 1) has successful controller, worker
and finalizer jobs; Issue #58 retains its exact v1 SUCCEEDED registry receipt.
This proves existing registry verification only. No new hosted run is claimed.

Before merge: run the public dispatcher workflow on this branch with
`tests_only=true`, record the actual run ID and check all required checks. Commits
carry [skip ci], so a PR opening is not hosted-test evidence. Do not run build_store.
