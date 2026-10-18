# Strict pack conformance adapter

Owned task: `SQLITE-CONFORMANCE-20261013`. Only this directory, its dedicated
tests, and `gha_pack_conformance.yml` are mutable. PR #40 owns
`tools/pack_conformance`; PR #66 owns security_fuzz; neither is modified.

Reuses `tools.pack_v2.pipeline` DDL/compiler and GHA-06 candidate inspection.
Adds strict UTF-8/JSON scalar validation, duplicate keys, nonfinite numbers,
canonical base64, exact producer DDL (including columns, indexes, FKs and FTS5
configuration), migrations, actual counts, record projection, source evidence,
and every FTS row's surface/lemma/gloss/language. The compiler legitimately
stores other registered languages for directed sense mappings: those are
verified against payloads and `languagesPresent`, never relabeled as the pack
language. Original Unicode remains intact; NFKC casefold only checks sort_key.

The FTS5 integrity command runs in a disposable bounded database copy, never
the input. SQL has a 30-second opcode deadline and a 4 MiB page cache. Archives
are capped at 40 MiB compressed / 120 MiB expanded / 80 MiB SQLite; records at
64 KiB; 1 million rows and 1024 distinct evidence objects. Run under the same
2 GiB address-space, 256 MiB per-file, CPU and wall-time bounds as the workflow.
A per-file limit is not a whole-filesystem quota; this adapter creates just one
SQLite copy, no downloads, caches or durable attack artifacts. Trusted canonical
DDL is the only schema executed. Full corpus processing remains upstream.

```
timeout 120s python3 -m unittest discover -s tests/gha_factory/pack_conformance -v
timeout 45s python3 -m tools.gha_factory.pack_conformance.check --root .
timeout 60s python3 -m tools.gha_factory.pack_conformance.check --root . --archive /isolated/candidate.pack.gz --language de --sha256 <expected-archive-sha256>
```

CLI has no fixture bypass. Synthetic fixtures are API-only, isolated, explicitly
quarantined and never published. An empty ledger yields BLOCKED_SOURCE with
100 REGISTERED_ONLY statuses and zero verified packs. Nonempty ledger yields
BLOCKED_DEPENDENCY: audit alone never verifies a real candidate. Per-record
production proofs must pass existing immutable artifact/license admission.

Signature status is NOT_RUN, publication_approved always false, semantic
accuracy NOT_VERIFIED. Trusted-key selection, signed release identity, replay,
downgrade, editorial linguistic accuracy and actual private consumer/device QA
remain release-owner gates. Do not use this receipt as release authorization.
The existing GHA-06 Ed25519 domain is not a consumer acceptance policy.

Weekly/manual workflow is short, read-only, single concurrency, Ubuntu standard,
no signing secrets, artifact upload, cache, source downloads or manifest writes.
It runs synthetic regressions and a small gate then exits. No heavy work is
eligible with the current empty ledger. GHA-02 v1 only supports
registry_validate and admission_partition_verify: candidate task integration is
BLOCKED_DEPENDENCY pending orchestration-owner versioned handoff (PR #74).
No fabricated queue Issue, checkpoint or run ID is produced.

Tokenizer caveat: unicode61 is not linguistic segmentation, stemming or
normalization equivalence. ß/ss, Turkish case, Arabic vowels, and CJK boundaries
remain distinct; this adapter makes structural claims only. GHA-10 remains the
independent sampled search suite. No performance or production readiness claim.
