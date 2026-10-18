# Lexical Scale: admitted-source extension (review-only)

Isolated from GHA-01/02 ownership and active PRs #63 and #70. No production
pack, queue schema, live source ledger, or unrelated application file is modified.

## Absolute admission and identity

- The canonical registry supplies exactly 100 distinct language IDs and default scripts.
- Before checkpoint creation, the adapter reuses live GHA-01 Route05 checks:
  manually approved dictionary source; exact immutable SHA-256 source artifact,
  source-specific license proof, publisher/version/URL and SHA-matched reviewer proof.
- Input must be a checked-in reviewed plain UTF-8 .jsonl Wiktextract-style snapshot.
  Compressed/unreviewed/network inputs are blocked. Source-specific rights must be
  independently reviewed; no generic license text is sufficient.
- The actual Route05 ledger legal/ledger/sources.json is empty (2026-10-13).
  Thus **NO PRODUCTION INPUT IS CURRENTLY ELIGIBLE**. Genuine accepted lexemes,
  senses, rejected source rows, and run IDs are all unavailable; do not call
  synthetic test counts production content.

## Operation when an actual source is admitted

From repo root, with one distinct checkpoint file per source/language/shard:

    python3 tools/factory_extensions/lexical_scale/adapter.py --root . --source-id APPROVED_ID --language ar --shard 0 --shards 8 --checkpoint /tmp/lex-ar-0.sqlite > /tmp/lex-ar-0.receipt.json
    python3 tools/factory_extensions/lexical_scale/export.py --checkpoint /tmp/lex-ar-0.sqlite --language ar --out /tmp/lex-ar-0-docs
    python3 tools/factory_extensions/lexical_scale/report.py --root . /tmp/lex-ar-0.receipt.json

All eight shard jobs must use the same immutable shard count/source hash, but
different checkpoint paths. Input is stream-scanned with bounded line buffers;
SHA-bound checkpoint identity includes source version, registry, source digest,
language and shard. SQLite saves byte offset, line number, actual counters,
source evidence, lexemes and senses transactionally. Replayed rows do not
double-count. In the shard receipt, source_rows means all rows scanned by that
shard; do not sum it across shards. Aggregate complete matching shard sets only.

Lexical output follows the opt-in lexical contract 1.0.0: separate homographs
and senses, original Unicode script/diacritics, native record locator,
publisher/license/version/retrieval SHA, source-attested forms and IPA only.
Missing pronunciation, proficiency, forms and translations remain unknown.
Unverified translation text is excluded and counted as a coverage gap.
Script substitution is rejected using the live admission script gate;
unsupported writing systems require reviewed verifier extensions (not fake
support). Uniform high counts across multiple languages trigger review.
Candidate status stays REVIEW_REQUIRED; no publication rights are asserted.

The checkpoint SQLite is NOT the production SQLite v2 mapping. Exported
bounded Route06-shaped fragments require full lexical schema validation,
independent SQLite v2 import conformance, license/release approval, and
permanent ID mapping before distribution.

## GitHub Actions and resume limits

The new public lexical_scale_qa.yml runs synthetic unit tests on PRs. A
workflow_dispatch only attempts manual admitted-source work when an approved
snapshot and proof bytes are already in checkout. Standard hosted Ubuntu,
contents:read, 295-minute maximum. It validates every emitted fragment and
stores short-lived 3-day review-only artifacts. This is manual recovery
material, NOT guaranteed durable cross-run restoration. No new GHA-02 task
types or automated queue dispatch have been authorized; no actual
workflow run/checkpoint/task IDs are claimed. Zero approved sources means
zero eligible production dispatches.

## Local synthetic-only test evidence (2026-10-13)

8 core synthetic unit cases passed; 18 discovered cases passed after extending
coverage/export tests (including inherited cases). Tests include Unicode
diacritics, etymology homographs, polysemy, forms, language/script substitution,
bad UTF-8, duplicate JSON keys, reviewer-proof tampering, replay, shard
isolation and 100 registry identities. A synthetic 25,000-row run took 8.59s
(2,911 scanned rows/sec, 25,000 synthetic lexemes and senses), with measured
Python allocation peak of 3,291,510 bytes, NOT process RSS. The local test
used a narrow test double for the GHA-01 interface. Exact-ref GitHub-hosted
tests and actual approved-corpus throughput are NOT_RUN.

Receipt aggregation summaries cannot independently authenticate arbitrary
outside JSON receipts. Check original checkpoint and Route05 data before
release decisions; absent languages are NOT_PROCESSED, not measured zeros.

Blocked-source evidence: legal/ledger/sources.json sources=[].
Owned dependencies: PR #63 lexical, PR #70 content ingestion, GHA-02 queue.
