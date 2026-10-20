# DEUTSCH-EXEC-03 — tested repair patch / NOT_APPLIED

Issue: https://github.com/moaz76943-creator/-offline-packs-store/issues/69
Baseline: 7a5a554b7248ec6baa610ba443b747c7643ba9b9

## Ownership decision

The runtime repair is **NOT_APPLIED**. PR #81 (head d3271875b29cf1168924e6100f136d80a822249f, updated 2026-10-14) changes queue.py. PR #68 (head f8e320ed06cc9dab6f0300f7d64757219ff6516f) changes controller.py and worker.py. Their actual file inventories were inspected. PR #74 adds an alternate orchestration integration and changes gha_dispatcher.yml; PR #105 stages an independent handoff contract. Do not overwrite these files or introduce another dispatcher. The only delivered paths are this document, exec03.patch, and two targeted test files inside the authorized dispatcher directories.

The patch modifies the existing three modules **only in a temporary copy during testing**. A coordinator must reconcile it with #68/#81, apply it to the selected implementation, and rerun tests. Do not merge the delivery as if its patch already repairs main.

## Reproduced on actual main Python modules

- An expired lease for an in_progress, missing, foreign, or newer-attempt run is recovered and reclaimed without proof the original worker stopped.
- A lower-number READY duplicate can displace/quarantine a real active lease; multiple active duplicates are omitted from capacity accounting.
- A lower-number READY duplicate of a SUCCEEDED task can be scheduled again.
- A READY task at attempts=3 passes selection, then claim raises after creating attempt=4 and aborts the controller.
- A worker accepts an expired claim and executes work.

Initial baseline: 13 existing tests PASS. The first targeted lifecycle run: 19 cases, 9 failures and 4 errors; 3 errors indicate absent new renewal/bounded-execution APIs, not independently discovered defects. The exhausted-claim error is a reproduced runtime defect.

## Patch behavior

- Preserve completed task identity and prioritize active claims over pending duplicates. Account for every active duplicate; quarantine it only after exact-run completion and lease expiry prove safe recovery.
- Fail closed on unknown run state. Recover only after authoritative GitHub GET /actions/runs/{id} reports completed for the same run ID and attempt. Keep checkpoint and bounded backoff. Retry remains at most three claims.
- Reject stale worker leases before execution, and emit TIMEOUT with the previous checkpoint if the lease expires during work.
- Execute the existing work() in a spawned process with a fixed 600-second bound for the currently supported verification tasks. Clean up the POSIX process group, including registry subprocess descendants, with terminate/kill bounds. No Issue-provided command or timeout is executed.
- Add queue.renew as a pure, exact-run/attempt-fenced transition, bounded by a trusted hard deadline. It is **not wired to an automatic heartbeat**; a serialized writer must validate current GH records and supply the authoritative run-start deadline.
- Preserve v1 fingerprint algorithm, schema, source gates, receipts, and existing checkpoint fields. No production task types, source approval, publication, or workflow changes.

## Reproduce / validate

From repository root:

    python3 -m unittest discover -s tests/gha_factory/dispatcher -v

The harness performs git apply --check and git apply only in a temporary directory, then imports and tests actual patched queue/controller/worker modules. It does not edit the checkout. The baseline cases run against tracked main code too.

Final local result: 14 outer tests PASS (13 existing + harness), and the harness runs 31 distinct patched-code cases PASS (9 queue + 22 lifecycle, including 4 existing controller cases and 18 new regressions). Actual child-process registry validation and an actual frozen registry subprocess are exercised. Fixtures and fake GitHub API records are used; no real GitHub worker or hosted test run was dispatched. Hosted validation: NOT_RUN. This proves local code behavior, not autonomous production orchestration.

## REMAINING_WORKFLOW_DEPENDENCY — DEUTSCH-EXEC-09

Current gha_dispatcher.yml still sets workflow-wide public-issue-queue-controller concurrency, retaining it during the 295-minute worker matrix. Code repair alone cannot remove the bottleneck.

Required workflow integration diff, owned exclusively by EXEC-09:

1. Remove workflow-wide serialization of long workers; serialize only durable claim/recovery/finalization writers using one selected coordinator. Do not simply remove the concurrency block: Issue PATCH has no compare-and-swap, so concurrent claim writers remain unsafe. GitHub concurrency also allows only one pending run/job; recovery must tolerate displaced pending finalizers.
2. Dispatch approved, fixed independent read-only worker runs, with a durable controller-to-worker run/attempt binding. Do not assume the controller run ID is the worker run ID after splitting workflows. Check status/conclusion, actual workflow identity, attempt and source/checkout binding before completion/recovery.
3. Enforce max three genuinely live workers using authoritative run/job inventory, including orphaned runs absent from Issue leases. Local tests model live leased workers; they do not verify global orphan accounting or concurrent external controllers.
4. Give workers contents:read/issues:read only. A short serialized issues:write controller/finalizer owns lease renewal and durable checkpoints. Grant actions:read for actual run inspection. Derive the hard deadline from verified run-start time and the fixed execution cap; renewal must never extend total execution indefinitely.
5. Keep checkpoint/artifact transport immutable, hash-verified and bound to task/source/run/attempt. Current verification workers replay the admitted partition safely and preserve their previously committed Issue checkpoint. This patch does not implement incremental durable checkpoints or artifact restore for future long corpus processors.
6. Missing receipt/artifact after an interruption must remain recoverable through bounded retry; authenticate receipt/output hashes before activating success. Preserve historical successful receipts. Independently test the reconciled candidate on its exact SHA before any merge.

No workflow file has been changed; no build_store.yml, paid runner, corpus ingestion, merge, or production claim occurred. #69 remains open and blocked on ownership reconciliation plus EXEC-09 integration.
