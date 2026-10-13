# Agglutinative / morphologically rich language adapter (read-only, v1)

**Status: capability-only; zero production forms admitted.** This extension does not import a dictionary, generate a form or claim dataset permission. All morphology facts must pass separate source and release rights reviews (`legal/ledger/`); the public source ledger was empty at development time. `canonical_declared` means an **unreviewed capability declaration** in the public registry or `standards/morphology/feature_overrides.json`, not a verified paradigm or redistributable attestation. `unknown` remains unknown.

The 14 explicit, independent language models use the exact IDs/families/scripts in `catalog/language_registry.v1.json`: **tr, az, uz, kk, ky, tk, tt, ba, ug** (nine Turkic); **fi, et, hu** (three distinct Uralic); **mn** (Mongolic); **eu** (Basque, language isolate). Family classification is not a generation strategy. The models expose possible dimensions individually, including case, possession, number, person, tense/aspect/mood, agreement, ergativity, vowel harmony, stem alternation, consonant gradation, compounding, derivation and ordered suffix slots, but do not pretend these are verified for each language or lexeme. The current canonical override explicitly declares vowel harmony for tr/az/kk only; unknown values for other languages are not negative linguistic claims.

`profile(language)` reports canonical declarations and unverified/unknown dimensions. `audit(language, shard)` reads **only** a path of the form `tools/linguistic_extensions/agglutinative/shards/<lang>/<name>.jsonl`, streaming UTF-8, validating language-scoped lemma and sense, independently registered script/variant, exact Unicode NFC, source IDs and admitted SHA-256, positionally ordered *attested* morphemes, and bounded records. The JSONL record must contain:

```json
{"language_code":"tr","lemma_id":"tr:source-lemma:1","sense_id":"tr:source-sense:1","lemma":"...","form":"...","script":"Latn","features":{"case":"..."},"morphemes":[],"evidence":{"status":"verified","generated":false,"source_id":"<approved-source-id>","dataset_version":"<exact-source-version>","artifact_sha256":"<64 lowercase hex>","attestation_id":"<attested-entry-id>"}}
```

This is a **schema example only**, not a real morphological attestation. For actual records all text and dimensions must be independently attested; `script` must match original spelling (no inferred Latin/Cyrillic/Arabic/Mongolian conversion). `morphemes` can carry `{kind,surface,position,slot}` with zero-based positions in observed order. `processes` may hold observed alternation/compound descriptions. A valid record is not permission for multiplying forms or extrapolating suffix order to other lemmas, dialects, scripts or languages.

Before any real shard can pass, `legal/ledger/sources.json` must contain an independent `APPROVED_FOR_REDISTRIBUTION` morphology source with reviewer and exact SHA/version, and exactly one corresponding *reviewed* `legal/ledger/daily/*.json` morphology release candidate with matching shard SHA-256, source refs and notices. The authoritative Route 05 admission gate remains a **separate mandatory prerequisite**; this extension's local checks do not replace it or grant licenses. Unknown/mismatched/synthetic/reconstructed data **fail closed**. Test fixtures simulate an admitted record in a temporary test directory only; they never ship to production. Duplicate JSON, traversal, symlinks, unregistered scripts and unverifiable variants are rejected.

The audit returns a **per-language** checkpoint SHA-256, lemma/form counts (within a maximum 10,000 forms / 4 MiB per shard), observed and unknown grammatical dimensions, unknown case inventory, and no fabricated counts. To avoid combinatorial growth, there is no precomputed paradigm, global form index or pairwise materialization. Lookup validates an entire shard first and scans it on demand, caps returned forms at 128, and never returns guesses. Source versions and schema must be vetted before integration with pack consumer contracts.

From the repository root:

```bash
python3 -m unittest discover -s tests/linguistic_extensions/agglutinative -p 'test_*.py' -v
python3 tools/linguistic_extensions/agglutinative/engine.py --language tr
# After real source admission only:
python3 tools/linguistic_extensions/agglutinative/engine.py --language tr --shard tools/linguistic_extensions/agglutinative/shards/tr/<approved>.jsonl
```

The public read-only `.github/workflows/agglutinative_morphology_qa.yml` runs tests with `contents: read` and no secrets, cache, paid runners or artifact retention. Manual runs may check one independently approved shard per run; `GITHUB_RUN_ID`, checkout SHA and checkpoint hash are preserved in the run's job summary. **No shard processing run or dataset checkpoint is claimed until a real source passes the legal gate and the hosted workflow executes.**
