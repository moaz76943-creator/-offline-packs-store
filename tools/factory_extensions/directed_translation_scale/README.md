# Evidence-gated directed translation scale (isolated extension)

This module consumes **canonical** public language identities and **pre-existing,
approved, sense-distinguished** lexical records. It never fetches corpora, generates
translations, creates fictional senses, substitutes aliases, infers reverse edges, or
composes pivot translations. The user-interface language is independent of both
directions of an edge. Production edges are **not** produced from fixture text.

## Current public-main evidence

At the integration base `254e8edd85a2d4a37c13e1834ef2d9f77ce7e605`,
`legal/ledger/sources.json` contains **zero approved source records**.
The examples in `standards/lexical/fixtures/positive.json` are
`fixture_only=true` and `publication_approved=false`. Therefore default
offline execution reports **0 verified pairs, 0 review-required edges,
9,900 unavailable (not yet evidenced) directed pairs**, rather than
pretending that any dictionary is complete. Availability describes the
*admitted graph*, not a linguistic claim that a translation is impossible.

## Canonical adapter and admission

- Registry: `catalog/language_registry.v1.json`; exactly 100 product IDs,
  no automatic alias, locale, script or dialect coercion.
- Sense input: a canonical `standards/lexical/lexical.schema.json`
  version-1.0.0 document, with lexemes and their independently approved senses.
  Unapproved fixture senses are never indexed.
- Candidates: bounded JSONL translation rows, canonical lexical translation
  shapes, or a single proposed PR #79 directed-pair 1.0.0 document. Source and
  target IDs are verified against the indexed sense owners, never guessed from
  the translated word or a language label.
- Provenance: Route-05 `legal/ledger/sources.json`, matched to the record's
  source ID, publisher, version, license, source URL and SHA-256. PR #87's mapper
  can provide provenance metadata but its output **alone** is not an approved
  directed-sense attestation. Each edge also needs a matching
  `evidence.kind=direct_sense_attestation`, matching from/to sense IDs, source
  snapshot SHA and source locator.
- PR #73's link QA is **candidate-level sentence-link verification**, not
  independent lexical sense identity or semantic editorial approval. Such
  records cannot be upgraded automatically to graph edges.
- Verified edges additionally require a *separate* immutable SHA-pinned
  editorial review ledger with the same candidate snapshot SHA, source SHA,
  sense IDs, direction, reviewer, review ID and evidence locator. Otherwise
  valid attested edges remain `review_required`. The authority and editorial
  quality of review ledgers must be established upstream by the owner; a
  matching local JSON object is not cryptographic proof of a human review.
- Contextual or approximate relations require explicit context; exact
  equivalence must match independently assigned canonical concept IDs.
  Original script and lexical text are not silently normalized.
- Invalid/uncertain candidates are counted in `blocked_reasons`, not
  admitted as verified or silently converted into reverse mappings.

No production source corpus or rights claim is included in this PR.

## Bounded build, extension, and reports

```bash
python3 -m unittest discover -s tests/factory_extensions/directed_translation_scale -p 'test_*.py' -v
python3 -m tools.factory_extensions.directed_translation_scale \
  --database /tmp/directed-graph.sqlite \
  --receipt /tmp/directed-receipt.json \
  --matrix /tmp/directed-coverage.json
```

For a future reviewed, genuinely licensed snapshot: save independently
approved source/sense, direct-translation and optional independent review
records **within the extension's `shards/` folder**; record their
SHA-256 digests; run the dedicated read-only workflow with
`lexical_path/lexical_sha256`, `candidate_path/candidate_sha256`,
and optionally `review_path/review_sha256`. Each required file pair must be
present together. PR and synthetic-only invocations deliberately have no
production candidate input.

Actions uses four disjoint deterministic SHA-256 translation-ID partitions,
SQLite-backed storage and a 100,000-row upper input bound. Shard runners are
read-only, standard free public Ubuntu, with 15-minute timeouts and artifacts
retained for 7 days; they do not mutate canonical files or source ledgers.
Each receipt binds the source/candidate/review SHA, checkout SHA, run ID,
shard index and SQLite digest. The aggregator refuses missing, duplicated,
divergent or tampered shards. Only the aggregate **coverage JSON** materializes
all 9,900 pair statuses on demand; no 9,900 dictionaries are preallocated.

The `counts` field enumerates actual admitted `verified`,
`review_required`, and `blocked` candidate records; per-pair counts always
retain direction. `unavailable` means there are no admitted attestations
for that directed pair, leaving a safe growth path when genuine evidence
is admitted in later immutable shard snapshots.

No additional billing, private application access, or third-party network
downloads are required. An artifact ID or successful Actions run ID must
come from GitHub, never from this synthetic test suite.
