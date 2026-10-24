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

SCHEMA_PATH = Path(__file__).with_name('schema.json')


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

    translations = document.get('translations', [])
    translation_ids = set()

    for translation in translations:
        tid = translation['translation_id']
        if tid in translation_ids:
            raise DirectedPairContractError(f'duplicate stable ID: {tid}')
        translation_ids.add(tid)

        # Source and target must be distinct
        if translation['source_language'] == translation['target_language']:
            raise DirectedPairContractError(f'target language mismatch with source language: {tid}')

        source = translation['source']
        if publication and (not source['publication_approved'] or source['fixture_only'] or
                            not source.get('artifact_sha256')):
            raise DirectedPairContractError(f'publication requires approved non-fixture source hash: {tid}')

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairContractError('document_id changed')

    before = {row['translation_id']: row for row in previous['translations']}
    after = {row['translation_id']: row for row in updated['translations']}
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
    parser.add_argument('--publication', action='store_true')
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.file.read_text(encoding='utf-8'))
        validate(document, publication=args.publication)
    except (OSError, ValueError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    print('VALID: directed pair contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
