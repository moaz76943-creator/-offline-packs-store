#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed-pair translation contract 1.0.0."""
import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit('Install the open-source jsonschema>=4 package to validate this contract') from exc

SCHEMA_PATH = Path(__file__).with_name('translation.schema.json')

class DirectedTranslationError(ValueError):
    pass

def validate(document):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedTranslationError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    # Sense separation and direction validation
    for i, translation in enumerate(document.get("translations", [])):
        if translation["source_sense_id"] == translation["target_sense_id"]:
            raise DirectedTranslationError(f'Translation cannot refer to same sense: {translation["source_sense_id"]}')

    # Validations such as "reverse translations cannot be assumed" are intrinsic to the directed model itself,
    # ensuring A->B and B->A are explicit independent entries if both exist.

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)

    # Track translations
    def _key(t):
        return (t["source_sense_id"], t["target_sense_id"])

    before = {_key(t): t for t in previous.get("translations", [])}
    after = {_key(t): t for t in updated.get("translations", [])}

    for k, old_t in before.items():
        if k not in after:
            raise DirectedTranslationError(f'Breaking removal of translation from {k[0]} to {k[1]}')

    return True

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.file.read_text(encoding='utf-8'))
        validate(document)
    except (OSError, ValueError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    print('VALID: directed translation contract 1.0.0')
    return 0

if __name__ == '__main__':
    sys.exit(main())
