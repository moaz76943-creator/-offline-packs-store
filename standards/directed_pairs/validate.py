#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed pairs contract 1.0.0.

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
_SCHEMA_CACHE = None


class DirectedPairContractError(ValueError):
    pass


def validate(document, *, publication=False, sense_languages=None, approved_sources=None):
    """Validate a single direction. Publication requires independent sense and rights indexes.

    Indexes must be built by the trusted caller from admitted canonical sources;
    lexical sense IDs must not be parsed as if they encoded language identity.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

    schema = _SCHEMA_CACHE
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    # Registry identities, not arbitrary well-formed BCP-47-like identifiers.
    registry_path = Path(__file__).resolve().parents[2] / 'catalog' / 'language_registry.v1.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    ids = {lang['id'] for lang in registry['languages']}
    pair = (document['source_language'], document['target_language'])
    if pair[0] == pair[1] or any(code not in ids for code in pair):
        raise DirectedPairContractError(f'unknown or identical canonical directed-pair languages: {pair}')
    if publication and (not isinstance(sense_languages, dict) or not isinstance(approved_sources, dict)):
        raise DirectedPairContractError('publication requires independently verified sense and source indexes')

    entries = {}

    for record in document['translations']:
        rid = record['translation_id']
        if (record['from_language'], record['to_language']) != pair:
            raise DirectedPairContractError(f'record direction does not match document pair: {rid}')
        if sense_languages is not None:
            if (sense_languages.get(record['from_sense_id']),
                    sense_languages.get(record['to_sense_id'])) != pair:
                raise DirectedPairContractError(f'unknown or mismatched sense-language ownership: {rid}')
        if record['from_sense_id'] == record['to_sense_id']:
            raise DirectedPairContractError(f'translation cannot be to the same sense id: {rid}')
        if rid in entries:
            raise DirectedPairContractError(f'duplicate stable ID: {rid}')
        entries[rid] = record
        source = record['source']
        if publication and approved_sources.get(source['source_id']) != source['license_id']:
            raise DirectedPairContractError(f'no independent source rights admission: {rid}')
        if publication and (not source['publication_approved'] or source['fixture_only'] or
                            not source.get('artifact_sha256')):
            raise DirectedPairContractError(f'publication requires approved non-fixture source hash: {rid}')

        for example in record.get('examples', []):
            if publication:
                src = example.get('source')
                if (not src or not src['publication_approved'] or src['fixture_only'] or
                        not src.get('artifact_sha256') or
                        approved_sources.get(src['source_id']) != src['license_id']):
                    raise DirectedPairContractError(f'unapproved example translation: {rid}')

    return document

def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if (previous['source_language'], previous['target_language']) != (updated['source_language'], updated['target_language']):
        raise DirectedPairContractError('directed pair reassignment')
    if previous['document_id'] != updated['document_id']:
        raise DirectedPairContractError('document_id changed')

    before = {row['translation_id']: row for row in previous['translations']}
    after = {row['translation_id']: row for row in updated['translations']}

    for rid, old in before.items():
        if rid not in after:
            raise DirectedPairContractError(f'breaking removal of {rid}')
        new = after[rid]
        pinned = ('from_sense_id', 'to_sense_id', 'from_language', 'to_language')
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
