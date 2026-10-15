#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed pairs contract 1.0.0.

Requires jsonschema>=4.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit('Install the open-source jsonschema>=4 package to validate this contract') from exc

SCHEMA_PATH = Path(__file__).with_name('directed_pair.schema.json')


class DirectedPairContractError(ValueError):
    pass


def validate(document):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    seen_ids = set()
    for translation in document.get('translations', []):
        tid = translation['translation_id']
        if tid in seen_ids:
            raise DirectedPairContractError(f'duplicate translation ID: {tid}')
        seen_ids.add(tid)

        # Verify directed nature
        if translation['source_language'] == translation['target_language']:
            raise DirectedPairContractError(f'source and target language cannot be the same: {tid}')

    return document

def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)

    before = {row['translation_id']: row for row in previous.get('translations', [])}
    after = {row['translation_id']: row for row in updated.get('translations', [])}
    for rid, old in before.items():
        if rid not in after:
            raise DirectedPairContractError(f'breaking removal of {rid}')
        new = after[rid]
        pinned = ('source_language', 'target_language', 'source_sense_id', 'target_sense_id')
        if any(old[key] != new[key] for key in pinned):
            raise DirectedPairContractError(f'stable identity reassignment: {rid}')
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
    print('VALID: directed pairs contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
