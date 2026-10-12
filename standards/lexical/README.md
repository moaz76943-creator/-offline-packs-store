# Multilingual lexical contract (public reference implementation)

Contract `1.0.0`; SQLite mapping `2.0.0` (`PRAGMA user_version=2`). This directory is an **opt-in** contract. The live `tools/compile_store_packs.py` remains unchanged and does not yet ingest this document shape. Nothing here certifies that published legacy `.pack.gz` files contain these records. The schema models linguistically attested records; it does not generate, extrapolate, or license lexicon content.

## Model and identity

- A `lexeme_id` identifies one lexical entry, not a spelling: homographs can have separate IDs. A `sense_id` identifies a distinct meaning under a lexeme; many senses share one `concept_id`. Reuse stable IDs after publication; no derivation of IDs from mutable surface text. All IDs are lower-case namespaced tokens. The document ID and contract version are independent.
- Language is BCP-47, script ISO 15924, dialect optional, and written direction script-specific when known. No grammatical feature is mandatory unless actually attested. `null` means unknown/not recorded, not grammatically absent. Forms have attestation and feature maps for person, number, tense, aspect, mood, voice, case, gender/class, definiteness and languages' other relevant categories. Unasserted features stay absent. Morphemes/roots/patterns/components and pronunciation variants are optional; do not synthesize IPA or stress.
- A sense carries contextual meaning, domains/subdomains/semantic tags, register, frequency and difficulty as distinct fields. Level assignments always pair `framework_id` with `level_id`; CEFR is neither presumed nor mandatory. Directed translations connect *two existing sense IDs*; reverse edges must be independently attested. With 100 supported languages storage grows with attested records/edges, not 100×100 language pairs.
- Per-record `source` includes stable publisher, source version, exact origin URL, retrieval identity, locator, license ID, publication review status and optional SHA-256 of source artifact. Embedded forms inherit lexeme provenance only when they lack an explicit `source`. For publication, all top-level records require approved non-fixture provenance with an actual artifact hash; an independent license ledger must still verify reuse, attribution, share-alike, and distribution constraints. The validator does **not** declare a license compatible.
- The positive and negative fixtures contain deliberately tiny **self-authored illustrative test vocabulary**, marked `fixture_only=true`, `publication_approved=false`, `LicenseRef-SyntheticTestFixture`. They are NOT a corpus or a real licensed dataset and fail the publication gate.

## Commands

```sh
python3 -m pip install 'jsonschema>=4'  # open-source, only if not already available
python3 standards/lexical/validate.py standards/lexical/fixtures/positive.json
python3 standards/lexical/sqlite_v2.py standards/lexical/fixtures/positive.json /tmp/lexical-fixture.sqlite
python3 -m unittest discover -s standards/lexical -p 'test_*.py' -v
python3 -m compileall -q standards/lexical
git diff --check
```

CLI uses local files only. `--publication` rejects fixtures, missing hashes and unapproved records. SQLite output must not already exist (to prevent overwriting user DBs). No network, extraction from private application stores, corpus import, or dataset harvesting occurs.

## SQLite v2 projection and migrations

The mapper creates `metadata`, `schema_migrations`, `concepts`, `lexicon`, `senses`, `translations`, `examples`, `lexical_relations` and `lexicon_fts`, as well as a legacy-compatible `lexemes` read view. `lexicon` preserves `id`, `surface`, `part_of_speech`, `direction`, `fields_json`, `cefr_level`, `frequency_rank`, `sort_key`, plus `pos`, language, script, dialect, source. All optional features stay in canonical `fields_json` or `payload_json` and roundtrip without loss. Missing CEFR and ordinal rank remain SQL NULL, never fabricated. Cross-entity foreign keys and FTS integrity are tested. Actual source order is irrelevant: each table is populated by a documented Unicode NFKC-casefold key then stable ID, or by stable ID.

FTS5 uses `unicode61` with accent stripping disabled; indexes written surfaces, lemmas, attested definitions and **outbound** translation text. For scripts without whitespace segmentation (e.g., Han, Japanese, Thai), consumers must use suitable segmenters or exact/prefix fallbacks; do not interpret Unicode61 matches as universal morphological analysis. FTS has no reverse translation inference.

The preexisting store compiler creates a different SQLite v2 layout. This mapper is a reference contract and has **not** been wired into that compiler. `check_mapping_version` accepts only a recognized user version and recorded mapping/contract pair. Any migration from unknown or legacy layouts must be separately implemented with verified provenance and explicit ID mapping; do not drop/rewrite historical data or silently assign IDs. For schema evolution, preserve `1.x` identity semantics, introduce new migration scripts/version entries, and test both old reads and new reads before changing publication pipelines.
