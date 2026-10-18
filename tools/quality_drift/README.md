# DEUTSCH-IMPROVE-11 — Quality drift ledger

**Offline, advisory, evidence-bound regression monitoring.** No content generation, second release gate, CI execution, new workflows, store publication, repo mutation or private-data collection. Python standard library only.

## Immutable baselines and evidence contract

- Each snapshot has `version`, `repository`, `branch`, `head_sha`, optional `previous_digest`, `data_class`, `source_refs`, `approval`, and metric measurements.
- Measured metrics require status PASS/FAIL, nonnegative numeric measurement, defined method, matching source SHA, and exact GitHub commit/blob/tree link at the pinned SHA. `--expected-head` must come from a separately verified live GitHub HEAD. **Offline URL-shape checks cannot authenticate a hosted CI run, reviewer approval, metric value, or its evidence.** The integration owner must verify those independently.
- Unmeasured metrics use `UNKNOWN`, `NOT_RUN`, or `STALE` and null values. Never zero-fill. Fixtures cannot become APPROVED production baselines.
- One immutable JSON file per version: exclusive atomic hard link prevents overwrite, SHA256 checksum detects tampering, and the previous digest chains successive baselines. Identical repeated writes are idempotent.
- Comparison requires previous production baseline marked APPROVED with a SHA-linked review artifact (approval claim must be checked independently), the exact previous digest and same repository/branch. Missing or stale inputs never produce PASS.
- Regression thresholds are configured in `thresholds.json`; current FAIL is always an alert, but past FAIL followed by PASS is recovery. Output reports include each metric's evidence URLs and a human-readable Arabic summary. `quality_score_10=null` and `publication_approved=false` in all outputs.
- Private consumer metrics: only authorized, privacy-preserving *aggregate* exports with `sanitized_export=true`, stable public-safe references and their own private source SHA. Never transfer SRS, learner histories, IDs, raw example text, sensitive file paths or secrets to this public repository.

## Run from repository root

```sh
python3 -m unittest discover -s tests/quality_drift -p 'test_*.py' -v
python3 -m tools.quality_drift.engine record --input /secure/candidate-v1.json --directory /secure/quality-baselines --expected-head VERIFIED_LIVE_SHA
python3 -m tools.quality_drift.engine compare --previous /secure/quality-baselines/1.0.0.json --current /secure/quality-baselines/1.1.0.json --format json
python3 -m tools.quality_drift.engine compare --previous /secure/quality-baselines/1.0.0.json --current /secure/quality-baselines/1.1.0.json --format markdown
```

First candidate: `schema_version=1.0.0`, `version`, public `repository` and `branch`, `head_sha`, `data_class=production`, `source_refs.public={repository,branch,head_sha}`, `approval={status:PENDING,evidence_url:null}`, `previous_digest=null`, `metrics={}`. This empty candidate is **not** a quality approval or production evidence. To compare another version, provide the predecessor's hash as `previous_digest`, with the prior baseline independently APPROVED.

## Current source audit and dependencies

- Baseline SHA: `1f9a4b04be8b757a307f5f7e9d1e851a03174bca`; main protected at audit time.
- `manifest.json`: `packs: []`, `UNVERIFIED_RIGHTS`. `version.json`: `latest_verified_version: null`, `BLOCKED_DEPENDENCY`. `legal/ledger/sources.json`: `sources: []`. Existing release-gate README confirms production packs blocked. Do not mistake 100 registered language identities or legacy archives for confirmed lexical coverage.
- [#189](https://github.com/moaz76943-creator/-offline-packs-store/pull/189) lexical validation, [#146](https://github.com/moaz76943-creator/-offline-packs-store/pull/146) change impact, [#171](https://github.com/moaz76943-creator/-offline-packs-store/pull/171) release evidence: all Draft at audit time.
- [IMPROVE-03 #191](https://github.com/moaz76943-creator/-offline-packs-store/pull/191), [IMPROVE-09 #192](https://github.com/moaz76943-creator/-offline-packs-store/pull/192), [IMPROVE-10 #195](https://github.com/moaz76943-creator/-offline-packs-store/pull/195): all Draft, with remaining hosted/source verification. IMPROVE-07 result not independently located: UNKNOWN.
- `evidence_20261014.json` is a read-only *observation*, not an approved quality Baseline; production metric measurements are UNKNOWN/NOT_RUN. A previous approved baseline was not available. No genuine old-versus-new quality regression can yet be claimed.

No edits outside `tools/quality_drift/**` and `tests/quality_drift/**`; no Jules-owned files touched. Human review and protected-branch CI required before merge.