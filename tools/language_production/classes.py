"""Parse Wikidata entity claims into a P31/P279 index. Network fetch is optional and capped."""

import json
import urllib.parse
import urllib.request

P31 = 'P31'
P279 = 'P279'
MAX_IDS = 40
BATCH = 20


def claims_to_index(entities):
    """Build {qid: {p31: [...], p279: [...]}} from a wbgetentities entities object."""
    index = {}
    if not isinstance(entities, dict):
        return index
    for qid, entity in entities.items():
        if not isinstance(entity, dict) or entity.get('missing'):
            continue
        claims = entity.get('claims') if isinstance(entity.get('claims'), dict) else {}
        index[qid] = {'p31': _qids(claims.get(P31)), 'p279': _qids(claims.get(P279))}
    return index


def _qids(statements):
    found = []
    if not isinstance(statements, list):
        return found
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        snak = statement.get('mainsnak')
        if not isinstance(snak, dict) or snak.get('snaktype') != 'value':
            continue
        value = snak.get('datavalue')
        if not isinstance(value, dict):
            continue
        inner = value.get('value')
        qid = inner.get('id') if isinstance(inner, dict) else None
        if isinstance(qid, str) and qid.startswith('Q'):
            found.append(qid)
    return found


def fetch_class_index(qids, *, max_ids=MAX_IDS, depth=3, opener=None):
    """Fetch P31/P279 for sense items and a bounded ancestor walk. Failures return a partial index."""
    opener = opener or urllib.request.urlopen
    queue = [qid for qid in qids if isinstance(qid, str) and qid.startswith('Q')]
    index = {}
    seen = set()
    remaining_depth = {qid: depth for qid in queue}
    while queue and len(index) < max_ids:
        batch = []
        while queue and len(batch) < BATCH and len(index) + len(batch) < max_ids:
            qid = queue.pop(0)
            if qid in seen:
                continue
            seen.add(qid)
            batch.append(qid)
        if not batch:
            break
        try:
            payload = _fetch(batch, opener)
        except (OSError, ValueError, json.JSONDecodeError):
            break
        parsed = claims_to_index(payload)
        index.update(parsed)
        for qid in batch:
            hops_left = remaining_depth.get(qid, 0)
            if hops_left <= 0:
                continue
            info = parsed.get(qid) or {}
            for parent in (info.get('p31') or []) + (info.get('p279') or []):
                if parent not in seen and parent not in remaining_depth:
                    remaining_depth[parent] = hops_left - 1
                    queue.append(parent)
    return index


def _fetch(batch, opener):
    query = urllib.parse.urlencode({
        'action': 'wbgetentities',
        'ids': '|'.join(batch),
        'props': 'claims',
        'format': 'json',
    })
    request = urllib.request.Request(
        'https://www.wikidata.org/w/api.php?' + query,
        headers={'User-Agent': 'offline-packs-store/1.0 (language-production)'},
    )
    with opener(request, timeout=20) as response:
        data = json.load(response)
    entities = data.get('entities') if isinstance(data, dict) else None
    if not isinstance(entities, dict):
        raise ValueError('wikidata class response has no entities')
    return entities
