#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed translation pairs contract 1.0.0.

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


def validate(document, *, publication=False):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    index = {}
    for collection, key in (('senses', 'sense_id'), ('directed_translations', 'pair_id')):
        entries = {}
        for record in document[collection]:
            rid = record[key]
            if rid in entries or rid in index:
                raise DirectedPairContractError(f'duplicate stable ID: {rid}')
            entries[rid] = record
            index[rid] = collection
            source = record['source']
            if publication and (not source['publication_approved'] or source['fixture_only'] or
                                not source.get('artifact_sha256')):
                raise DirectedPairContractError(f'publication requires approved non-fixture source hash: {rid}')
        index[collection] = entries

    senses = index['senses']

    # Track directed pairs to prevent reversing assumption without explicit attribution
    pair_directions = set()

    for translation in index['directed_translations'].values():
        src_id = translation['source_sense_id']
        tgt_id = translation['target_sense_id']

        if src_id not in senses:
            raise DirectedPairContractError(f'orphan source sense: {src_id}')
        if tgt_id not in senses:
            raise DirectedPairContractError(f'orphan target sense: {tgt_id}')

        src_lang = translation['source_language']
        tgt_lang = translation['target_language']

        if src_lang == tgt_lang:
            raise DirectedPairContractError(f'source and target languages must be different: {translation["pair_id"]}')

        pair_key = (src_id, tgt_id)
        if pair_key in pair_directions:
             raise DirectedPairContractError(f'duplicate translation pair direction: {translation["pair_id"]}')
        pair_directions.add(pair_key)

    return document

def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairContractError('document_id changed')
    for collection, id_key in (('senses', 'sense_id'), ('directed_translations', 'pair_id')):
        before = {row[id_key]: row for row in previous[collection]}
        after = {row[id_key]: row for row in updated[collection]}
        for rid, old in before.items():
            if rid not in after:
                raise DirectedPairContractError(f'breaking removal of {rid}')
            new = after[rid]
            pinned = ('lexeme_id', 'concept_id') if collection == 'senses' else ('source_sense_id', 'target_sense_id', 'source_language', 'target_language')
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
    print('VALID: directed translation pair contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
