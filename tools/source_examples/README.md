# Source-backed multilingual example pipeline (schema v1)

This tool is isolated from the app: it reads **approved public source examples only**. All work is offline and Python-standard-library-only. It never reads a learner history, user conversation, private repository, or any signing material. The public repository did not yet contain the canonical sense/grammar catalogs or the licensing ledger when this code was authored; the pipeline therefore **fails closed** rather than inventing approvals or explanations.

## Run from repository root

```sh
python3 -m tools.source_examples.pipeline ingest \
  --input tools/source_examples/fixtures/pilot_tatoeba.jsonl \
  --db /tmp/source_examples.sqlite \
  --out /tmp/source_example_bundles
python3 -m tools.source_examples.pipeline search \
  --db /tmp/source_examples.sqlite --language de --situation food --limit 20
python3 -m unittest discover -s tools/source_examples -p 'test_*.py' -v
python3 -m compileall -q tools/source_examples
git diff --check
```

Once independent approved contracts exist, add **read-only** `--ledger PATH --senses PATH --rules PATH --reviewers PATH` to the `ingest` invocation. Each contract is a JSON object with `schema_version: 1` and a list key described below. Input is line-delimited JSON, streamed without loading the corpus in RAM. Daily ingestion into the **same SQLite file** keeps stable IDs; reusing the same `source_id + sentence_id + language + context_id` preserves IDs even after text changes. Changed records are held for re-review. Only `ACCEPTED` records appear in deterministic per-language `accepted/*.jsonl.gz`; everything else is in `requires_review.jsonl` or `rejected.jsonl`. The `report.json` contains exact status counts and per-batch malformed-line counts. Retrieval is SQL-indexed, bounded to 200 records.

## Minimal approval contracts (external, independently governed)

- `sources` licensing ledger (the native `legal/ledger/sources.json` format uses `schema_version: "1.0.0"` and enforces kind, status, retrieval SHA and manual review; also accepts the simpler explicit v1 form below for independently approved downstream manifests): `source_id`, `publisher`, `origin_prefix` (HTTPS), `license` (e.g. `CC-BY-2.0-FR`), and an explicit Boolean `redistribution_approved`. Record-specific attribution and URLs must match. **A license alone is not reviewer approval.** The license ledger must be maintained by a separate compliance review, not self-approved by this script.
- `senses`: `sense_id`, `language`, `lexeme_id`. The native `standards/lexical/lexical.schema.json` contract is supported when its `contract_version` is `"1.0.0"`; `fixture_only` and `publication_approved` fields are honored. Synthetic lexical fixtures never authorize publication. All examples intended for publication must link to at least one matching canonical sense. This module will not create new lexical senses itself.
- `rules`: `rule_id`, `language`, `explanation` (editor-approved exact text), optional `allowed_cases` and `allowed_agreements`. Sentence annotations may refer to rules and features. Unsupported or contradictory grammatical case or agreement is rejected. This is a **contract validator**, not a full grammatical parser; family-specific validators can be added as independently reviewed implementations without changing record IDs.
- `reviewers`: approved `id` and `languages`. The individual record must contain a `review` with `decision: approved`, `reviewer_id`, `evidence_url` (HTTPS) and `sentence_sha256` of the current exact UTF-8 text. This is a **trust policy over an externally approved roster**, not cryptographic proof that an editor actually worked. Deployment must authenticate review attestations upstream.

Illustrative structure (not an approval or project-specific authoritative dataset):

```json
{"schema_version":1,"sources":[{"source_id":"tatoeba","publisher":"Tatoeba","origin_prefix":"https://tatoeba.org/","license":"CC-BY-2.0-FR","redistribution_approved":false}]}
```

Every sentence specifies its real source URL, author/contributors, publisher, text license + URL and full attribution; original language and Unicode text remain unchanged. `context_id`, `situation` (one of greetings/travel/health/work/food/home/emergencies/shopping/administration/study), `construction` (positive/negative/interrogative), `register`, `politeness`, `dialect`, `sense_refs` and `grammar_refs` are independent annotation layers. `sentence_cefr` and `word_cefr` are distinct and default to `null`; a non-null sentence CEFR needs its own `cefr_evidence_url` and review. No inferred translations, rules, CEFR ratings, or editor verdicts are generated.

`translations` is a directed list of `{target_source_id, target_sentence_id, target_language, direction, evidence_url}`; direction is literally `{source language}_to_{target language}`. A target must exist in the persisted index for the link to be publishable. Translation origin URLs must be independently reviewed; URL presence is not semantic correctness. Records with same normalized Unicode surface + sense/context are **retained** and flagged for review rather than silently deduplicated. Distinct contexts are not collapsed. Wrong-script content is rejected, but same-script language identification (English vs German, etc.) requires independent native-language review.

## Genuine pilot sources and attribution

The five fixtures are real Tatoeba text examples: German #6010648, Arabic #4925881, English #373330, Spanish #431975 and French #373345. The fixture quotes exact published sentences, tracks the publisher/authors and the CC BY 2.0 FR license, and links only source-logged translations. Reference: [Tatoeba reuse guidelines](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus), [Tatoeba downloads](https://tatoeba.org/en/downloads), and each per-sentence source URL in the fixture. There is **no source archive checksum** because no official export artifact was ingested, and no sentence is labeled human-editor-verified. `REQUIRES_REVIEW` is intentional while the external license/sense/grammar/reviewer registries remain unavailable. The fixture is **not a production-publishable pack**.

The SQLite index is for incremental ingestion and local retrieval; the repository's existing pack compiler is not modified. A future integration should consume only approved per-language gzip files and provide a versioned compatibility adapter, rather than changing `manifest.json` or private runtime code as part of this scoped task.

## Operational caveats

- Unparseable lines are counted as rejected, with non-content line number and exception type; no potentially private text appears in diagnostics.
- Unicode source text is not NFKC-folded on export. NFC is used only for duplicate detection. Arabic combining marks, RTL text and CJK punctuation survive JSONL and UTF-8 gzip unchanged.
- Accepted data require both separate redistribution approval and pedagogical review. Text-level Tatoeba CC BY 2.0 FR does not cover recordings; no audio is imported.
- A stored record that changes after initial ingestion gets an irreversible `change_hold` until a separately designed reapproval workflow exists; deleting or rewriting local history is not a substitute for editorial revision control.
