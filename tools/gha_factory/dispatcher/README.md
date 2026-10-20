# GHA public queue dispatcher v1 (fail closed)

**Storage:** one GitHub Issue per deterministic task. Open issues are the durable record; do not close completed task issues, because their `task_id` prevents duplicate acceptance. Only queue issues created by `moaz76943-creator` with a `[GHA-TASK] ` title prefix and one exact `gha-task-v1` JSON code fence are eligible. All 100 language identities must come from `catalog/language_registry.v1.json`; aliases cannot be silently substituted.

**Execution:** `.github/workflows/gha_dispatcher.yml` runs independently every hour (`11 * * * *`) or via the **Actions → Public GHA issue dispatcher → Run workflow** button. A workflow-wide concurrency group serializes claims and finalization; the controller claims at most three READY tasks, each with a distinct `(source_id, language)` lock. Three separate standard `ubuntu-latest` matrix jobs can work simultaneously; workers have read-only Issues/Contents permissions and never commit data. The controller/finalizer alone have `issues: write`, not `contents: write`. Each worker is limited to 295 minutes. No runner upgrade and no `build_store.yml` dispatch.

**Fallback enqueue:** if an API connector cannot call `workflow_dispatch`, create a GitHub Issue with title `[GHA-TASK] <task_id>` and the exact `queue.serialize(task)` body. Do not modify queue Issues manually except to create a structurally valid READY or NEW task. The scheduled dispatcher picks it up without ChatGPT waiting. A queue Issue is *not* a successful workflow run. Use this Python snippet in a trusted local clone to produce the Issue body (never pass commands, paths, URLs or secrets in task metadata):

```python
from pathlib import Path
import hashlib
from tools.gha_factory.dispatcher import queue
sha=hashlib.sha256(Path('catalog/language_registry.v1.json').read_bytes()).hexdigest()
t={
  'schema_version':'1.0','source_sha256':sha,'source_id':'public-registry',
  'language':'de','task_type':'registry_validate','shard':0,'contract_version':'1.0.0',
  'state':'READY','attempts':0,'next_retry_at':None,'lease_until':None,
  'run_id':None,'run_attempt':None,'checkpoint':0,'receipt':None}
t['task_id']=queue.fingerprint(t)
print('[GHA-TASK] '+t['task_id'])
print(queue.serialize(t))
```

**Task fingerprints:** lowercase SHA-256 of sorted compact JSON mapping `source_sha256`, `language`, `task_type`, `shard`, `contract_version`. The language and source ID must be allowed by the current public registry and ledger. Duplicate fingerprints are quarantined, not executed. Issue body has exactly 16 required fields. Fields are validated on every read, and worker jobs re-check lease `run_id` and `run_attempt`.

**States:** `NEW`, `READY`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `RETRY_WAIT`, `BLOCKED_SOURCE`, `QUARANTINED`. CLAIMED means reserved, *not executed*. RUNNING is recorded only after an authenticated same-run receipt is found; SUCCEEDED only after receipt and artifact digest verification. Missing/cancelled/timed-out worker receipts cause retry. Expired 330-minute leases become RETRY_WAIT, with 30/60 minute backoff and two retries after the initial attempt. Invalid or tampered receipts halt finalization; the lease times out for safe recovery. All issue transitions are serialized by the workflow concurrency group; this is not a general-purpose multi-writer CAS database.

**Current allowed work:** `registry_validate` invokes `catalog/validate_registry.py` with fixed argv, read-only. `admission_partition_verify` reads *only* Route GHA-01 output under `tools/gha_factory/admission/accepted/*/queue.json`, with status `ACCEPTED_FOR_QUEUE`, `publication_approved=false`, a matching canonical source SHA-256, reviewer evidence and an immutable partition filename/hash. The worker independently calls GHA-01 `route05_source` to verify the live Route 05 ledger, source snapshot, license proof and rights review, then streams at most 10,000 partition records / 40 MB. It records partition-offset progress and the exact run identity in the Issue. A crash replays the same immutable partition safely, with no accepted-record duplication because verification does *not* publish output. **Actual source release publication is separately gated and remains BLOCKED_SOURCE while the Route 05 ledger is empty.** No remote fetch, private application sources, personal learner data or credentials are read by workers.

**Validation:** `python3 -m unittest discover -s tests/gha_factory/dispatcher -p 'test_*.py' -q`. Tests use fake Issue API and local synthetic registry. Live GitHub issue enqueue → actual worker run → finalizer receipt is a separate integration gate; the run ID must come from GitHub Actions, never from a simulated unit test.

**Capacity:** three workers total per scheduled run and max three active leases, with one active task per `(source_id, language)`. The limit must not be raised without observing real run duration and quota/resource metrics. Up to 600 open repository Issues are scanned; above that bound, the controller stops rather than silently skipping tasks. Avoid creating more than a few genuine tasks per hour until throughput has been measured.
