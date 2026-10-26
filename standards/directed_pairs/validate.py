#!/usr/bin/env python3
"""Fail-closed validator for directional multilingual lexical translations.

Enforces schema compliance, independent sense IDs, directionality, and prevents
duplicate IDs.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
    import referencing
except ImportError as exc:
    raise SystemExit('Install jsonschema>=4.18.0 to validate this contract') from exc

SCHEMA_PATH = Path(__file__).with_name('directed_pairs.schema.json')

class DirectedPairContractError(ValueError):
    pass

def validate(document):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))

    # Initialize validator using referencing
    registry = referencing.Registry().with_resource(
        schema["$id"],
        referencing.Resource.from_contents(schema)
    )
    validator = Draft202012Validator(schema, registry=registry)

    failures = sorted(validator.iter_errors(document),
                      key=lambda error: tuple(str(piece) for piece in error.absolute_path))
    if failures:
        error = failures[0]
        raise DirectedPairContractError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

    translation_ids = set()
    sense_ids = {}

    for pair in document.get('pairs', []):
        tid = pair['translation_id']
        if tid in translation_ids:
            raise DirectedPairContractError(f'Duplicate translation_id: {tid}')
        translation_ids.add(tid)

        from_sense = pair['from_sense']
        to_sense = pair['to_sense']

        if from_sense['language'] == to_sense['language']:
            raise DirectedPairContractError(f'Invalid direction: from_language == to_language ({from_sense["language"]}) for {tid}')

        # Sense ID isolation checks (one ID per sense text/lang combination)
        for sense in (from_sense, to_sense):
            sid = sense['sense_id']
            sense_signature = (sense['language'], sense['text'], sense.get('context'), sense.get('domain'))
            if sid in sense_ids:
                if sense_ids[sid] != sense_signature:
                    raise DirectedPairContractError(f'Sense identity mismatch for sense_id: {sid}')
            else:
                sense_ids[sid] = sense_signature

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
    print('VALID: directed pairs contract 1.0.0')
    return 0

if __name__ == '__main__':
    sys.exit(main())
