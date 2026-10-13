# European inflection — source-gated contract (19 registered languages)

This lane specializes, but **does not rewrite**, the existing public `standards/morphology/form.schema.json`, `feature_overrides.json`, 100-language canonical `catalog/language_registry.v1.json`, or the Route05 source admission gate (`legal/ledger/admission.py`).

The 19 independent profiles are **contracts, not a corpus**. `ru uk pl cs sk bg sr hr bs sl mk be` are Slavic, `el` is Greek, `lt lv` Baltic, and `ga cy gd br` Celtic. Every profile individually declares its cases, numbers (including Slovenian dual), genders, animacy, aspects, mutation types, constructions, stress evidence modes and exact registered writing systems. Bulgarian and Macedonian **do not inherit a six-case paradigm**. The Celtic trigger for every mutation is mandatory. Serbian/Bosnian Latin/Cyrillic forms are distinct **source-backed attestations**, never automatic conversions. Greek accent evidence must match original NFC spelling. Lithuanian and Latvian stress evidence are independently typed; no inference or stress transfer.

## Provenance contract

Input is UTF-8 NFC JSONL, with one record per line, at:

`tools/linguistic_extensions/european_inflection/shards/<sha256-of-exact-file-bytes>.jsonl`

Every record contains a language-scoped `record_id`, `lemma_id`, and `sense_id`; an exact `lemma`, `form` and registry `script`; a `category`; a sparse `features` map; `paradigm_complete:false`; `evidence_status`; and nonempty `source_refs` with exact Route05 `source_id`, `dataset_version`, `artifact_sha256` and immutable source `locator`. `verified`, `predicted`, `gap`, and `disagreement` are **never combined**. Disagreement requires two independently approved sources and an explicit note; gaps and predictions require an explanatory note. `verified` alone is attested, not inferred.

Before any production processing, the runner executes the **existing, full Route05 `evaluate` gate**, including approval, identity, snapshot hashes and rights. It rejects empty/unapproved sources, altered shard names, script confusion, duplicates, unknown features, control characters and inferred full paradigms. A verified record with a feature absent from a public v1 capability can remain in the isolated extension only; `to_public_morphology_form` rejects transfer unless every mapped base feature is explicitly `supported`. There is no release/manifest write permission.

Outputs are isolated, SHA-named `verified.jsonl`, `predicted.jsonl`, `gap.jsonl`, `disagreement.jsonl` and deterministic `summary.json` under a caller-specified output directory. Only exact evidence goes to `verified`. Exact per-language counts are calculated from admitted records, with a SQLite on-disk uniqueness index (bounded RAM). There is no paradigm synthesis. Byte-identical inputs generate identical classification; outputs are collision-checked. Output directories must not exist at run start: all shard outputs are staged in a temporary sibling and atomically renamed only after every shard succeeds. If a later shard fails, no partial verified output is published. Shards are immutable, at most 64 MiB each, and input lines capped at 64 KiB.

## Running on a public standard runner

```bash
python3 -m unittest discover -s tests/linguistic_extensions/european_inflection -p 'test_*.py' -v
python3 tools/linguistic_extensions/european_inflection/validator.py --repo-root . --shards-dir tools/linguistic_extensions/european_inflection/shards --output-dir /tmp/european-inflection
```

The dedicated `.github/workflows/european_inflection_qa.yml` uses a standard public `ubuntu-latest` runner, read-only permissions and no paid artifact upload. It prints the GitHub run ID. **When the approved ledger/shards are empty, status is `BLOCKED_NO_ADMITTED_SHARDS`, total = 0 — not 19 fully covered languages.** Do not create synthetic production shards or claim content coverage from the negative fixtures. Source identity, verified-versus-predicted status and provenance must be retained into any later packaging pipeline by a separate authorized integration.
