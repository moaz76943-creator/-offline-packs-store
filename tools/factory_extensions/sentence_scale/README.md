# Sentence-scale evidence factory (v1)

This independent, standard-library-only **candidate processor** reuses the
canonical tools/source_examples/pipeline.py validator and identities, as well
as the GHA-05 source candidate contract, the 100-language registry, lexical
sense identities, and the Route05 legal source ledger. The program never
manufactures sentences, translations, grammatical claims or source approvals.

## Inputs and rights

- JSON manifest: {"schema_version":1,"shards":[{"path":"shard-1.jsonl","sha256":"ACTUAL_SHA256","approved_shard_source_id":"reviewed.shard.id"}]}. The shard SHA is calculated from the actual source bytes; it is never inferred from a record's self-declared original artifact hash.
- A published-eligible shard requires a **separate independently reviewed Route05 source record** for approved_shard_source_id, with kind=examples, status=APPROVED_FOR_REDISTRIBUTION, retrieval.sha256 equal to the actual shard bytes, and publisher, dataset_version and license matching the original source. Its reviewed alterations must contain "derived_from:<original_source_id>@<original_artifact_sha256>", plus actual retrieval and license evidence URLs/hashes and reviewer decision. A caller-provided SHA or approval flag alone is never a grant. Missing approval stays REQUIRES_REVIEW; contradictory claimed approval is REJECTED. The original source and derived shard have **distinct source IDs** so shard bytes need not self-contain their own SHA.
- Rights/lineage evidence is verified against the *independent* ledger on every checkpoint replay; revoking the original or derived shard grant downgrades formerly accepted records.
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
  target language and authorized reviewer evidence. The authorized reviewer must
  be approved for **both source and target languages**.
- Evidence-only changes (review, language_review, annotation_review,
  editorial_rights_review, translation_reviews, cefr_evidence_url) may be
  resubmitted without changing immutable sentence identity. They replace only
  editorial evidence and are revalidated; source text, source metadata,
  translations and grammar claims remain immutable.

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


Duplicate JSON object keys in job manifests, source ledgers, lexical/grammar
registries and authorized reviewer rosters are rejected before processing;
ambiguous overrides cannot promote a denied approval. SQLite connections are
closed explicitly at the end of each bounded run, including failure paths.
This is covered by four additional isolated regression tests.

Each checkpoint replay revalidates the current legal, lexical, grammar and
reviewer trust contracts. A revoked source approval or editorial grant cannot
leave a previously accepted candidate accepted. Shard paths reject symlinks
before canonical resolution, and oversized JSONL lines are discarded through
bounded reads instead of being loaded into process memory. The three regressions
are covered by scoped tests; local tests do not certify hosted GitHub Actions.


## Current production evidence

As inspected 2026-10-13, legal/ledger/sources.json contains zero approved
source records. Therefore genuine production accepted sentence counts are ZERO.
Five real Tatoeba pilot fixture sentences remain unapproved-to-publish
REQUIRES_REVIEW examples. Mock approved fixtures in tests never count as
real source approval. No source downloads, ingestion dispatch, publication,
record-count inflation, or remote-run ID is triggered by these files.
