# Semitic attestation extension v1 (AR / AM)

Independent additive contract. No edits to **PR #85** (`standards/morphology/validator.py`, `form.schema.json`, `feature_overrides.json` or its tests). Nested `record` uses exactly the **existing v1 form schema fields**; the sidecar `evidence` adds immutable source locators and separately attested linguistic claims. No production language packs are modified by this extension.

## Language isolation

- `ar` is an explicitly registered **Semitic / Arab** profile: recorded root/template pairs, Arabic noun gender, singular/dual/plural, attested broken plurals, and separately verified verb stems and verbal TAM/person/agreement are retained without generating new forms. The variety must be `classical`, `msa`, or `dialect`. For dialect, the language-scoped tag is required.
- `am` is a separately registered **Semitic / Ethi** profile: independent attested roots/templates, noun and verbal features, standard versus regional distinctions; **no Arabic normalization, Arabic plural paradigms or Arabic-script fallback**. An attested verb stem must use Ethiopic script.
- `mt` is Semitic but has **no verified profile/admitted forms here**. It is intentionally unsupported until registered source evidence and a reviewed Maltese-specific contract exist. Persian, Urdu, Pashto, Sindhi and Uyghur use Arabic-derived scripts but are not Semitic; Somali and Hausa are not Semitic. No language is enabled on writing system or family alone.

An unattested form/root/gender/translation stays **unknown**, including potentially plausible-looking inflections. For Arabic, retrieval strips relevant harakat/tatweel and conservatively folds selected Alef and Alif Maqsura characters **only in the retrieval key**. Original records are never rewritten. Colliding unvowelled spellings return `ambiguous` unless an exact vowelled surface disambiguates, in which case the collision flag remains visible. For Amharic, lookup uses Unicode NFC without Arabic transformations.

## Input contract and provenance

The approved, SHA-256-pinned Route 05 `legal/ledger/sources.json` **morphology** entry is the only admissible source; its `retrieval.artifact_path` must resolve inside the public repo to a line-delimited UTF-8 shard. No dynamic network downloads. The file's true SHA and its license snapshot must match their reviewed ledger hashes. The source must have `APPROVED_FOR_REDISTRIBUTION`, explicit reviewer+decision, source-specific rights evidence and exact version. This additional read-only gate does **not** replace or weaken final Route 05 release approval.

Each source line is strict JSON `{ "record": {...}, "evidence": {...} }`; `record` follows the existing canonical v1 fields. Required evidence keys: `source_locator`, `dataset_version`, `variety`, `part_of_speech`, `attested: true`, and `claim_locators`. Every attested claim requires its own locator: `form`, `features.number`, `features.mood`, `root`, `pattern`, `processes.broken_plural`, `verb_stem`, etc. For verbs, `verb_stem` is mandatory; `dialect_tag` is mandatory for dialect/regional varieties. The input **must not include `source_sha256`**, because embedding a file's own hash would be circular. The worker adds the independently computed, ledger-verified hash to the accepted evidence envelope before writing the candidate output.

Only observed facts are copied; no root extraction or inflection generation. Original lemma/form, vocalized spelling, gender tags and all claim evidence are preserved. The existing `MorphologyEngine` currently has an `ar` capability override but `am` is still `unknown` in `standards/morphology/feature_overrides.json`; this additive sidecar **does not pretend the generic runtime consumes Amharic results**. Any upstream integration requires a separate coordinated contract change outside this PR.

## Safe invocation

Run local synthetic QA (no dependencies or downloaded corpora):

```sh
python3 -m unittest discover -s tests/linguistic_extensions/semitic -p 'test_*.py' -v
python3 -m tools.linguistic_extensions.semitic.worker coverage --repo-root .
```

On an explicitly approved morphology source shard only:

```sh
python3 -m tools.linguistic_extensions.semitic.worker shard \
  --repo-root . --language ar --source-id APPROVED_ID \
  --out-dir /tmp/semitic-part1 --max-records 5000 --run-id RUN_ID
python3 -m tools.linguistic_extensions.semitic.worker shard \
  --repo-root . --language ar --source-id APPROVED_ID \
  --out-dir /tmp/semitic-part2 --resume-dir /tmp/semitic-part1 \
  --max-records 5000 --run-id NEXT_RUN_ID --resume-run-id RUN_ID
```

The workflow `.github/workflows/semitic_morphology_qa.yml` is **manual-only** (`workflow_dispatch`). QA mode reads registry and pilot files but never publishes anything. Shard mode runs only on public `main` with the exact pinned approved source, checks source SHA and previous run segment before resuming, emits `accepted.jsonl` and `checkpoint.json` in short-retained artifact `semitic-verified-segment`. Each segment contains *only new* rows; `total_accepted`, `next_line`, `segment_count` and `complete` are exact worker-reported counters. Each checkpoint captures the actual `GITHUB_RUN_ID`. A resume must download the previous run's artifact before its 3-day retention expires, and an incomplete segment can be resumed only after verifying exact source, version, language and artifact digests. A checkpoint is not a release certificate.

## Current coverage and blockers

As of reviewed `main` at implementation time, the production source ledger has **zero approved morphology entries**. Thus `accepted_production_forms = {"ar":0,"am":0}`; the existing `standards/morphology/attested_forms.jsonl` pilot contains **3 Arabic** attestation rows and **0 Amharic**, which are *not* production redistribution approvals. Do not label a simulated test run as a production proof. When approved input shards arrive, process up to 10,000 independently attested lines per bounded worker run, report counts per segment, and resume by checkpoint. The existing GHA-02 queue supports only `registry_validate` and `admission_partition_verify`: this extension does not modify or silently hijack it.
