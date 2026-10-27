# Revision-pinned Wikidata source review — 2026-10-23

Status: **REVIEW_REQUIRED — no source admission or publication approval.**

This dossier fills the artifact and rights-snapshot gaps in the existing source review process. It is a bounded three-entity API capture, not a complete Wikidata dump. All original responses are retained without modification. The production ledger remains unchanged and empty.

## Exact decision requested

An independent authorized human reviewer must decide whether the exact structured Lexeme snapshots below may be redistributed commercially/offline under CC0-1.0, with their attested lemma, POS, forms and sense records. Confirm that this approval covers only structured Lexeme data, not linked media, quotations from external sources or text in other Wikidata namespaces. Source approval would not approve any candidate pack or release.

| Proposed source ID | Revision | Original artifact SHA256 |
|---|---|---|
| `wikidata-lexeme-l1026-r2457144138` | `L1026@2457144138` | `ce04495fa86963798a2bf5b0bbf65880d90268e74d3eed060de944f5f2c5cbb2` |
| `wikidata-lexeme-l3006-r2549891188` | `L3006@2549891188` | `7e3bc9a51337eae5996b382c3ca3083266530ae15e2806a19b13ed9a076372fa` |
| `wikidata-lexeme-l7882-r2548839684` | `L7882@2548839684` | `b147755e4266a4305d6dc2a0670d03025f1b938a4afa87e738ff8a73c370da5d` |

Exact retrieval IDs, URLs, versions and paths are in [proposed-sources.json](proposed-sources.json). Each record explicitly remains `REVIEW_REQUIRED`; no reviewer identity or decision URL has been invented. The canonical source validator accepts the other evidence and reports precisely three `REVIEW_REQUIRED` blockers.

## Rights evidence and earlier authorization

The existing `legal/ledger/evidence/owner-decision-2026-10-18.txt` records broad owner permission to work with Wikidata CC0. It is not an artifact-bound independent decision for these bytes. Do not copy that broad permission into a review descriptor as if it named these snapshots.

The original pinned copyright notice is [copyright-1523614187.txt](copyright-1523614187.txt), SHA256 `a74df271d6e2cceb81f71967fb180c66d08c33a670d14d8b64448ee9ef286396`. It distinguishes CC0 structured namespaces from differently licensed site text. Proposed records reference the existing scoped CC0 evidence at `legal/source_evidence/wikidata-structured-cc0.txt`, SHA256 `234e955b1d8e8b1c58f0b5f7b78f439a465f4badaeabe2ddacedc7d977ca71e6`. The reviewer must reconcile the scope against the retained original notice; this dossier does not weaken the license scanner.

After an actual independent decision, the existing `tools/gha_factory/admission/VERIFIED_SNAPSHOT.md` requires a `legal/ledger/review_snapshots/<source_id>.json` descriptor binding the source ID, dataset version, artifact SHA256, license-evidence SHA256, actual reviewer, repository decision URL, and the retained decision bytes/hash. No such descriptor is fabricated here.

## Reproduced candidate evidence

Existing `tools.language_production.harvest.classify_entity`, `build_overlay.to_document` and `standards.lexical.sqlite_v2.build` produced review-only candidates. Attested form IDs are retained as record locators. Estimated CEFR was omitted; no conjugation, gloss, example or translation was generated. Per-language results are:

| Language | Verbs | Senses | Attested forms | Examples | Directed translations |
|---|---:|---:|---:|---:|---:|
| de | 1 | 5 | 32 | 0 | 0 |
| en | 1 | 19 | 5 | 0 | 0 |
| ar | 1 | 1 | 3 | 0 | 0 |

All three SQLite files have real schema/user_version 2, FTS5, `integrity_check=ok` and zero foreign-key errors. The merged #537 checker passes their structure and correctly leaves source evidence unverified. No legacy `user_version=0` database was relabeled or replaced. Original source/form IDs and raw claims remain in the retained source bytes.

Offline replay (no HTTP requests, new output directory required):

```sh
python3 legal/ledger/evidence/wikidata-20261023/replay.py --out /tmp/wikidata-source-review-replay
```

The replay verifies every input hash, uses existing converters, and checks exact document and SQLite SHA256 values in [review-receipt.json](review-receipt.json). Python/SQLite versions are recorded there. These sample candidates do not prove general 100-language readiness.

## Remaining technical gates

Even after human source approval, `admission.pipeline.route05_source` accepts only `wiktextract-jsonl`, while these originals are Special:EntityData JSON. The existing Wikidata converter must be connected through a separately tested format handoff; relabeling this JSON as Wiktextract is forbidden. The active orchestration `EXECUTABLE` set also has no `lexical_partition` worker adapter. Therefore no READY issue, claim, production worker run or finalizer receipt was fabricated.

Published words: **0**. Published verbs: **0**. Published examples: **0**. Production packs: **0**.
