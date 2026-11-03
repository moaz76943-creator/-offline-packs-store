#!/usr/bin/env python3
"""Offline evidence replay using existing factory converters; never source admission."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))

from tools.language_production.catalog import load_languages, load_sections, load_blocklist
from tools.language_production.harvest import attach_registry, classify_entity
from tools.language_production.build_overlay import to_document
from standards.lexical.sqlite_v2 import build
from tools.pack_conformance.validator import PackConformanceValidator


def checked(relative, expected):
    path = ROOT / relative
    if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
        raise ValueError('unsafe evidence path')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('evidence SHA256 mismatch: ' + relative)
    return raw


def replay(output):
    receipt = json.loads((HERE/'review-receipt.json').read_text())
    proposals = json.loads(checked(str((HERE/'proposed-sources.json').relative_to(ROOT)),
                                   receipt['proposed_sources_sha256']))['sources']
    sources = {s['source_id']:s for s in proposals}
    index = json.loads(checked(receipt['class_index']['path'], receipt['class_index']['sha256']))
    for capture in receipt['class_captures']:
        checked(capture['artifact_path'], capture['sha256'])
    notice = receipt['retrievals']['license']
    checked(notice['artifact_path'], notice['sha256'])
    languages = load_languages()['languages']
    blocked, lemmas = load_blocklist()
    output = Path(output)
    if output.exists():
        raise ValueError('replay output must be a new directory')
    output.mkdir(parents=True)
    results = []
    for snapshot, expected in zip(receipt['retrievals']['entities'], receipt['results']):
        entity = json.loads(checked(snapshot['artifact_path'],snapshot['sha256']))['entities'][snapshot['entity_id']]
        if entity['lastrevid'] != snapshot['revision']:
            raise ValueError('revision mismatch')
        source = sources[expected['source_id']]
        checked(source['license']['evidence_path'],source['license']['evidence_sha256'])
        language = attach_registry(next(x for x in languages if x['wikidata']==entity['language']))
        lang = language['id']
        decision, payload = classify_entity(entity,language,load_sections(),index,blocked,lemmas,
                                            source['dataset_version'],source['origin_url'])
        if decision != 'keep':
            raise ValueError('source no longer passes existing policy: ' + decision)
        for row in [payload['lexeme'],*payload['senses']]:
            row['source'].update(source_id=source['source_id'],artifact_sha256=source['retrieval']['sha256'],
                                 retrieval_id=source['retrieval']['identity'],dataset_version=source['dataset_version'],
                                 origin_url=source['origin_url'],publication_approved=False)
        # Estimated CEFR is not source evidence. Retain attested data only.
        for sense in payload['senses']:
            sense.pop('levels',None)
        originals = [f for f in entity.get('forms',[]) if (f.get('representations',{}).get(lang)or{}).get('value')]
        forms = payload['lexeme']['morphology']['conjugations']
        if len(originals) != len(forms):
            raise ValueError('form count mismatch')
        for form, upstream in zip(forms, originals):
            if form['surface'] != upstream['representations'][lang]['value'].strip():
                raise ValueError('form surface mismatch')
            form['source'] = {**payload['lexeme']['source'],'record_locator':upstream['id']}
        document = to_document(lang,[payload],source['dataset_version'],source['origin_url'])
        raw = (json.dumps(document,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        if hashlib.sha256(raw).hexdigest() != expected['document_sha256']:
            raise ValueError('document replay mismatch')
        (output/(lang+'.json')).write_bytes(raw)
        path = output/(lang+'.sqlite')
        build(document,path,publication=False)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sqlite_sha256']:
            raise ValueError('SQLite replay mismatch (check Python/SQLite build identity)')
        validator = PackConformanceValidator(path)
        if validator.validate() or validator.publication_approved:
            raise ValueError('review-only evidence unexpectedly treated as source approval')
        results.append({'language':lang,'verbs':len(document['lexemes']),'senses':len(document['senses']),
                        'attested_forms':len(forms),'sha256':expected['sqlite_sha256']})
    return {'status':'OFFLINE_REPLAY_PASS','results':results,'production_publication':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.out),ensure_ascii=False,sort_keys=True))
