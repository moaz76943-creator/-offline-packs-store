# Source-rights research — DEUTSCH-IMPROVE-09
Date: 2026-10-14. Evidence type: publisher-level rights research, **NOT** artifact admission.

## Snapshot and license evidence

| Candidate | Publisher-level origin and rights evidence | Commercial redistribution and adaptation | Actual corpus SHA256 | Preflight decision |
| --- | --- | --- | --- | --- |
| German Wiktionary original text | https://de.wiktionary.org/wiki/Wiktionary:Lizenzbestimmungen and https://foundation.wikimedia.org/wiki/Terms_of_Use | Wikimedia text uses CC BY-SA / GFDL routes; commercial reuse and adaptation require the selected license conditions, author credit and ShareAlike where applicable; external quotes/media can have separate terms | NOT_VERIFIED | REVIEW_REQUIRED |
| Kaikki German Wiktextract raw data | https://kaikki.org/dewiktionary/index.html and https://kaikki.org/dewiktionary/rawdata.html | Data inherits Wiktionary terms, not the MIT license for the extraction software; output may contain imported material. Raw extraction download link is mutable; do not infer source snapshot hash from date or tool commit | NOT_VERIFIED | REVIEW_REQUIRED |
| Wiktextract extraction code | https://github.com/tatuylonen/wiktextract/blob/master/LICENSE | MIT governs software; it **does not** relicense the extracted Wiktionary dictionary as MIT/CC0 | NOT_APPLICABLE to corpus | REVIEW_REQUIRED for corpus |
| Wikidata structured Lexemes | https://www.wikidata.org/wiki/Wikidata:Licensing and https://www.wikidata.org/wiki/Wikidata:Copyright | Lexeme structured data is declared CC0, separate from Wiktionary text and external media; the canonical adapter is not yet demonstrated | NOT_VERIFIED | REVIEW_REQUIRED |

## Facts and limits

- The official terms permit commercial reuse of Wikimedia text subject to obligations. CC BY-SA can require attribution, modification notices, ShareAlike and no additional restrictions. Third-party examples, file descriptions, images and recordings may carry distinct conditions.
- The live Kaikki raw page describes a source dump and extraction but is continually updated. Search caches showed different editions/dates; this is **not** a cryptographically pinned source snapshot. Never compute a SHA256 from parsed webpage summaries or publish a guessed digest.
- Wikidata official licensing explicitly covers Lexeme structured namespace under CC0, **not** all content linked from Wikidata; this is the comparatively simpler rights candidate but may lack the Arabic translations, CEFR, examples or audio the product needs.
- The current canonical `legal/ledger/sources.json` contains zero registered sources; `manifest.json` contains zero production packs. PR #182 is a rights research dossier, #186 creates a licensing ledger proposal, and #187 a compatibility preflight proposal. All were Draft during this review.
- Original **corpus archive bytes and original source-specific notice bytes were not downloaded and retained** for this audit. Therefore actual publisher-artifact SHA256, authoritative notice snapshot SHA256, immutable identity and independent human approval remain **NOT_VERIFIED**. A unit-test fixture hash is not a published source hash.
- No legal approval or automatic production source acceptance is asserted; `legal/ledger/**` is read-only in this task.

## OWNER_ACTION (exact blockers)

1. Source owner chooses a real dated/pinned German data snapshot and stores the **original byte-identical artifact** in a bounded trusted content-addressed store; calculate its streaming SHA256 and retain immutable retrieval metadata. Avoid committing large dumps to Git.
2. Rights reviewer retains the **source-specific rights-notice bytes** with their own SHA256, checks external examples/media and documents how Attribution, ShareAlike and no additional restrictions are satisfied.
3. Owner independently records signed/reviewable approval bound to both hashes in canonical `legal/ledger` after #178/#179 and ongoing Jules ownership issues are resolved.
4. Integration owner runs canonical admission, adapter/compiler, queue and hosted release gates; never infer `PACK_READY` from this report or from fixtures.

**Publication decision:** BLOCKED/NO-GO until the independent source and release gates pass.
