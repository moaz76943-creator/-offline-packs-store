#!/usr/bin/env python3
"""Refresh concept anchors from Wikidata. Writes only catalog/organization/concept_graph.v1.json.

The graph is language-neutral item ids. It does not read packs or the license ledger
and it does not invent labels: a missing English label is stored as null.
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from tools.language_production.catalog import BLOCKLIST_PATH, ROOT, SECTIONS_PATH, load_json

TARGET = 240
PAGE = 50
API = 'https://www.wikidata.org/w/api.php'
USER_AGENT = 'offline-packs-store/1.0 (language-production)'
OUTPUT = ROOT / 'catalog' / 'organization' / 'concept_graph.v1.json'


def _get(params):
    url = API + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    delay = 5
    last_error = None
    for _ in range(8):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                time.sleep(0.4)
                return json.load(response)
        except Exception as exc:
            last_error = exc
            # The query service and the action API both answer 429 with a cool-down.
            time.sleep(delay)
            delay = min(delay * 2, 90)
    raise RuntimeError(f'wikidata request failed: {last_error}')


def _search(class_qid, property_id, offset):
    data = _get({
        'action': 'query',
        'list': 'search',
        'format': 'json',
        'srsearch': f'haswbstatement:{property_id}={class_qid}',
        'srlimit': str(PAGE),
        'sroffset': str(offset),
        'srnamespace': '0',
    })
    hits = data.get('query', {}).get('search') or []
    qids = []
    for hit in hits:
        title = hit.get('title') if isinstance(hit, dict) else ''
        if isinstance(title, str) and title.startswith('Q') and title[1:].isdigit() and not title.startswith('Q0'):
            qids.append(title)
    return qids


def _details(qids):
    if not qids:
        return {}
    data = _get({
        'action': 'wbgetentities',
        'ids': '|'.join(qids),
        'props': 'labels|claims',
        'languages': 'en',
        'format': 'json',
    })
    return data.get('entities') or {}


def _parents(entity):
    found = set()
    claims = entity.get('claims') if isinstance(entity, dict) else None
    if not isinstance(claims, dict):
        return found
    for property_id in ('P31', 'P279'):
        for statement in claims.get(property_id) or []:
            if not isinstance(statement, dict):
                continue
            snak = statement.get('mainsnak') or {}
            value = (snak.get('datavalue') or {}).get('value') if isinstance(snak.get('datavalue'), dict) else None
            qid = value.get('id') if isinstance(value, dict) else None
            if isinstance(qid, str):
                found.add(qid)
    return found


def _label(entity):
    labels = entity.get('labels') if isinstance(entity, dict) else None
    if not isinstance(labels, dict):
        return None
    english = labels.get('en')
    if not isinstance(english, dict):
        return None
    value = english.get('value')
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def concepts_for_class(class_qid, blocked, seen):
    """Real instance and subclass items for one section class, capped at TARGET."""
    found = []
    for property_id in ('P31', 'P279'):
        if len(found) >= TARGET:
            break
        offset = 0
        while len(found) < TARGET and offset < 2000:
            page = _search(class_qid, property_id, offset)
            if not page:
                break
            fresh = [qid for qid in page if qid not in seen and qid not in blocked]
            for start in range(0, len(fresh), 20):
                batch = fresh[start:start + 20]
                entities = _details(batch)
                for qid in batch:
                    entity = entities.get(qid)
                    if not isinstance(entity, dict) or entity.get('missing'):
                        continue
                    if _parents(entity) & blocked:
                        continue
                    seen.add(qid)
                    found.append({
                        'id': f'concept.{qid.lower()}',
                        'wikidata': qid,
                        'anchor_label': _label(entity),
                    })
                    if len(found) >= TARGET:
                        break
                if len(found) >= TARGET:
                    break
            if len(page) < PAGE:
                break
            offset += PAGE
    return found


def _write(graph):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build_graph():
    sections = load_json(SECTIONS_PATH)['sections']
    blocked = set(load_json(BLOCKLIST_PATH).get('blocked_concepts') or [])
    if OUTPUT.is_file():
        graph = json.loads(OUTPUT.read_text(encoding='utf-8'))
        built = list(graph.get('sections') or [])
    else:
        built = []
    done = {section.get('id') for section in built}
    seen = set(blocked)
    for section in built:
        for subsection in section.get('subsections') or []:
            for concept in subsection.get('concepts') or []:
                qid = concept.get('wikidata')
                if isinstance(qid, str):
                    seen.add(qid)
    for section in sections:
        if section['id'] in done:
            count = sum(len(item.get('concepts') or []) for item in section.get('subsections') or [])
            # The on-disk section is the checkpoint, not the class list.
            saved = next(item for item in built if item.get('id') == section['id'])
            count = sum(len(item.get('concepts') or []) for item in saved.get('subsections') or [])
            print(f"{section['id']}: {count} (kept)", flush=True)
            continue
        subsections = []
        for class_qid in section['classes']:
            concepts = concepts_for_class(class_qid, blocked, seen)
            subsections.append({
                'id': f"{section['id']}.{class_qid.lower()}",
                'label': section['label'],
                'class': class_qid,
                'concepts': concepts,
            })
        built.append({
            'id': section['id'],
            'label': section['label'],
            'classes': list(section['classes']),
            'subsections': subsections,
        })
        count = sum(len(item['concepts']) for item in subsections)
        print(f"{section['id']}: {count}", flush=True)
        _write({
            'schema_version': '1.0.0',
            'independent_of': ['packs', 'legal/ledger', 'manifest'],
            'note': (
                'Language-neutral concept ids anchored to Wikidata items that are instances or '
                'subclasses of the section class. Labels come from the English Wikidata label and '
                'are null when Wikidata has none. No pack, license, or invented word is required. '
                'Content-policy items are omitted. A section is written as soon as it is fetched.'
            ),
            'target_concepts_per_section': TARGET,
            'sections': built,
        })
    return {
        'schema_version': '1.0.0',
        'independent_of': ['packs', 'legal/ledger', 'manifest'],
        'note': (
            'Language-neutral concept ids anchored to Wikidata items that are instances or '
            'subclasses of the section class. Labels come from the English Wikidata label and '
            'are null when Wikidata has none. No pack, license, or invented word is required. '
            'Content-policy items are omitted.'
        ),
        'target_concepts_per_section': TARGET,
        'sections': built,
    }


def main():
    graph = build_graph()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {OUTPUT}')


if __name__ == '__main__':
    main()
