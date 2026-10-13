# GHA-04 — Linguistics QA (not a production corpus)

This isolated Python standard-library module implements fail-closed **read-only** checks of the Route 09 `standards/morphology/form.schema.json` attested-form shape. It never modifies the Route 09/11 contracts, source ledgers, content packs, or releases.

## API

- `validate_form(record, registered_languages, pos=None)`: verifies canonical field names, language-scoped lemma/sense IDs, Unicode and language-specific structural tags. POS is optional externally verified lexical metadata, never inferred from a surface.
- `audit_stream(path, sha256, registered_languages, source_id, shards=16)`: bounds line memory, calculates the actual artifact SHA-256, checks JSON duplicates and contradictory roots/patterns with disk-backed SQLite, and reports deterministic shard **membership**. It does **not** write shard datasets or publish an artifact.
- `classify_answer(submitted, expected, other_attestations)`: identifies a wrong morphological form only when another **same-lemma, same-sense** attestation proves it. One-edit spelling mistakes are distinguished; all other uncertainties stay `unverified`.
- `shard_for(record, count)`: SHA-256-based stable partition membership, independent of language family, source row order, or mutable display text.

The module preserves record Unicode verbatim; it does not compute noun gender, derive Perfekt auxiliaries, infer Arabic broken plurals, expand German compounds, fabricate conjugations, or assign language proficiency. German-specific case and gender checks are **not** applied to agglutinative, analytic, CJK, Semitic, or Bantu languages. `components` are evidence metadata only and never prove a compound split.

Run from repository root:

```sh
python3 -m unittest discover -s tests/gha_factory/linguistics -p 'test_*.py' -v
python3 -m py_compile tools/gha_factory/linguistics/validator.py
```

## Dependency and release boundary

All reports are `QA_ONLY_BLOCKED_SOURCE` with `distributable=false`. Current Route 09 attestations are small reference records, not approved GHA-03 production lexical snapshots. Route 05 source ledger approval with immutable original SHA-256, GHA-03 stable lexical identity evidence, Route 11 independent proficiency review, and GHA-02 persistent queue receipts must exist and be verified before a future pipeline consumes production data or dispatches a public workflow.

No GitHub Actions job is added/dispatched in this PR because GHA-03 approved output and end-to-end queue integration are not established. Local synthetic tests do not license a corpus or demonstrate production readiness.
