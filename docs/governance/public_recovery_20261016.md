# Public batch recovery checkpoint

Task: `DEUTSCH-PUBLIC-BATCH-RECOVERY-20261016`.
Canonical baseline: `5c965970d7375c4f2c617d932cf6e951185adfe4` on public `main`.
This is execution evidence, not approval, enrollment or production certification.

## Complete initial inventory

The adjacent `public_recovery_20261016_snapshot.json` records all 144 open PRs,
their exact heads, changed paths (including rename origins), reviews, unresolved
review threads, exact-head checks and file intersections. Open pagination was
100 + 44 + an empty page. Closed pagination was 100 + 24, with 72 PRs merged in
the preceding 72 hours. PR #37 required three file pages (207 files); #27
required two (106 files). No review/check collection exceeded its first page.

Initial counts: 143 Draft, one non-Draft, zero wrong base, 24 conflicted,
112 behind, eight blocked and zero unknown mergeability. These are overlapping
classifications, not disjoint readiness states. Forty heads had a successful
required merge gate; 104 lacked that check. Reading every exact commit message
found 100 CI-skip heads. There were 27 review submissions and no independent
APPROVED submission; six PRs had unresolved inline threads. File intersections
are evidence of overlap, not proof of semantic duplication or an active Jules
worker. Remote Jules lifecycle ownership cannot be independently established.

Ruleset #25041495 is active: strict `public-pr-merge-gate`, squash only,
thread resolution, stale-review dismissal, no bypass actors, no force updates
or branch deletion. Its configured approval count is zero. This recovery still
requires independent review under the owner's current instructions. No Ruleset
or authorization file was changed. `approved.json` is empty.

## Actual repairs

- PR #180: normal fast-forward update to
  `a641a511367bb752a31170342891f3a317e6b03a`, merging current main into its
  branch and repairing the aggregate FTS SQL-value rejection. Test fixture
  builds five individually bounded senses through the canonical producer;
  the original consumer rejects their combined gloss. The repaired consumer
  uses the existing 80 MiB database ceiling without removing file size,
  SQL deadline, cache, read-only or exhaustive alignment guards. Local search
  18/18, conformance 19/19, CI policy 10/10 and store pipeline 17/17 pass.
  Published/tested tree: `26f05a7d5c75d7c74a2242a9296cfe5559735092`.
  Hosted exact-head gate run `38870407857`, search run `38870407836`,
  factory regression run `38870407640`, JSON run `38870407639`: PASS.
  Independent review remains requested; the original thread is open for
  reviewer verification. PR #176 changes a different function in the same
  source file and must be revalidated after integration.
- PR #117: normal fast-forward update to
  `8c073a5e1ea7cc36fda00b19a4e046c3dff1f474`, merging current main into its
  branch. Three regression tests reproduced seven failing subcases: lost
  root/pattern ambiguity, decomposed-query exact-match failure and invalid
  optional allomorph acceptance. All 20 Semitic tests now pass, including
  ambiguity beyond the returned-row limit. Local policy 10/10, pipeline
  17/17, registry and YAML/event guards pass. Published/tested tree:
  `f5a2e9263ec9cd82600c1dc96915738b110ca3ac`. The existing workflow now
  runs read-only contract QA for PR changes to its code/tests/canonical inputs;
  approved source processing remains explicitly manual, main-only and gated.
  Independent reviewer requested; three original threads remain open for
  verification. Exact-head hosted contract QA run `38870854336`, required
  gate run `38870854087` and JSON validation run `38870854132` pass. The
  production shard job is intentionally skipped on PRs; this is not a
  production execution claim.
- Incumbent coordinator: reproduced expired draft authorization returning
  `PROMOTE_ONLY`. Move the existing expiry check ahead of draft promotion.
  Add deterministic regressions for both expiry field names and an unexpired
  positive control. Coordinator suite: 45/45 PASS. No approval policy, scope
  exemption, merge writer, protection or registry changes.

## Superseded competing merge authorities

PR #165 at `e8bddde617b1a8a9f470398b7bd40397bfd07dd9` adds a separate
`smart_pr_merge.yml` and squash engine. Its own description requires selecting
one authority and prevents activation while the incumbent exists. PR #167 at
`c28b0c0e833cd806d3707691752b63dfc1991dc2` consists only of a Mergify queue.
Both were closed, not merged, under the owner's explicit incumbent-only
selection. All branches and unique proposals remain available. Neither's
unresolved technical findings are claimed fixed. No other PR was closed.

## Queue and source findings

Do not redo merged #181, #267, #74, #184 or #230. Dispatcher suite passes
29 outer tests, including subprocess candidate-patch lifecycle tests (22 inner
cases and 12 queue cases). Orchestration suite passes 44 tests. The merged
EXEC-03 repair is still a candidate patch exercised by tests, rather than
proof that its runtime code has replaced the production dispatcher.

The live workflow invokes `tools.gha_factory.orchestration.cli`, whose
`protocol.EXECUTABLE` still contains only registry validation, admission
partition verification and approved snapshot verification. #267's additional
legacy dispatcher types therefore do not establish production execution in
the active v2 orchestration path. Keep Issue #65 open. The existing job-level
controller/finalizer concurrency is separate from workers, addressing the
original workflow-wide bottleneck, but Issue #69's stronger separate-run and
source-backed interruption/checkpoint acceptance is not proven by these tests.

The source ledger is empty. No licensed production shard, authentic production
finalizer receipt or recoverable multilingual corpus checkpoint was generated
in this task. No worker production run was dispatched. The existing main
coordinator run `38866524219` passed 43 contracts, verified effective rules and
reported `APPROVED_CANDIDATES=0` / `NO QUALIFIED MERGE`.

## Handoff and blockers

No PR was merged by this recovery, so `MERGE_COMMIT_SHAS=[]`; historical
merges in the snapshot must not be attributed to it. The existing coordinator
is the sole permitted writer. Independent exact-head approval and a separate
reviewed authorization change are still required. No candidate was enrolled.
The current generic coordinator excludes search QA and workflow-bearing
Semitic scope; a legitimate reviewed policy decision is needed before such
candidates can be handed to it. Do not route around that exclusion or use a
self-authored approval record. The expiry fix itself is in the permitted
incumbent scope but still needs independent review and authorization.

Next batch: finish independent verification of #180/#117 and this expiry fix;
then re-pin main/head, authorize through the approved process and allow one
incumbent coordinator transition at a time. Revalidate #176 after #180.
Source-rights approval and active queue adapter integration remain separate
production blockers. Flutter analyze/tests are not applicable to this public
Python-only repair; no APK build was run.
