# Admission to canonical lexical v1 and SQLite v2

Adapter: tools/pack_v2/admission_adapter.py. This is a staging addition to the
existing pack_v2 compiler, not a second pack factory or publication route.

## INPUT_CONTRACT

- Admission queue.json: schema_version 1.0.0, status ACCEPTED_FOR_QUEUE,
  publication_approved false, source_id, dataset_version, language,
  source_artifact_sha256, license_evidence_sha256, actual_accepted_records,
  and ordered jobs with sha256, record_count and verifiable resume_id.
- Each partition-########.jsonl record has content.word, content.pos,
  content.senses[], source_line and source_line_sha256 plus source/rights
  evidence SHA values.
- Script comes from the language registry and provenance comes from the
  independent Route 05 ledger. For an approved real source, the adapter uses
  the existing compiler's approval gate and re-extracts exact pinned original
  source lines to reject fabricated admission content.

## OUTPUT_CONTRACT

A new directory, atomically created, contains bounded LANGUAGE-########.json
canonical documents (contract_version 1.0.0), plus report.json. Every
document includes lexemes, separate senses, and empty translations, examples
and relations. No unverified CEFR, Arabic translation, IPA or frequency is
fabricated. Identical records are deduplicated through a disk-backed SQLite
index, while repeated distinct gloss occurrences remain separate senses.

Each canonical shard can independently enter pipeline.compile_pack for
conformance verification. Shards are NOT complete language packs and must
not be published individually as complete language coverage. Source admission
approval is not release candidate approval. Reports are marked either
FIXTURE_ONLY_NOT_FOR_PUBLICATION or
SOURCE_APPROVED_CANDIDATE_NOT_PUBLISHED.

## Fixture verification command

    python3 -m unittest tools.pack_v2.test_admission_adapter -v

The fixture tests build a synthetic queue and ledger in temporary directories.
The real source ledger on main is empty. A CLI invocation with fixture evidence:

    python3 -m tools.pack_v2.admission_adapter \
      --queue /path/to/fixture-admission/queue.json \
      --out /path/to/new-output-directory \
      --repo-root /path/to/fixture-repo --fixture-only

Omit --fixture-only only for a genuinely independently approved source in
the ledger. The adapter verifies source hash, rights evidence and original
lexical lines before staging. It never publishes or modifies the ledger.

## Fail-closed limitations

1. Admission flattens Wiktextract senses and excludes examples, human audio,
   unchecked translations and CEFR. No sense grouping can be recovered.
2. No immutable upstream lexeme/sense ID survives raw source edits. The
   deterministic line-hash IDs survive reruns and repartitioning, but changed
   source lines need a reviewed identity reconciliation before learner-linked
   updates.
3. Unsupported POS and script directions are rejected, not guessed.
4. The existing compile_pack accepts one canonical JSON (20 MiB max).
   This adapter shards large inputs and requires separately reviewed
   aggregation before a whole-language production build.
5. Hosted exact-head checks, source approval, candidate QA, and final release
   publication are separate gates; no synthetic fixture is release-ready.

Only tools/pack_v2/** is modified by this task.
