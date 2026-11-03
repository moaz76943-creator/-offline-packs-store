# Multilingual Directed Pair Translation Contract

Contract `1.0.0`; SQLite mapping `2.0.0` (`PRAGMA user_version=2`).

This standard models directional multilingual lexical translations. It strictly separates translation mappings into independent $A \rightarrow B$ directions.

## Key Principles

-   **Directionality**: A translation $A \rightarrow B$ does not automatically imply a valid and contextually appropriate $B \rightarrow A$ translation. The schema specifically prevents automatic backward extrapolation.
-   **Sense Mapping**: Translations pair two explicit `sense_id` records, not raw lexemes or word surfaces. This preserves contextual meanings and polysemous variations.
-   **Identity & Provenance**: Both senses and their connecting translation pair must provide robust and independent provenance records. Source information tracks attribution, domain confidence, and dataset retrieval locations.
-   **Equivalence Model**: Translations denote whether the equivalence is `exact`, `approximate`, or `contextual`, maintaining semantic boundaries between literal and functional translations.

## Structure & Usage

This project directory implements schema validation via `jsonschema` (Draft 2020-12) and provides an additive deterministic SQLite v2 export path.

### Core Files
-   `directed_pair.schema.json`: JSON schema constraint contract.
-   `validate.py`: Validation tool verifying provenance hashing, directional integrity, and stable IDs.
-   `sqlite_v2.py`: Generates the non-lossy SQLite DDL layout, deterministically sorted.

### Examples

```bash
python3 standards/directed_pairs/validate.py standards/directed_pairs/fixtures/positive.json
python3 standards/directed_pairs/sqlite_v2.py standards/directed_pairs/fixtures/positive.json /tmp/directed-pairs-fixture.sqlite
python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v
```

The fixtures are illustrative synthetic test subsets and do not pass real-world publication validation requirements.

### Existing factory interoperability (candidate-only)

The public standard is a versioned JSON document, while the existing
`tools/factory_extensions/directed_translation_scale/graph.py` candidate
reader accepts bounded JSONL rows using `translation_id`, `from_sense_id`
and `to_sense_id`. Passing the standards JSON document directly to that
reader is **not supported**. Convert explicitly, without modifying the factory:

```bash
python3 standards/directed_pairs/factory_adapter.py \
  standards/directed_pairs/fixtures/positive.json /tmp/fixture-candidates.jsonl
python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v
```

The adapter preserves explicit A→B and B→A rows separately and rejects
invalid language identities, oversized records, unknown attestation IDs and
unverified publication claims. It does not synthesize direct-sense evidence,
canonical language ownership, license approval or reverse pairs. Optional
`--canonical-languages` and `--attestations` inputs must come from
independent approved sources. The factory still independently verifies
canonical senses, Route-05 rights, attestation integrity and editorial review.
Synthetic fixture output is **never** an admitted production translation.


### Lexeme-language integrity

Every sense references a lexeme owner record carrying a language and source. A directed pair's source and target labels must match those owners; language is never inferred from the spelling of a stable ID. This in-document check prevents accidental direction swaps but is not independent evidence of canonical ownership. Production validation must supply `canonical_lexeme_languages` from an independently admitted lexical registry, or it fails closed. The existing factory adapter uses a different input shape and requires a separate owner-coordinated compatibility fix; a valid standards fixture is **not** automatically an admitted production candidate.
