# Sentence-scale evidence factory (v1)

This independent, standard-library-only **candidate processor** reuses the
canonical tools/source_examples/pipeline.py validator and identities, as well
as the GHA-05 source candidate contract, the 100-language registry, lexical
sense identities, and the Route05 legal source ledger. The program never
manufactures sentences, translations, grammatical claims or source approvals.

## Inputs and rights

- JSON manifest: {"schema_version":1,"shards":[{"path":"shard-1.jsonl","sha256":"ACTUAL_SHA256"}]}.
- Each immutable UTF-8 JSONL record extends the canonical sentence.schema.json.
  The source object must include dataset_version, artifact_sha256,
  record_locator, and source_class: attested_corpus or reviewed_editorial.
- Publisher, source version, license class and original retrieval SHA must
  match independently approved Route05 sources.json records. Per-sentence
  attribution and license are preserved. Mixed licenses require separate
  independently approved source IDs; CC BY material is never labeled CC0.
- The source language, situation, register, context and grammar annotations
  require an independent language_review and annotation_review with
  reviewer_id, exact sentence_sha256 and HTTPS evidence_url. Independently
  reviewed editorial examples additionally require editorial_rights_review.
- The canonical lexical sense, grammar and editorial review contracts still
  apply. Unsupported senses and linguistic assumptions never get invented.
- Original translations are links, not automatically generated or assumed
  literal equivalents. Each translation requires a translation_reviews
  attestation with original sentence SHA, target SHA, target source sentence ID,
  target language and authorized reviewer evidence.

Situation fields cover everyday greetings, travel, work, home, health, food,
public services/administration, shopping, emergencies and study. Separate
languages and culturally contextual expressions are not collapsed.

## Usage

    python3 -m tools.factory_extensions.sentence_scale.worker \
      --manifest /tmp/manifest.json --workspace /tmp/approved-snapshots \
      --db /tmp/sentence-scale.sqlite --out /tmp/sentence-scale-out \
      --catalog catalog/language_registry.v1.json \
      --ledger legal/ledger/sources.json \
      --senses /tmp/reviewed-senses.json --rules /tmp/reviewed-rules.json \
      --reviewers /tmp/trusted-reviewers.json

    python3 -m unittest discover -s tests/factory_extensions/sentence_scale -p 'test_*.py' -v

Files emitted are candidates.jsonl and report.json, both **not published**.
The report gives accepted/rejected/requires_review for each of the 100
registered language identities, plus counts for malformed lines and unknown
languages. Source text, script and punctuation remain byte-faithful after
JSON decoding. NFC/casefold transforms apply only to duplicate indexes.

SQLite checkpoint keys include immutable source shard name and SHA-256.
Stable canonical sentence identities are preserved; content revision is held
without overwriting the original record. Exact duplicates are retained with
their sources and held for review. Near-duplicate comparison is bounded to
32 indexed same-language candidates sharing the first 12 normalized characters:
this is a review signal, not an exhaustive semantic deduplication claim.
Batch relation processing uses 512-record pages.

## Current production evidence

As inspected 2026-10-13, legal/ledger/sources.json contains zero approved
source records. Therefore genuine production accepted sentence counts are ZERO.
Five real Tatoeba pilot fixture sentences remain unapproved-to-publish
REQUIRES_REVIEW examples. Mock approved fixtures in tests never count as
real source approval. No source downloads, ingestion dispatch, publication,
record-count inflation, or remote-run ID is triggered by these files.
