#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed-pair contract 1.0.0.

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

SCHEMA_PATH = Path(__file__).with_name('directed_pairs.schema.json')


class DirectedPairContractError(ValueError):
    pass


def validate(document, *, publication=False):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    seen_pairs = {}
    pair_ids = set()

    for pair in document['pairs']:
        pid = pair['pair_id']
        if pid in pair_ids:
            raise DirectedPairContractError(f'duplicate stable ID: {pid}')
        pair_ids.add(pid)

        source_id = pair['source_sense_id']
        target_id = pair['target_sense_id']

        if source_id == target_id:
            raise DirectedPairContractError(f'source and target sense IDs must not be identical: {pid}')

        direction_key = (source_id, target_id)
        if direction_key in seen_pairs:
            raise DirectedPairContractError(f'duplicate directed translation: {pid}')
        seen_pairs[direction_key] = pid

        source = pair['source']
        if publication and (not source['publication_approved'] or source['fixture_only'] or
                            not source.get('artifact_sha256')):
            raise DirectedPairContractError(f'publication requires approved non-fixture source hash: {pid}')

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairContractError('document_id changed')

    before = {row['pair_id']: row for row in previous['pairs']}
    after = {row['pair_id']: row for row in updated['pairs']}

    for rid, old in before.items():
        if rid not in after:
            raise DirectedPairContractError(f'breaking removal of {rid}')
        new = after[rid]
        pinned = ('source_sense_id', 'target_sense_id', 'source_language', 'target_language')
        if any(old[key] != new[key] for key in pinned):
            raise DirectedPairContractError(f'stable identity reassignment: {rid}')

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
    print('VALID: directed-pair contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
