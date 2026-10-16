import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "directed_pair.schema.json"

class DirectedPairValidationError(Exception):
    pass

def validate(document):
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: e.path)
    if errors:
        raise DirectedPairValidationError(f"Schema validation failed: {errors[0].message}")

    pairs = document.get("pairs", [])
    seen_ids = set()
    for pair in pairs:
        pair_id = pair["pair_id"]
        if pair_id in seen_ids:
            raise DirectedPairValidationError(f"Duplicate pair_id: {pair_id}")
        seen_ids.add(pair_id)

        source_lang = pair["source_language"]
        target_lang = pair["target_language"]
        if source_lang == target_lang:
            raise DirectedPairValidationError(f"Source and target languages must differ in pair {pair_id}")

        # Validate that language prefixes match the sense IDs
        source_sense = pair["source_sense_id"]
        target_sense = pair["target_sense_id"]

        if not source_sense.startswith(f"{source_lang}-"):
            raise DirectedPairValidationError(f"Source sense ID {source_sense} must match language {source_lang}")
        if not target_sense.startswith(f"{target_lang}-"):
            raise DirectedPairValidationError(f"Target sense ID {target_sense} must match language {target_lang}")

    return True

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate.py <file.json>")
        sys.exit(1)

    try:
        with open(sys.argv[1]) as f:
            document = json.load(f)
        validate(document)
        print("Valid!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def verify_compatible(previous, updated):
    validate(previous)
    validate(updated)

    # ensure same schema
    if previous.get("schema_version") != updated.get("schema_version"):
        raise DirectedPairValidationError("Schema version changed")

    before = {pair["pair_id"]: pair for pair in previous.get("pairs", [])}
    after = {pair["pair_id"]: pair for pair in updated.get("pairs", [])}

    for pair_id, old in before.items():
        if pair_id not in after:
            raise DirectedPairValidationError(f"Breaking removal of {pair_id}")

        new = after[pair_id]

        # Stable identity reassignment check
        pinned = ("source_language", "target_language", "source_sense_id")
        for key in pinned:
            if old[key] != new[key]:
                raise DirectedPairValidationError(f"Stable identity reassignment for {pair_id}: {key} changed")

    return True
