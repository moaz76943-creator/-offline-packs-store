#!/usr/bin/env python3
"""Fail-closed JSON Schema and cross-record checks for directed pairs standard.

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

class DirectedPairError(ValueError):
    pass

def validate(document):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    senses = {}
    for sense in document.get('senses', []):
        sid = sense['sense_id']
        if sid in senses:
            raise DirectedPairError(f'duplicate sense ID: {sid}')
        senses[sid] = sense

    translations = set()
    for translation in document.get('directed_translations', []):
        tid = translation['translation_id']
        if tid in translations:
            raise DirectedPairError(f'duplicate translation ID: {tid}')
        translations.add(tid)

        src_id = translation['source_sense_id']
        tgt_id = translation['target_sense_id']

        if src_id not in senses:
            raise DirectedPairError(f'orphan source sense ID: {src_id}')
        if tgt_id not in senses:
            raise DirectedPairError(f'orphan target sense ID: {tgt_id}')

        if senses[src_id]['language'] != translation['source_language']:
            raise DirectedPairError(f'source language mismatch for translation {tid}')
        if senses[tgt_id]['language'] != translation['target_language']:
            raise DirectedPairError(f'target language mismatch for translation {tid}')

    return document

def verify_compatible(previous, updated):
    """Reject silent ID reassignment or removal in a patch of the same contract."""
    validate(previous)
    validate(updated)

    if previous['document_id'] != updated['document_id']:
        raise DirectedPairError('document_id changed')

    prev_senses = {s['sense_id']: s for s in previous.get('senses', [])}
    curr_senses = {s['sense_id']: s for s in updated.get('senses', [])}

    for sid, old in prev_senses.items():
        if sid not in curr_senses:
            raise DirectedPairError(f'breaking removal of sense {sid}')
        new = curr_senses[sid]
        if old['language'] != new['language']:
            raise DirectedPairError(f'stable identity reassignment for sense: {sid}')

    prev_trans = {t['translation_id']: t for t in previous.get('directed_translations', [])}
    curr_trans = {t['translation_id']: t for t in updated.get('directed_translations', [])}

    for tid, old in prev_trans.items():
        if tid not in curr_trans:
            raise DirectedPairError(f'breaking removal of translation {tid}')
        new = curr_trans[tid]
        pinned = ('source_sense_id', 'target_sense_id', 'source_language', 'target_language')
        if any(old[key] != new[key] for key in pinned):
            raise DirectedPairError(f'stable identity reassignment for translation: {tid}')

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
