# DEUTSCH-PRODUCTION-12 — German lexical source rights acquisition dossier
Date: 2026-10-14 (UTC+03:00)
Classification: **BLOCKED_REVIEW — RESEARCH ONLY; NOT A SOURCE ADMISSION**
Base main SHA at branch creation: `7a5a554b7248ec6baa610ba443b747c7643ba9b9`

## Scope and unambiguous release decision

This file records independently discoverable upstream candidate/source-specific rights URLs. It **does not** claim that the original dataset bytes, source SHA256, rights-notice snapshot SHA256, independent human decision, or manufacturing admission has been verified. It is not a substitute for an immutable original snapshot and legal review. Do not copy any value below into a production approval without filling all evidence gates.

**Do not modify `legal/ledger/sources.json` in this evidence-only PR.** The strict v1 admission contract requires an on-disk original artifact path and hash, a local original license snapshot path and hash, and human-approved status. Fake 64-character hashes, publisher guesses and reviewer identities are forbidden. For a large file, retain the original bytes in an independently addressable immutable content-addressed store and arrange a separately reviewed gate implementation; do not weaken `admission.py` or commit a multi-hundred-MB archive to git.

### Candidate A: original German Wiktionary via Kaikki/Wiktextract — existing JSONL ingestion format

| Field | Evidence / state |
| --- | --- |
| Proposed SOURCE_ID | `de-dewiktionary-wiktextract-20260901-CANDIDATE` (proposed only; not registered) |
| Origin / upstream | `https://de.wiktionary.org/` — community Wiktionary text, Wikimedia-hosted |
| Extraction publisher | Kaikki.org, extracted via Wiktextract by Tatu Ylönen; upstream copyright remains with the original Wiktionary contributors |
| Dataset version candidate | Wikimedia `dewiktionary` source dump dated **2026-09-01**; Kaikki raw extraction page reports **2026-10-02**, Wiktextract refs `1a05e46` and `e3d6d4e` (short identifiers are **not** dataset hashes) |
| Raw catalog page | `https://kaikki.org/dewiktionary/rawdata.html` |
| Raw direct retrieval URL | `https://kaikki.org/dewiktionary/raw-wiktextract-data.jsonl.gz` — URL is **mutable**; not an immutable snapshot |
| Declared rights | Kaikki edition index explicitly says extracted material is available under **CC BY-SA and GFDL** as Wiktionary text. Select a specific license route only after independent review of source-specific content/exceptions; no CC0 assumption |
| Source-specific rights notices | `https://kaikki.org/dewiktionary/`; `https://de.wiktionary.org/wiki/Wiktionary:Lizenzbestimmungen`; controlling Wikimedia ToU `https://foundation.wikimedia.org/wiki/Terms_of_Use` |
| Legal terms example | `https://creativecommons.org/licenses/by-sa/4.0/legalcode.en` — generic terms **alone are not proof of a specific source's license** |
| Artifact availability | Publisher advertises about 294 MB compressed for the extraction dated 2026-09-01. No exact retained dataset bytes were downloaded in this execution |
| Artifact SHA256 | **UNVERIFIED / NULL** |
| Original source-specific notice snapshot SHA256 | **UNVERIFIED / NULL** |
| Required obligations if CC BY-SA 4.0 route is approved | publisher/contributors attribution; original URL; license link; indication of changes; ShareAlike for covered adaptations; no additional restrictions |
| Extra risk | Imported examples, images, audio and third-party materials may carry separate terms; exclude until per-record rights verification. Full raw edition covers many language sections; filter only `lang_code == de` under a reviewed exact-source adapter |
| Decision | **BLOCKED_REVIEW** (no verified artifact/notice digest; no independent reviewer and no source approval) |

Reference facts were observed on 2026-10-14 via publisher pages; publisher pages are periodically updated and historical extraction references must be independently rechecked. A source version label is not cryptographic immutability.

### Candidate B: Wikidata Lexeme namespace — preferred licensing simplicity, format adapter missing

