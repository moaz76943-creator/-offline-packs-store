#!/usr/bin/env python3
"""Open Directed-Pair Translation Data Standard Validator.

Requires jsonschema>=4.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit('Install jsonschema>=4 to validate this contract') from exc

SCHEMA_PATH = Path(__file__).with_name('schema.json')


class DirectedPairsContractError(ValueError):
    pass


def validate(document, *, publication=False):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairsContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    pairs = document.get('pairs', [])
    index = {}
    for pair in pairs:
        pid = pair['pair_id']
        if pid in index:
            raise DirectedPairsContractError(f'duplicate pair ID: {pid}')
        index[pid] = pair

        # Ensure direction explicitly does not imply reverse
        if pair['source_language'] == pair['target_language']:
            raise DirectedPairsContractError(f'source and target language must differ: {pid}')

        source = pair['source']
        if publication and (not source['publication_approved'] or source['fixture_only'] or
                            not source.get('artifact_sha256')):
            raise DirectedPairsContractError(f'publication requires approved non-fixture source hash: {pid}')

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairsContractError('document_id changed')

    before = {row['pair_id']: row for row in previous.get('pairs', [])}
    after = {row['pair_id']: row for row in updated.get('pairs', [])}

    for pid, old in before.items():
        if pid not in after:
            raise DirectedPairsContractError(f'breaking removal of {pid}')
        new = after[pid]
        pinned = ('source_language', 'target_language', 'source_sense_id', 'target_sense_id')
        if any(old[key] != new[key] for key in pinned):
            raise DirectedPairsContractError(f'stable identity reassignment: {pid}')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--publication', action='store_true')
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.file.read_text(encoding='utf-8'))
        validate(document, publication=args.publication)
    except (OSError, ValueError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    print('VALID: directed pairs contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
