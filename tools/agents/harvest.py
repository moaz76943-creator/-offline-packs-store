"""Bounded source adapters. A failed source is skipped; it does not invent a row."""

import json
import urllib.parse
import urllib.request

from tools.agents.common import BLOCKED_CONCEPTS, SCHEMA_VERSION, is_placeholder, script_matches
from tools.open_sources.assess import positive_match

USER_AGENT = 'offline-packs-store/1.0 (language-production)'
TATOEBA_CODES = {
    'en': 'eng', 'de': 'deu', 'fr': 'fra', 'es': 'spa', 'ar': 'ara', 'tr': 'tur',
    'ru': 'rus', 'zh': 'cmn', 'ja': 'jpn', 'nl': 'nld', 'sv': 'swe',
}


class SourceSkip(Exception):
    pass


def fetch_bytes(url, timeout=30, max_bytes=200000):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(max_bytes + 1)[:max_bytes]


def fetch_json(url, timeout=30):
    return json.loads(fetch_bytes(url, timeout=timeout, max_bytes=2_000_000).decode('utf-8'))


def _sense_qids(sense):
    found = []
    for claim in (sense.get('claims') or {}).get('P5137') or []:
        value = ((claim.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {}
        qid = value.get('id')
        if isinstance(qid, str):
            found.append(qid)
    return found


def rows_from_lexeme(entity, concept, language_by_qid, profiles, retrieved):
    """Keep one row per lemma whose language QID is in the production catalog."""
    if not isinstance(entity, dict) or entity.get('type') != 'lexeme':
        return [], 'skip'
    senses = entity.get('senses') or []
    qids = []
    sense_id = ''
    for sense in senses:
        found = _sense_qids(sense)
        qids.extend(found)
        if concept.get('wikidata') in found and not sense_id:
            sense_id = sense.get('id') or ''
    if concept.get('wikidata') not in qids:
        return [], 'unplaced'
    if any(qid in BLOCKED_CONCEPTS for qid in qids):
        return [], 'exclude'
    language_qid = entity.get('language')
    language = language_by_qid.get(language_qid)
    if not language:
        return [], 'other_language'
    lemmas = entity.get('lemmas') or {}
    lemma = ''
    if isinstance(lemmas, dict):
        for item in lemmas.values():
            if isinstance(item, dict) and isinstance(item.get('value'), str):
                lemma = item['value']
                break
    if is_placeholder(lemma):
        return [], 'placeholder'
    profile = profiles.get(language) or {}
    if not script_matches(lemma, profile.get('script')):
        return [], 'quarantine'
    forms = []
    for form in (entity.get('forms') or [])[:8]:
        reps = form.get('representations') or {}
        if isinstance(reps, dict):
            for item in reps.values():
                if isinstance(item, dict) and item.get('value'):
                    forms.append(item['value'])
    pos = 'verb' if entity.get('lexicalCategory') == 'Q24905' else ''
    return [{
        'schema_version': SCHEMA_VERSION,
        'language': language,
        'section': concept.get('section'),
        'subsection': concept.get('subsection'),
        'concept_id': concept.get('concept_id'),
        'wikidata': concept.get('wikidata'),
        'qids': qids,
        'lemma': lemma,
        'forms': forms,
        'pos': pos,
        'source_id': 'wikidata.lexemes',
        'record_id': entity.get('id') or '',
        'sense_id': sense_id,
        'revision': str(entity.get('lastrevid') or ''),
        'license_id': 'CC0-1.0',
        'retrieval_date': retrieved,
        'origin_url': f"https://www.wikidata.org/wiki/Lexeme:{entity.get('id')}",
        'status': 'keep',
    }], 'keep'


def search_lexemes(qid, fetch=fetch_json, limit=8):
    query = urllib.parse.urlencode({
        'action': 'query',
        'list': 'search',
        'srsearch': f'haswbstatement:P5137={qid}',
        'srnamespace': '146',
        'srlimit': str(limit),
        'format': 'json',
    })
    payload = fetch('https://www.wikidata.org/w/api.php?' + query)
    hits = ((payload.get('query') or {}).get('search') or [])
    ids = []
    for hit in hits:
        title = hit.get('title') or ''
        if title.startswith('Lexeme:'):
            ids.append(title.split(':', 1)[1])
    return ids


def load_lexemes(ids, fetch=fetch_json):
    if not ids:
        return {}
    query = urllib.parse.urlencode({
        'action': 'wbgetentities',
        'ids': '|'.join(ids[:20]),
        'format': 'json',
        'formatversion': '2',
    })
    payload = fetch('https://www.wikidata.org/w/api.php?' + query)
    return payload.get('entities') or {}


def tatoeba_sample(code, limit=12):
    """Stream the start of one detailed export. Rows without an author are dropped."""
    import bz2
    url = (
        'https://downloads.tatoeba.org/exports/per_language/'
        f'{code}/{code}_sentences_detailed.tsv.bz2'
    )
    raw = fetch_bytes(url, timeout=40, max_bytes=1_500_000)
    try:
        text = bz2.decompress(raw).decode('utf-8', 'replace')
    except OSError:
        text = bz2.BZ2Decompressor().decompress(raw).decode('utf-8', 'replace')
    rows = []
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) < 4 or not parts[0].isdigit() or not parts[2].strip() or not parts[3].strip():
            continue
        sentence = parts[2].strip()
        if is_placeholder(sentence):
            continue
        slot = 'sentence.question' if '?' in sentence else 'sentence.statement'
        rows.append({
            'text': sentence,
            'author': parts[3].strip(),
            'record_id': 'tatoeba:' + parts[0],
            'sentence_slot': slot,
        })
        if len(rows) >= limit:
            break
    return rows


def ud_sample(limit=12):
    raw = fetch_bytes(
        'https://raw.githubusercontent.com/UniversalDependencies/UD_English-EWT/master/en_ewt-ud-dev.conllu',
        timeout=30,
        max_bytes=80000,
    )
    text = raw.decode('utf-8', 'replace')
    rows = []
    sent_id = ''
    tokens = []
    for line in text.splitlines():
        if line.startswith('# sent_id = '):
            sent_id = line.split('=', 1)[1].strip()
            tokens = []
        elif line.startswith('# text = '):
            sentence = line.split('=', 1)[1].strip()
            if sent_id and sentence and not is_placeholder(sentence) and script_matches(sentence, 'Latn'):
                rows.append({
                    'text': sentence,
                    'record_id': 'ud:en_ewt:' + sent_id,
                    'sentence_slot': 'sentence.question' if '?' in sentence else 'sentence.statement',
                })
            if len(rows) >= limit:
                break
        elif line and not line.startswith('#'):
            tokens.append(line)
    return rows


def accept_notice(notice, declared, co_offered=()):
    ok, reasons = positive_match(notice or '', declared, co_offered)
    if not ok:
        raise SourceSkip(','.join(reasons) or 'license_rejected')
    return True
