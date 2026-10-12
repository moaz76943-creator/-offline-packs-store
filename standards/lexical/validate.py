#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for lexical contract 1.0.0.

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

SCHEMA_PATH = Path(__file__).with_name('lexical.schema.json')


class LexicalContractError(ValueError):
    pass


def validate(document, *, publication=False):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise LexicalContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    index = {}
    for collection, key in (('lexemes', 'lexeme_id'), ('senses', 'sense_id'),
                            ('translations', 'translation_id'), ('examples', 'example_id'),
                            ('relations', 'relation_id')):
        entries = {}
        for record in document[collection]:
            rid = record[key]
            if rid in entries or rid in index:
                raise LexicalContractError(f'duplicate stable ID: {rid}')
            entries[rid] = record
            index[rid] = collection
            source = record['source']
            if publication and (not source['publication_approved'] or source['fixture_only'] or
                                not source.get('artifact_sha256')):
                raise LexicalContractError(f'publication requires approved non-fixture source hash: {rid}')
        index[collection] = entries

    lexemes, senses = index['lexemes'], index['senses']
    for lexeme in lexemes.values():
        for form_group in ('articles', 'classifiers', 'inflections', 'conjugations', 'irregular_forms'):
            for form in lexeme.get('morphology', {}).get(form_group, []):
                if publication:
                    src = form.get('source', lexeme['source'])
                    if not src['publication_approved'] or src['fixture_only'] or not src.get('artifact_sha256'):
                        raise LexicalContractError(f'unapproved morphological form: {lexeme["lexeme_id"]}')
        for phonetic in lexeme.get('pronunciations', []):
            if publication and ('source' not in phonetic or not phonetic['source']['publication_approved']):
                raise LexicalContractError(f'unapproved pronunciation: {lexeme["lexeme_id"]}')
    for sense in senses.values():
        if sense['lexeme_id'] not in lexemes:
            raise LexicalContractError(f'orphan sense: {sense["sense_id"]}')
    for translation in index['translations'].values():
        a, b = translation['from_sense_id'], translation['to_sense_id']
        if a not in senses or b not in senses:
            raise LexicalContractError(f'orphan directed translation: {translation["translation_id"]}')
        target = lexemes[senses[b]['lexeme_id']]
        if translation['language'] != target['language']:
            raise LexicalContractError(f'target language mismatch: {translation["translation_id"]}')
    for example in index['examples'].values():
        sid = example['sense_id']
        if sid not in senses:
            raise LexicalContractError(f'orphan example: {example["example_id"]}')
        source_lexeme = lexemes[senses[sid]['lexeme_id']]
        if example['language'] != source_lexeme['language']:
            raise LexicalContractError(f'example language mismatch: {example["example_id"]}')
        if publication:
            for translated in example.get('translations', []):
                src = translated['source']
                if not src['publication_approved'] or src['fixture_only'] or not src.get('artifact_sha256'):
                    raise LexicalContractError(f'unapproved example translation: {example["example_id"]}')
    for relation in index['relations'].values():
        if relation['from_lexeme_id'] not in lexemes or relation['to_lexeme_id'] not in lexemes:
            raise LexicalContractError(f'orphan lexical relation: {relation["relation_id"]}')
    return document


def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)
    if previous['document_id'] != updated['document_id']:
        raise LexicalContractError('document_id changed')
    for collection, id_key in (('lexemes', 'lexeme_id'), ('senses', 'sense_id')):
        before = {row[id_key]: row for row in previous[collection]}
        after = {row[id_key]: row for row in updated[collection]}
        for rid, old in before.items():
            if rid not in after:
                raise LexicalContractError(f'breaking removal of {rid}')
            new = after[rid]
            pinned = ('language', 'script', 'lemma', 'pos') if collection == 'lexemes' else ('lexeme_id', 'concept_id')
            if any(old[key] != new[key] for key in pinned):
                raise LexicalContractError(f'stable identity reassignment: {rid}')
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
    print('VALID: lexical contract 1.0.0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
