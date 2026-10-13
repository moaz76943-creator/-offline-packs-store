# Nonconflicting immutable-source lexical adapter

Scope: this directory, its matching tests, and its dedicated **read-only test** workflow.
At inspected main `8c872804a132ae514ac7efe0c01ded3981293564`, PR #63 owns
`lexical/**` and PR #67 owns `source_snapshots/**`; both are open Drafts.
This adapter does not replace them, modify private code, download resources, change
source rights, claim GHA-02 jobs, compile distributable SQLite packs, or publish.

## Live blockers (not approvals)

* Route05 ledger has `sources: []`. Approved production input/lexemes/senses = **0**.
* GHA-02 queue v1 accepts only `registry_validate` and `admission_partition_verify`.
  It cannot accept this lexical task, an external immutable snapshot or durable
  disk checkpoint. No issue with a forged queue envelope is created.
* PR63/67 are dependency handoff points, not merged APIs. Their files are untouched.
* No canonical per-source immutable PanLex sense-link admission exists. Translation
  word matches never become semantic equivalence or reverse links.
* Hosting the test workflow does not imply hosting a 295-minute production worker.
  Global coordinator capacity, immutable external storage and durable checkpoint
  transport must be approved/wired by their existing owners first.

Candidate rights research lives in `docs/gha_factory/provenance/reviewed_sources.json`.
It is not a license grant. Kaikki/Wiktionary is not CC0; UniMorph rights are per
repository; Tatoeba text rights do not authorize audio; noncommercial CEFRLex data
remain unavailable for commercial production. This adapter never changes that ledger.

## Stable callable API

Run from the repository root. Python 3.12+, stdlib for worker logic. The tests also
use the existing Route06 validator (`jsonschema==4.26.0`).

```sh
python3 -m tools.gha_factory.content_ingestion.worker snapshot \
  --source-id REVIEWED_SOURCE_ID --language de > /tmp/verified-descriptor.json
python3 -m tools.gha_factory.content_ingestion.worker process \
  --descriptor /tmp/verified-descriptor.json --checkpoint /tmp/partition.sqlite \
  --shard 0 --shards 1 --limit 100000
python3 -m tools.gha_factory.content_ingestion.worker export \
  --checkpoint /tmp/partition.sqlite --out /tmp/new-immutable-batch
```

A failed first command emits a blocked result, never a verified descriptor. These
commands cannot operate with the current empty ledger. The queue coordinator should
validate descriptor status before handoff, call `process` under its own lease/cap,
and transport the **closed** checkpoint as an immutable, hashed artifact between
runs. A local SQLite checkpoint alone is not durable GitHub-hosted storage.

`worker.snapshot(root, source_id, language)` consumes Route05/GHA01 rights and exact
artifact/license proofs, then additionally requires **review.evidence_path** and
**review.evidence_sha256** in the owner-approved source metadata. It never manufactures
that evidence. Input bytes must remain inside the reviewed repository/evidence root;
external snapshot storage needs a future owner-approved handoff contract.

Only `.jsonl` and gzip are supported. Artifact bytes <=8 GiB; expanded bytes <=16 GiB;
rows <=1 MiB. Full streamed EOF/CRC preflight occurs before any acceptance. Metadata
<=4 MiB. Strict JSON rejects duplicate keys, nonfinite numbers, invalid UTF-8/BOM and
surrogates. Oversized rows drain in bounded chunks and count as one rejected record.
No HTTP means no redirect/DNS/metadata-service access here; approved network retrieval
belongs to PR67, which remains independently gated.

`process(root, descriptor, checkpoint, shard=0, shards=1, limit=100000, batch_size=128)`
rechecks exact source, license, reviewer, registry, ledger and adapter identity.
Source/language/SHA/shard/contract identities are pinned in the checkpoint. Changing
partition count also rejects resume. Shards use SHA-256 stable lexeme identity, so
all rows for the same source lexeme have one owner. Malformed records are owned only
by shard zero. `input_rows` is scanned progress **per shard** and must not be summed
as unique corpus input; `owned_rows`, rejected counts and accepted identities are
disjoint. Startup scans/decompresses again for integrity and skips committed lines;
this is bounded-memory but is not constant-time compressed seeking.

