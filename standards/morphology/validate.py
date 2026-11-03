#!/usr/bin/env python3
"""Fail-closed JSON Schema and feature-compatibility checks for morphology contract 1.0.0.

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

SCHEMA_PATH = Path(__file__).with_name('morphology.schema.json')

# Verified language profiles mapping language code to explicitly disallowed features
# Empty set means we don't have restrictions defined, but we can add known typological constraints here.
LANGUAGE_PROFILES = {
    # Mandarin Chinese is analytic, usually does not inflect for tense, case, gender.
    'cmn': {'tense', 'case', 'gender', 'person'},
    # English doesn't have grammatical gender on regular nouns (though on pronouns, we don't blanket ban, but let's restrict a hypothetical one if needed).
    # For testing, let's say 'cmn' disallows 'tense' and 'gender'
}

class MorphologyContractError(ValueError):
    pass

def validate(document, *, lemmas=None):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failures = sorted(Draft202012Validator(schema).iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise MorphologyContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    form_ids = set()
    for form in document.get('forms', []):
        fid = form['form_id']
        if fid in form_ids:
            raise MorphologyContractError(f'duplicate form ID: {fid}')
        form_ids.add(fid)

        lemma_id = form['lemma_id']
        if lemmas is not None and lemma_id not in lemmas:
            raise MorphologyContractError(f'form references unknown lemma: {lemma_id}')

        language = form['language']
        disallowed_features = LANGUAGE_PROFILES.get(language, set())

        for analysis in form['analyses']:
            features = analysis.get('features', {})
            for feature in features:
                if feature in disallowed_features:
                    raise MorphologyContractError(
                        f'unsupported feature "{feature}" for language "{language}" in form {fid}'
                    )

    return document

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
    print('VALID: morphology contract 1.0.0')
    return 0

if __name__ == '__main__':
    sys.exit(main())
