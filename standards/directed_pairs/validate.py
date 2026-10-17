#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed pair contract 1.0.0.

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

    index = {}
    for collection, key in (('senses', 'sense_id'), ('pairs', 'pair_id')):
        entries = {}
        for record in document.get(collection, []):
            rid = record[key]
            if rid in entries or rid in index:
                raise DirectedPairContractError(f'duplicate stable ID: {rid}')
            entries[rid] = record
            index[rid] = collection
        index[collection] = entries

    senses = index.get('senses', {})
    pairs = index.get('pairs', {})

    for pair in pairs.values():
        a, b = pair['from_sense_id'], pair['to_sense_id']
        if a not in senses or b not in senses:
            raise DirectedPairContractError(f'orphan directed pair: {pair["pair_id"]}')
        if a == b:
            raise DirectedPairContractError(f'self-referential pair: {pair["pair_id"]}')

        lang_a = senses[a]['language']
        lang_b = senses[b]['language']

        if lang_a == lang_b:
            raise DirectedPairContractError(f'directed pair languages must differ: {pair["pair_id"]}')

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairContractError('document_id changed')

    for collection, id_key in (('senses', 'sense_id'), ('pairs', 'pair_id')):
        before = {row[id_key]: row for row in previous.get(collection, [])}
        after = {row[id_key]: row for row in updated.get(collection, [])}
        for rid, old in before.items():
            if rid not in after:
                raise DirectedPairContractError(f'breaking removal of {rid}')
            new = after[rid]

            if collection == 'senses':
                pinned = ('sense_id', 'language')
            else: # pairs
                pinned = ('pair_id', 'from_sense_id', 'to_sense_id')

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
    print('VALID: directed pair contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
