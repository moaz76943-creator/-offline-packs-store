#!/usr/bin/env python3
"""Explicit, fail-closed projection from the public pair standard to factory JSONL.

The canonical standards document remains authoritative. This adapter does not
approve rights, create evidence, or infer reverse translations. Factory admission
still independently checks canonical senses, Route-05 rights and attestations.
"""
import argparse
import json
from pathlib import Path

from validate import DirectedPairContractError, validate

MAX_FACTORY_LINE_BYTES = 65536
MAX_FACTORY_CANDIDATES = 100000


def _reject_duplicate_keys(pairs):
    """Reject ambiguous JSON before identity and provenance validation."""
    record = {}
    for key, value in pairs:
        if key in record:
            raise DirectedPairContractError(f'duplicate JSON key: {key}')
        record[key] = value
    return record


def _load_unambiguous_json(raw):
    return json.loads(raw, object_pairs_hook=_reject_duplicate_keys)


def to_factory_jsonl(document, *, canonical_lexeme_languages=None,
                     attestation_by_pair=None, publication=False):
    """Return bounded UTF-8 JSONL understood by graph.each_candidate().

    Attestations, if supplied, must be independent records keyed by pair_id.
    Neither this projection nor a fixture grants admission or editorial approval.
    """
    validate(document, publication=publication,
             canonical_lexeme_languages=canonical_lexeme_languages)
    pairs = document['directed_translations']
    if len(pairs) > MAX_FACTORY_CANDIDATES:
        raise DirectedPairContractError('factory candidate budget exceeded')
    attestations = {} if attestation_by_pair is None else attestation_by_pair
    if not isinstance(attestations, dict):
        raise DirectedPairContractError('attestations must be a pair-ID mapping')
    ids = {pair['pair_id'] for pair in pairs}
    if set(attestations) - ids:
        raise DirectedPairContractError('attestation refers to unknown pair')
    lines = []
    for pair in sorted(pairs, key=lambda item: item['pair_id']):
        record = {
            'translation_id': pair['pair_id'],
            'from_sense_id': pair['source_sense_id'],
            'to_sense_id': pair['target_sense_id'],
            'source_language': pair['source_language'],
            'target_language': pair['target_language'],
            'translation_text': pair['text'],
            'equivalence': pair['equivalence'],
            'source': pair['source'],
        }
        if pair.get('context') is not None:
            record['context'] = pair['context']
        if pair['pair_id'] in attestations:
            attestation = attestations[pair['pair_id']]
            if not isinstance(attestation, dict):
                raise DirectedPairContractError('attestation must be an object')
            record['evidence'] = attestation
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')
        if len(encoded) + 1 > MAX_FACTORY_LINE_BYTES:
            raise DirectedPairContractError('factory candidate line budget exceeded')
        lines.append(encoded + b'\n')
    return b''.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--canonical-languages', type=Path)
    parser.add_argument('--attestations', type=Path)
    parser.add_argument('--publication', action='store_true')
    args = parser.parse_args(argv)
    try:
        data = _load_unambiguous_json(args.input.read_text(encoding='utf-8'))
        owners = (_load_unambiguous_json(args.canonical_languages.read_text(encoding='utf-8'))
                  if args.canonical_languages else None)
        attestations = (_load_unambiguous_json(args.attestations.read_text(encoding='utf-8'))
                        if args.attestations else None)
        output = to_factory_jsonl(data, canonical_lexeme_languages=owners,
                                  attestation_by_pair=attestations,
                                  publication=args.publication)
        with args.output.open('xb') as stream:
            stream.write(output)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'INVALID: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
