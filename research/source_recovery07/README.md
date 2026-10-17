# DEUTSCH-RECOVERY-07 — real lexeme research shard, NOT admitted

**Decision:** `REVIEW_REQUIRED / NO-GO`. One **real, manually transcribed historical** Wikidata German lexeme (`L2957`, Haus) is captured in `lexeme_L2957_candidate.json`. The JSON is a **derived research excerpt**, not original Wikibase JSON downloaded from the publisher, not a synthetic production fixture, and not an immutable ORIGINAL source artifact.

## Identifiers, rights and evidence

- Exact lexeme revision: https://www.wikidata.org/w/index.php?title=Lexeme:L2957&oldid=2321564793
- Canonical ORIGINAL JSON endpoint to obtain: https://www.wikidata.org/wiki/Special:EntityData/L2957.json?revision=2321564793
- Source-specific rights: https://www.wikidata.org/w/index.php?title=Wikidata:Copyright&oldid=1523614187 ; https://www.wikidata.org/wiki/Wikidata:Licensing
- License selected for **Lexeme structured data only**: `CC0-1.0`, subject to independent review and rights exclusions.
- Original downloaded publisher JSON: **NOT OBTAINED**, original artifact SHA-256: **UNKNOWN**. The candidate's own SHA-256 is **not** the publisher-artifact SHA-256.
- Original source-specific notice bytes: **NOT OBTAINED**, notice SHA-256: **UNKNOWN**.
- Historical source page displayed a CC0 footer and stable form/sense IDs. Content is human transcribed; automated equivalence to canonical JSON **NOT VERIFIED**.
- No third-party quotations, images, Commons audio, Arabic translations or CEFR claims have been copied/created.

## Source comparison

| Candidate | Corpus rights | Existing pipeline fit | Decision |
| --- | --- | --- | --- |
| German Wiktionary original | CC BY-SA / GFDL for relevant text, exceptions per record | Requires complex attribution and license-route review | Defer |
| Kaikki / Wiktextract German extraction | Inherits Wiktionary text rights, **not** MIT (MIT applies to code) | Existing JSONL pipeline; mutable raw download URL | Defer |
| Wikidata Lexemes | Official structured Lexeme namespace under CC0 | Requires **reviewed Wikidata-specific adapter**; no Arabic gloss/CEFR guarantee | Preferred for rights-scoping, NOT YET ADMITTED |

Sources: Wikidata:Copyright, Wikidata:Database_download, Kaikki /dewiktionary/ and /dewiktionary/rawdata.html, Wiktextract LICENSE, German Wiktionary copyright/Terms of Use. The source text includes no automatic license for Commons media or other sites.

## Reproduction and bounds

```
python3 -m unittest discover -s research/source_recovery07 -p 'test_*.py' -v
sha256sum research/source_recovery07/lexeme_L2957_candidate.json
```

Local authoring run (2026-10-14): **6/6 focused tests PASS**, candidate excerpt SHA-256 `c692eadba8fec6ec42deec76e18431997a8c2604fb136196d798629a5bde427a`. This digest refers **ONLY** to the derived local JSON bytes. The SQLite smoke test checks local stable foreign keys and `integrity_check`, NOT full canonical SQLite v2 conformance. GitHub-hosted CI: **NOT_RUN**. No production workflow was triggered.

Direct publisher JSON retrieval from this runtime failed due outbound DNS/network restrictions (the web renderer also could not fetch JSON); no source hash was fabricated. Upstream immutable entity revision is an identity locator, not bytes in repository.

## Required handoff (source owner, reviewer, integration owner)

1. In a network-capable free environment, retrieve **byte-identical** original revision-specific JSON and the source-specific license notice bytes through bounded HTTPS, retaining exact bytes and their independently computed SHA-256, size, date and publisher response/provenance. Do not fetch a mutable “latest” and claim immutability.
2. Confirm original revision and `Q188` German language from the actual JSON; compare this transcribed subset against original source. Quarantine differences rather than silently correcting provenance.
3. Obtain independently reviewable human rights decision explicitly bound to source/artifact/notices SHA and media exclusions. Coordinate with canonical Route05 and Draft PRs #178/#179/#182/#192 and Jules; do not modify or duplicate their owned files.
4. Implement/adopt a reviewed canonical Wikidata Lexeme JSON adapter without bypassing `tools/gha_factory/source_snapshots` staging or `legal/ledger/admission.py`. Keep stable lexeme (`L...`), form (`L...-F...`) and sense (`L...-S...`) identities; only validate true SQLite v2 after integration.
5. Only then consider `legal/ledger/sources.json` status transitions. Issue #65 queue support, Issue #71 source/hosted gates, independent review and release QA remain required before packs are published.

**Do not treat this candidate or the six tests as SOURCE_APPROVED, PACK_AVAILABLE or PRODUCTION_READY.** No manifests, ledgers, dispatcher, release gates, media, private-app data or live tasks were changed.
