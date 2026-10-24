import json
import sys
from pathlib import Path
import jsonschema

SCHEMA_PATH = Path(__file__).with_name('directed_pair.schema.json')

class DirectedPairError(ValueError):
    pass

def validate(document):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    failures = sorted(validator.iter_errors(document), key=lambda e: e.path)
    if failures:
        error = failures[0]
        path = list(error.path)
        raise DirectedPairError(f'JSON Schema violation at {path}: {error.message}')

    senses = {}
    for sense in document['senses']:
        sid = sense['sense_id']
        if sid in senses:
            raise DirectedPairError(f'Duplicate sense ID: {sid}')
        senses[sid] = sense

    pairs = set()
    for pair in document['directed_pairs']:
        pid = pair['pair_id']
        if pid in pairs:
            raise DirectedPairError(f'Duplicate pair ID: {pid}')
        pairs.add(pid)

        src_id = pair['source_sense_id']
        tgt_id = pair['target_sense_id']
        if src_id not in senses:
            raise DirectedPairError(f'Missing source sense ID: {src_id}')
        if tgt_id not in senses:
            raise DirectedPairError(f'Missing target sense ID: {tgt_id}')

        tgt_sense = senses[tgt_id]
        if tgt_sense['language'] != pair['target_language']:
            raise DirectedPairError(f'Target language mismatch in pair: {pid}')

        if src_id == tgt_id:
             raise DirectedPairError(f'Self translation not allowed: {pid}')

    return document

def verify_compatible(old_doc, new_doc):
    validate(old_doc)
    validate(new_doc)
    if old_doc['document_id'] != new_doc['document_id']:
         raise DirectedPairError("Document ID changed")

    old_senses = {s['sense_id']: s for s in old_doc['senses']}
    new_senses = {s['sense_id']: s for s in new_doc['senses']}

    for sid, old_s in old_senses.items():
        if sid not in new_senses:
            raise DirectedPairError(f"Breaking change: Removed sense {sid}")
        new_s = new_senses[sid]
        if old_s['language'] != new_s['language']:
            raise DirectedPairError(f"Breaking change: Changed language for sense {sid}")

    old_pairs = {p['pair_id']: p for p in old_doc['directed_pairs']}
    new_pairs = {p['pair_id']: p for p in new_doc['directed_pairs']}

    for pid, old_p in old_pairs.items():
        if pid not in new_pairs:
            raise DirectedPairError(f"Breaking change: Removed pair {pid}")
        new_p = new_pairs[pid]
        if old_p['source_sense_id'] != new_p['source_sense_id'] or old_p['target_sense_id'] != new_p['target_sense_id']:
            raise DirectedPairError(f"Breaking change: Changed sense IDs for pair {pid}")
        if old_p['target_language'] != new_p['target_language']:
            raise DirectedPairError(f"Breaking change: Changed target language for pair {pid}")

    return True
