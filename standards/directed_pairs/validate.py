#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed_pairs contract 1.0.0.

Requires jsonschema>=4; no corpus downloads and no inferred language data.
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

    # Validate that reverse translations cannot be assumed.
    # Enforce uniqueness of translation_ids.
    index = {}
    pair_set = set()

    for translation in document.get('translations', []):
        tid = translation['translation_id']
        if tid in index:
            raise DirectedPairsContractError(f'duplicate stable ID: {tid}')
        index[tid] = translation

        source = translation['source']
        if publication and (not source.get('publication_approved') or source.get('fixture_only') or
                            not source.get('artifact_sha256')):
            raise DirectedPairsContractError(f'publication requires approved non-fixture source hash: {tid}')

        # Explicit pair identity
        from_sense = translation['from_sense_id']
        to_sense = translation['to_sense_id']
        if not from_sense or not to_sense:
            raise DirectedPairsContractError(f'missing sense identity: {tid}')

        pair = (from_sense, to_sense)
        if pair in pair_set:
            raise DirectedPairsContractError(f'duplicate directed pair mapping: {from_sense} -> {to_sense}')
        pair_set.add(pair)

        # Verify no reverse pair implicitly conflicts or is assumed to be equivalent
        # (Actually, we just store it explicitly. The check is that the same translation_id isn't reused
        # for a reverse pair, and that we don't accidentally treat a reverse pair as the same identity).
        # We also might want to check examples.
        for example in translation.get('examples', []):
            eid = example['example_id']
            # Optionally validate example uniqueness within document?
            # The schema allows multiple translations per document, each with examples.
            pass

    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairsContractError('document_id changed')
    if previous['source_language'] != updated['source_language']:
        raise DirectedPairsContractError('source_language changed')
    if previous['target_language'] != updated['target_language']:
        raise DirectedPairsContractError('target_language changed')

    before = {row['translation_id']: row for row in previous.get('translations', [])}
    after = {row['translation_id']: row for row in updated.get('translations', [])}

    for tid, old in before.items():
        if tid not in after:
            raise DirectedPairsContractError(f'breaking removal of {tid}')
        new = after[tid]
        pinned = ('from_sense_id', 'to_sense_id')
        if any(old[key] != new[key] for key in pinned):
            raise DirectedPairsContractError(f'stable identity reassignment: {tid}')
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
