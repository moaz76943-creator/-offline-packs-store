# Germanic/Romance morphology extension (public evidence-only)

This extension holds **19 explicit independent profiles** anchored to the canonical public registry: Germanic de, en, nl, sv, no, da, af, is, lb, fo, fy; Romance fr, es, it, pt, ca, gl, ro; and classical Italic la. Profiles describe *possible grammatical distinctions*; they do not authorize productive generation of forms.

## Evidence boundary

- Read-only dependencies: catalog/language_registry.v1.json; standards/morphology/** from merged PR #85; Route05 legal/ledger/sources.json; canonical language-scoped lexical IDs. No private inputs.
- The small reference observations in standards/morphology/attested_forms.jsonl are NOT automatically production-admitted. The public Route05 ledger currently contains zero sources, so all 19 languages have **zero approved production verbs, paradigms, nouns and inflections**.
- Engine accepts only explicitly supplied UTF-8 JSONL shards. Each record must identify language_code, lemma_id, sense_id, lemma, form, pos, features, source_id, source_version, source_sha256, evidence_version and record_locator.
- The Route05 source precheck requires morphology kind, APPROVED_FOR_REDISTRIBUTION, exact original artifact SHA-256, separately hashed source-specific rights notice, reviewer decision URL and dataset version. The official full Route05 release admission remains mandatory; this precheck is NOT legal authorization to publish.
- Unicode originals are preserved. Unresolved uncertainty blocks verification. Conflicting forms for the same lemma/sense/features/variant require evidence-based disambiguation, not guessed replacements.
- Language-specific axes distinguish German article/case/declarations, weak/strong/mixed verbs, separable prefixes; English countability/aspect/phrasal senses; Scandinavian gender, definiteness and Swedish supine; distinctive Romance auxiliary, mood, clitic and agreement behavior; Romanian postposed definiteness; Latin case and deponent voice.
- The umbrella registry ID 'no' requires explicit nb/nn variety; 'pt' requires pt-PT/pt-BR variety. Each language has its own allowed feature values, with no family fallback.
- Compound forms require attested auxiliary and components; this does not establish full syntactic/contextual correctness. Official source licensing and manual ambiguity review remain mandatory.

## Run bounded offline checks

From repository root:

    python3 -m unittest discover -s tests/linguistic_extensions/germanic_romance -p 'test_*.py' -v
    python3 tools/linguistic_extensions/germanic_romance/engine.py --root . --language de

For future genuinely admitted, repository-relative source shards (NOT supplied in this PR):

    python3 tools/linguistic_extensions/germanic_romance/engine.py --root . --language de --input tools/linguistic_extensions/germanic_romance/shards/de.jsonl --checkpoint /tmp/de-morphology-checkpoint.json

The JSON report contains actual per-language unique verified verbs, noun lemmas, verb lemma/sense paradigms, and attested inflections with the input SHA-256. Missing inputs return **0**, not a fabricated denominator or estimated coverage.

## Bounded GitHub workflow

germanic_romance_qa.yml uses an immutable checkout SHA, read-only permissions, bounded jobs with max-parallel: 3, synthetic unit tests and a source-gated shard plan. It publishes results in GitHub Actions run summaries and can save a deterministic job-local JSON checkpoint in RUNNER_TEMP. Runner temp files are NOT cross-run durable storage; no paid external storage, releases, caches or artifacts are configured. Absent approved source shards yield no producer jobs and no packs. It is possible to resume externally only after a separately authorized durable checkpoint store exists.