| Field | Evidence / state |
| --- | --- |
| Proposed SOURCE_ID | `de-wikidata-lexemes-cc0-CANDIDATE` |
| ORIGIN_URL | `https://www.wikidata.org/wiki/Wikidata:Lexicographical_data` |
| Rights publisher | Wikidata contributors / Wikimedia |
| Source-specific CC0 declaration | `https://www.wikidata.org/wiki/Wikidata:Database_download` and `https://www.wikidata.org/wiki/Wikidata:Licensing` |
| Authentic dump directory | `https://dumps.wikimedia.org/wikidatawiki/entities/` |
| Dataset version | **NOT PINNED**: dated immutable directory and exact lexemes dump object/checksum must be retrieved; `latest-lexemes.json.gz` is **not** a stable snapshot |
| License route | Official Wikidata structured Lexeme namespace: **CC0 1.0**, with commercial/offline reuse allowed; does not include externally hosted media or separate Wiktionary text |
| ARTIFACT_SHA256 | **UNVERIFIED / NULL** |
| LICENSE_EVIDENCE_SHA256 | **UNVERIFIED / NULL** |
| Format limitation | Current GHA-01 / lexical workers are built for Wiktextract JSONL, not Wikidata Lexeme JSON; a separately owned reviewed adapter would be needed, including exact lexeme/sense/form identities and truthful German-only filtering. No inventing Arabic glosses/CEFR/examples |
| Decision | **BLOCKED_REVIEW** (no exact payload, SHA, rights-notice snapshot, human approval or compatible ingestion adapter) |

## Governance & known conflicts

- Current `main` ledger has zero approved source records. No new candidate is released or counted as an admitted source.
- DEUTSCH-EXEC-04 [Draft PR #179](https://github.com/moaz76943-creator/-offline-packs-store/pull/179) proposes a separately verified decision snapshot but remains unmerged and not adopted by existing callers.
- [Draft PR #178](https://github.com/moaz76943-creator/-offline-packs-store/pull/178) changes `legal/ledger/admission.py` and its tests for symlink and contradictory rights safeguards. This evidence-only PR deliberately does not modify those paths. The owners must coordinate final adopted guard behavior before source admission.
- [Issue #71](https://github.com/moaz76943-creator/-offline-packs-store/issues/71) confirms source and coordinator dependency; [Issue #65](https://github.com/moaz76943-creator/-offline-packs-store/issues/65) confirms production lexical queue integration is not completed.
- Neither a `[skip ci]` commit nor a draft PR is an approval. No production pack, active manifest, downloader, workflow or public-facing claims are changed.

## Exact blockers / gate required for next owner

1. Independent Route05 source reviewer chooses the **actual upstream artifact** and acceptable license route; investigate mixed content and whether commercial distribution inside the application can honor ShareAlike (for candidate A).
2. Download pinned, precisely versioned **original bytes** with an authenticated retrievable immutable locator and safe size/transport rules; compute local streaming SHA256, retain size and retrieval evidence; for Wikidata use a dated lexemes snapshot, not `latest`.
3. Save a direct source-specific legal notice snapshot (not solely generic CC legalcode), hash the exact original bytes, and identify immutable revision URL or revision ID; do not invent hash if bytes unavailable.
4. Obtain independent human reviewer, publication of a decision URL, and verified decision-byte hash bound to SOURCE_ID + version + artifact SHA + license SHA as required by proposed #179; do not self-approve.
5. Produce a legally and technically approved, *repository-confined* source shard compatible with the current admission contract or integrate an explicitly reviewed secure external-snapshot mechanism without bypassing hash checks. Assess the 256 MiB source limit in the proposed #179 CLI for large Kaikki archives; shard safely with original-versus-derived provenance.
6. Add the real schema-valid source record in `legal/ledger/sources.json` only after the above; ensure output attribution/ShareAlike and per-record provenance for the final candidate. Verify the no-regression legal admission gate and targeted tests.
7. Keep publication NO-GO until both source rights admission and Issue #65 queue/release gates pass.

## Validation truth

| Check | Result |
| --- | --- |
| Source-specific official rights URLs researched | **PASS — documentary evidence only** |
| Actual dataset file downloaded, immutable snapshot and SHA256 | **NOT_VERIFIED** |
| Original legal-notice bytes saved and SHA256 verified | **NOT_VERIFIED** |
| Full source registry schema admission | **NOT_APPLICABLE** — intentionally zero additions; no forged source |
| `python3 legal/ledger/admission.py --repo-root .` | **NOT_RUN** — no local checkout was accessible in this session; baseline expected NO-GO is not represented as a test result |
| `python3 -m unittest discover -s legal/ledger -p 'test_*.py' -v` | **NOT_RUN** — no local checkout |
| Hosted workflow tests | **NOT_RUN** — no new Actions or billing |
| Independent human license review / approval | **NOT_GRANTED** |
| SOURCE_ADMISSION / RELEASE | **BLOCKED_REVIEW / NO-GO** |

All external observations are research, not a redistribution warranty. Never treat a publisher webpage's current revision as evidence of already archived bytes without a retained exact snapshot.
