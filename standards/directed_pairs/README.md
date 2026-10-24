# Open Directed-Pair Translation Data Standard

Contract `1.0.0` for directional multilingual lexical translations.

## Model and Identity

- A `pair_id` identifies a specific directional translation from one sense to another.
- `source_language` and `target_language` are defined explicitly and must be different.
- Directions are strict: A->B does not imply B->A.
- Includes `target_text`, `equivalence`, `context`, `domain`, `examples`, and `confidence`.
- Reuses the canonical source schema for provenance.
- Strict validation that rejects malformed directions and missing identities.

## Commands

```sh
python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v
python3 -m compileall -q standards/directed_pairs
git diff --check
```
