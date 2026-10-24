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
