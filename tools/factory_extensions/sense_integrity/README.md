# Sense integrity — independent review-only QA

This layer is additive; it does not edit or wrap standards/lexical, Jules PR #95 or Jules PR #87. It never deletes, deduplicates, generates a translation edge, rewrites a canonical ID, publishes a pack, or claims source licensing.

## Input and execution

Each snapshot directory must contain five UTF-8 JSONL files: lexemes.jsonl, senses.jsonl, translations.jsonl, relations.jsonl, examples.jsonl. Rows mirror lexical contract 1.0.0 records, but this is an *interchange format*, not native JSON document ingestion. Validate upstream documents against standards/lexical/validate.py first; no existing pack compiler is wired to this layer.

Example CLI:

    python3 -m unittest discover -s tests/factory_extensions/sense_integrity -p 'test_*.py' -v
    python3 -m tools.factory_extensions.sense_integrity.audit --input-dir path/to/snapshot --previous-dir path/to/older --ledger legal/ledger/sources.json --registry catalog/language_registry.v1.json --out-dir /tmp/sense-qa --shard 0 --shards 4
    python3 -m tools.factory_extensions.sense_integrity.audit --input-dir path/to/snapshot --previous-dir path/to/older --ledger legal/ledger/sources.json --registry catalog/language_registry.v1.json --out-dir /tmp/sense-qa --shard 0 --shards 4 --resume

## Semantics

- Lexeme IDs, sense IDs, concept IDs and directed translation IDs are separate identities; a written word is never a primary key.
- Distinct homographs, polysemous senses, grammatical derivations, inflections, compounds and orthographic variants are preserved, never silently merged. Explicit source-backed relations remain edges.
- Candidate grouping uses NFC-only written lemma plus exact language, script, POS, dialect, register and optional homograph discriminator. No casefold, diacritic stripping, transliteration or aggressive cross-script Unicode normalization.
- Orphans, mismatched directed translation target language, example leakage, cross-language relation suspicion, conflicting within-lexeme concept definitions, removal and reassignment of prior IDs, and source-ledger version/hash/license mismatches produce reviewable findings.
- Accepted senses require BOTH lexeme and sense source publication approval and an *explicitly approved* matching legal ledger entry; fixture-only sources do not count. SHA assertions are compared, but this tool does not download or verify source artifact bytes and does not decide license compatibility.
- Reviewer dispositions must be JSONL objects with candidate_id, disposition (distinct / merge_approved / rejected / needs_review), reviewer and review_reference. A disposition never changes content.

## Outputs

conflicts.jsonl: sorted review/blocking issues; candidates.jsonl: candidate header and streamed members, not an in-memory member list; merge-plan.jsonl: propose/retain/review suggestions with canonical_write=false; per-language.json: 100 registry-language metrics (accepted senses, total senses, unresolved groups, reviewer outcomes, conflicts); checkpoint.json: SHA-256 input fingerprint and output digests. Four shards are disjoint by hashed ID; add counts across shards rather than reporting a shard as global.

Output is write-once and cannot exist unless --resume validates all input/output digests. SQLite indexing is on disk, JSONL is read a line at a time (2 MiB maximum per row), and index construction never loads a whole corpus into RAM. Disk usage grows with source count. Repeated replays need a persistent caller-managed filesystem; hosted Actions runners are ephemeral, and this isolated workflow deliberately does not publish or upload checkpoints or artifacts.

## Explicit limits

No latent semantic similarity inference, language translation generation, automatic conflation of senses, legacy .pack.gz ingestion, production-readiness claim, standalone legal license verification, approved source downloading, automatic cross-run checkpoint persistence or automatic merge. A previous complete snapshot is required to detect historical removals. The live public source admission ledger is empty, so synthetic tests cannot count as accepted production corpora.

Public workflow triggers on PR or manual dispatch. Indexing needs an in-repository approved JSONL snapshot path supplied at dispatch time; otherwise only synthetic regressions run. Hosted workflow run IDs must be recorded after an actual dispatch, never fabricated.
