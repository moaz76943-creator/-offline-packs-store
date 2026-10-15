# Open Directed-Pair Translation Data Standard

This directory contains a versioned, executable data standard for directional multilingual lexical translations.
It preserves sense identity, contextual meanings, and source provenance.

## Purpose

The directed pair translation standard explicitly models translations from a source language to a target language.
Unlike bidirectional mappings, this standard acknowledges that translation A -> B does not necessarily imply B -> A.

## Features

- **Directionality:** Explicit source and target languages.
- **Sense Identity:** Models translations between independent lexical sense IDs rather than mere word surfaces.
- **Context & Domain:** Supports contextual descriptions and specific domains.
- **Provenance:** Includes detailed source attribution, version, and confidence evidence.
- **Equivalence Types:** Distinguishes between literal, contextual, and approximate translations.
- **Validation:** Provides a JSON Schema and a robust Python validator (`validate.py`) leveraging the `jsonschema` library.

## Usage

```bash
python3 -m validate <path_to_translation_json>
```

## Testing

```bash
python3 -m unittest discover -s standards/directed_pairs -p 'test_*.py' -v
```
