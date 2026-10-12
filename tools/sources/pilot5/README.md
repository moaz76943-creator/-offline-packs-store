# Pilot5 — source-backed lexical ingestion

Status as of 2026-10-13: **BLOCKED_SOURCE**. Route 05 ledger legal/ledger/sources.json currently contains zero approved sources. Therefore the genuine accepted counts for German, Arabic, English, Spanish and French are each **zero**. Synthetic fixtures used by the tests are not corpus data.

The importer consumes only locally available **Wiktextract JSONL** from an independently approved source with exact hashes for the original source artifact and source-specific license-evidence artifact, recorded in the Route 05 ledger. It preserves accepted raw UTF-8 records and their hashes in an evidence sidecar, normalizes into the existing Route 06 lexical contract 1.0.0, and emits an explicit unmapped concept identity rather than guessing concepts.

## Candidate upstream dataset — NOT APPROVED

English Wiktionary via Wiktextract/Kaikki: https://kaikki.org/dictionary/rawdata.html .
The Kaikki site reports a 2026-09-02 Wiktionary dump, extracted 2026-10-03. Verify again for any later snapshot. Original rights: https://en.wiktionary.org/wiki/Wiktionary:Copyrights . The material is offered under **CC BY-SA 4.0 and GFDL**, subject to attribution, compatible redistribution terms and third-party rights exclusions. It is not CC0. No sample or source artifact was downloaded, hashed, or approved here.

## CLI after license admission

Run, using real approved source metadata and an actual pinned local raw JSONL file:

    python3 tools/sources/pilot5/pipeline.py --repo-root . --ledger legal/ledger/sources.json --source-id APPROVED_SOURCE_ID --input PATH_TO_REVIEWED_ARTIFACT.jsonl --language de --gloss-language en --out /tmp/pilot5-de-v1 --limit 200

Repeat for ar, en, es and fr with independent output paths, and set gloss language from the source's evidence. English Wiktionary definitions are often in English even for entries in another language. The current Route 06 schema has no separate definition-language field, so provenance.json records that input explicitly.

Each successful invocation creates lexical.json, evidence.jsonl and provenance.json in a new immutable directory. Missing source, unsafe path, missing proof or incorrect hashes return **BLOCKED_SOURCE** (exit 2) without emitting output. Successful ingestion returns **IMPORTED_REVIEW_REQUIRED**, not automatic release permission.

No CEFR, translations, example sentences, unverified morphology or IPA are manufactured. The code preserves only attested source content. Existing raw evidence sidecars must be retained when applying --previous to new daily batches, since each new output directory contains only newly accepted raw lines. A downstream pack release additionally requires the Route 05 publication gate, required rights notices and independent Route 06 publication validation.

## Checks

    python3 -m unittest discover -s tools/sources/pilot5 -p 'test_*.py' -v
    python3 -m compileall -q tools/sources/pilot5
    git diff --check

No network, paid service, CI, or private assets are required.