# GHA Lexical Worker — source-backed ingestion (public only)

Status: BLOCKED_SOURCE for production rows; public Route 05 legal/ledger/sources.json has no approved dictionary artifacts. GHA-02 durable dispatcher/queue: BLOCKED_DEPENDENCY until a verified queue claim/lease contract is merged. PanLex source-backed semantic links: BLOCKED_DEPENDENCY until exact underlying licenses and semantic evidence are approved. No content downloaded, fabricated, or published.

## Dependencies and invariants

- Route 03: canonical catalog/language_registry.v1.json with 100 stable language IDs, script and direction, including de/ar/en/es/fr.
- GHA-01 admission: tools/gha_factory/admission/pipeline.py and Route 05 public legal ledger. Source is an immutable local Wiktextract JSONL reviewed dictionary artifact with exact SHA-256 and separately hashed license evidence. The worker reads (never writes) the source ledger and rejects license/path/version/review failures.
- Route 08: tools/sources/pilot5/pipeline.py for attested lexeme, POS, sense, morphology and IPA extraction.
- Route 06: standards/lexical/lexical.schema.json checked on each accepted record.
- Route 07: standards/lexical/sqlite_v2.py for bounded, independently verifiable SQLite user_version=2 batches with FTS5, foreign key and integrity checks.
- No inferred proficiency, directed translations, cross-language pivots, fabricated forms, or semantic concepts. Unmapped source senses have explicit unmapped concept IDs.

## Partitioning, checkpoints and outputs

Use a fixed partition_count. Partition owner is SHA-256 of the stable lexeme ID modulo partition_count. A GitHub Actions concurrency group serializes all runs of the same source_id+language to prevent overlap, even if operators vary partition_count. The SQLite checkpoint file binds snapshot SHA-256, language, partition count/index and registry SHA-256. It stores the raw-input byte offset, counters, lexical evidence and dedup keys. The output directory must be outside the repository. Resuming is supported by supplying the SAME output directory; automatic cross-run checkpoint restoration and durable claims require GHA-02 and are NOT implemented.

On completed input, verified-batches/ contains: 256-lexeme-max Route 06 lexical JSON files, corresponding SQLite v2 conformance slices, evidence.jsonl with source record locators/hashes, and qa_receipt.json. The receipt includes source/license IDs, source hash, partition identity, scanned/owned/accepted/rejected/duplicate counters and individual output hashes. These are NOT production packs and never change root manifest.json, version.json, or packs/.

Each invocation examines at most 100000 JSONL lines; memory is bounded by a 1 MiB line, 256-lexeme export batches and disk-backed SQLite state. Corrupt UTF-8, repeated JSON properties, wrong language, invalid POS/senses/forms or oversized records are counted and rejected. Accepted totals only count validated records. The Route 08 POS/feature adapter is intentionally narrower than all possible 100-language Wiktextract forms; unsupported forms must not be silently invented.

## Run after exact Route 05 admission

Install the open-source jsonschema 4.23.0 dependency if needed. Focused tests: python3 -m unittest discover -s tests/gha_factory/lexical -p 'test_*.py' -v. Example worker invocation: python3 tools/gha_factory/lexical/worker.py --repo-root . --source-id APPROVED_SOURCE_ID --language de --partition-index 0 --partition-count 4 --max-lines 20000 --out /tmp/gha-lexical-de-p0.

The gha_lexical_worker.yml workflow is manual-only on a standard Ubuntu runner with contents:read and timeout-minutes:295. It neither dispatches jobs automatically nor uploads data to a public release. GitHub Actions artifacts are retained seven days and may be manually reused to resume exactly the same partition. Until the GHA-02 dispatcher is approved, no queue integration or hosted run ID is claimed.
