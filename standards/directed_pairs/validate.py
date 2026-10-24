#!/usr/bin/env python3
"""Executable validator for directional multilingual lexical translations.
"""

import json
from pathlib import Path
import sys

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMA_PATH = Path(__file__).parent / "directed_pairs.schema.json"


class DirectedPairContractError(Exception):
    pass


def load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema not found: {SCHEMA_PATH}")
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate(doc: dict):
    """Validates the directed pair document against schema and semantic invariants."""
    if jsonschema:
        schema = load_schema()
        try:
            jsonschema.validate(instance=doc, schema=schema)
        except jsonschema.ValidationError as e:
            raise DirectedPairContractError(f"Schema violation: {e.message}") from e

    # Structural invariants
    if "source_language" in doc and "target_language" in doc:
        if doc["source_language"] == doc["target_language"]:
            raise DirectedPairContractError("Source language and target language must be different.")

    for i, pair in enumerate(doc.get("pairs", [])):
        if "source_sense_id" not in pair or "target_sense_id" not in pair:
            raise DirectedPairContractError(f"Pair {i} missing sense identity.")

        if pair["source_sense_id"] == pair["target_sense_id"]:
            raise DirectedPairContractError(f"Pair {i}: source_sense_id and target_sense_id cannot be identical.")

        # Ensure no reverse translations are assumed
        if pair.get("source_lexeme_id") == pair.get("target_lexeme_id") and pair.get("source_sense_id") == pair.get("target_sense_id"):
             raise DirectedPairContractError(f"Pair {i}: Exact self-translation is meaningless.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate directional pair JSON.")
    parser.add_argument("file", help="JSON file to validate")
    args = parser.parse_args()

    if not jsonschema:
         print("Warning: jsonschema is not installed. Schema validation will be skipped.", file=sys.stderr)

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        validate(data)
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