SQLite uses a 2 MiB cache and file temporary storage. Each row is a savepoint;
conflicting scalar morphology rolls back all that row's insertions. Batches commit
checkpoint and content together. A nonblocking flock prevents concurrent checkpoint
owners. All source input is read-only. Output accepts only complete partitions and
uses a new temporary sibling directory and atomic directory rename; existing outputs
are never overwritten. Checkpoint/output roots must be worker-owned local directories.

## Linguistic evidence and limits

* NFC identity preserves case and native spellings (including Turkish dotted I).
* Source-aware IDs retain language/script/POS/etymology/dialect. `logical_id` in the
  checkpoint permits future cross-source review without merging unrelated homographs.
  This adapter does **not** perform automatic cross-source reconciliation.
* One attested source sense remains one sense; its multiple glosses are preserved
  together. Equal glosses with different source qualifiers stay distinct.
* Form tags, auxiliary and reading variants survive as original evidence. Explicit
  number/person/tense/mood/case/degree map only when unambiguous. No German article,
  Perfekt, irregular stem, root, pattern or conjugation is generated. Unknown fields
  remain absent/unverified. Conflicting genders produce review codes.
* Source root/pattern, dialect, native tags, classifiers and IPA/romanization survive.
  Script comes from the canonical registry and actual Unicode gate. Unsupported
  script gates reject records explicitly; 100 metadata IDs are **not** 100 qualified
  linguistic processors. No CJK segmentation, vowel harmony or CEFR is inferred.
* Original raw JSONL plus line SHA preserves every accepted record's provenance,
  unprojected tags, examples and sound metadata. Rights for sentence/audio publication
  are **not** inferred: Route06 examples/media are deliberately not published.
* Sense-local translation evidence retains its source sense; entry-wide translations
  retain an unknown source sense. Target sense stays unknown until a reviewed semantic
  resolver supplies direct evidence. No reverse relationship is generated.

Export streams bounded, self-contained Route06 fragments (one sense each), plus
`evidence.jsonl`, `errors.jsonl`, `review.jsonl`, `translation_review.jsonl`, and
`receipt.json` containing exact counters and SHA-256 per output file. Repeated lexeme
IDs across fragments are intentional: downstream merge must use the same IDs and
retain provenance. Export has **LEXICAL_REVIEW_REQUIRED**, `publication_approved=false`;
it is not a Route07 production pack. The closed checkpoint stores normalized lexemes
once, avoiding duplicated language-pair tables and quadratic resident memory.

## Test and handoff receipt

All linguistic test rows, rights notices and reviewer decisions are **TEST ONLY**.
No fixture enters the public source ledger. Tests cover five pilots, native Arabic,
Turkish/CJK, all 100 registry identities, strict JSON/Unicode, gzip truncation, SHA/proof
mismatch, sense boundaries, attested morphology dedupe, conflicts/rollback, disjoint
partitions, interruption/resume, atomic output and 15,000 repeated synthetic rows
under a 24 MiB Python-allocation cap. This measures streaming overhead, not a million
unique-word production run or total native RSS.

Local command:
`python3 -m unittest discover -s tests/gha_factory/content_ingestion -p 'test_*.py' -v`.
The new workflow uses public `ubuntu-latest`, 15-minute timeout, read-only permission,
768 MiB address-space and 600-second CPU bounds, with no cache/artifact or release
writes. `[skip ci]` commits mean hosted checks must be manually dispatched on the
exact PR ref with an authorized Actions client. Do not merge before actual required
checks pass. A missing dispatch tool/run ID is NOT test success.
