"""Bounded source adapters. A failed source is skipped; it does not invent a row."""

import json
import time
import urllib.error
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


class SourceAPIError(ValueError):
    """A failed or malformed upstream response, never evidence of an empty source."""


def _wikidata_payload(payload):
    if not isinstance(payload, dict):
        raise SourceAPIError('malformed Wikidata response')
    if 'error' in payload:
        error = payload['error']
        code = error.get('code', 'unknown') if isinstance(error, dict) else 'unknown'
        raise SourceAPIError(f'Wikidata API error: {code}')
    return payload


def fetch_bytes(url, timeout=30, max_bytes=200000):
    """Pace Wikidata and retry transient throttling without masking failures.

    Preserve bounded-prefix sampling for Tatoeba and UD. Persistent errors
    still fail the agent and keep the search cursor for a later attempt.
    """
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    wikidata = urllib.parse.urlsplit(url).hostname == 'www.wikidata.org'
    for attempt in range(3):
        if wikidata and attempt == 0:
            time.sleep(0.4)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(max_bytes + 1)[:max_bytes]
        except urllib.error.HTTPError as exc:
            if not wikidata or exc.code not in (429, 502, 503, 504) or attempt == 2:
                raise
            retry_after = exc.headers.get('Retry-After') if exc.headers else None
            if retry_after is not None:
                if not retry_after.isascii() or not retry_after.isdecimal():
                    raise
                delay = int(retry_after)
                if delay > 8:
                    raise
            else:
                delay = 1 << attempt
            time.sleep(max(1, delay))


def fetch_json(url, timeout=30):
    # A truncated API document is not evidence of an empty lexicon.
    raw = fetch_bytes(url, timeout=timeout, max_bytes=2_000_001)
    if len(raw) > 2_000_000:
        raise SourceAPIError('oversized Wikidata API response')
    return json.loads(raw.decode('utf-8'))


def _sense_qids(sense):
    """Use only the best non-deprecated P5137 item statements.

    Wikibase preferred rank supersedes normal rank. A preferred no-value
    statement must not cause fallback to an older normal item. Malformed
    statements are not evidence for mapping a lexeme to a concept.
    """
    if not isinstance(sense, dict):
        return []
    claims = sense.get('claims')
    statements = claims.get('P5137') if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return []
    preferred = any(isinstance(c, dict) and c.get('rank') == 'preferred'
                    for c in statements)
    selected_rank = 'preferred' if preferred else 'normal'
    found = []
    for claim in statements:
        if not isinstance(claim, dict) or claim.get('rank', 'normal') != selected_rank:
            continue
        snak = claim.get('mainsnak')
        if not isinstance(snak, dict) or snak.get('snaktype', 'value') != 'value':
            continue
        data = snak.get('datavalue')
        value = data.get('value') if isinstance(data, dict) else None
        qid = value.get('id') if isinstance(value, dict) else None
        if (isinstance(qid, str) and qid.startswith('Q')
                and qid[1:].isascii() and qid[1:].isdigit()
                and not qid[1:].startswith('0') and qid not in found):
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


def search_lexeme_page(qid, fetch=fetch_json, limit=8, offset=0):
    """Fetch one bounded page and return the upstream continuation, or zero at EOF."""
    if type(offset) is not int or not 0 <= offset <= 10000:
        raise SourceAPIError('invalid Wikidata search offset')
    query = urllib.parse.urlencode({
        'action': 'query',
        'list': 'search',
        'srsearch': f'haswbstatement:P5137={qid}',
        'srnamespace': '146',
        'srlimit': str(limit),
        'sroffset': str(offset),
        # Relevance changes when an existing lexeme is edited. Creation order
        # keeps new lexemes at the tail across bounded scheduled pages.
        'srsort': 'create_timestamp_asc',
        'format': 'json',
    })
    payload = _wikidata_payload(fetch('https://www.wikidata.org/w/api.php?' + query))
    result = payload.get('query')
    if not isinstance(result, dict) or not isinstance(result.get('search'), list):
        raise SourceAPIError('missing Wikidata search results')
    hits = result['search']
    ids = []
    for hit in hits:
        title = hit.get('title') if isinstance(hit, dict) else None
        if (not isinstance(title, str) or not title.startswith('Lexeme:L')
                or not title[8:].isascii() or not title[8:].isdigit()):
            raise SourceAPIError('malformed Wikidata lexeme search hit')
        ids.append(title.split(':', 1)[1])
    continuation = payload.get('continue', {})
    if (not isinstance(continuation, dict)
            or ('continue' in payload and 'sroffset' not in continuation)):
        raise SourceAPIError('malformed Wikidata search continuation')
    next_offset = continuation.get('sroffset', 0)
    if (type(next_offset) is not int or not 0 <= next_offset <= 10000
            or ('continue' in payload and next_offset <= offset)):
        raise SourceAPIError('nonadvancing Wikidata search continuation')
    return ids, next_offset


def search_lexemes(qid, fetch=fetch_json, limit=8):
    """Compatibility adapter for callers requesting only the first bounded page."""
    return search_lexeme_page(qid, fetch=fetch, limit=limit)[0]


def load_lexemes(ids, fetch=fetch_json):
    if not ids:
        return {}
    query = urllib.parse.urlencode({
        'action': 'wbgetentities',
        'ids': '|'.join(ids[:20]),
        'format': 'json',
        'formatversion': '2',
    })
    payload = _wikidata_payload(fetch('https://www.wikidata.org/w/api.php?' + query))
    entities = payload.get('entities')
    if not isinstance(entities, dict) or not entities:
        raise SourceAPIError('missing Wikidata entities')
    if any(not isinstance(entity, dict) for entity in entities.values()):
        raise SourceAPIError('malformed Wikidata entity')
    return entities


def tatoeba_sample(code, limit=12):
    """Stream the start of one detailed export. Rows without an author are dropped."""
    import bz2
    url = (
        'https://downloads.tatoeba.org/exports/per_language/'
        f'{code}/{code}_sentences_detailed.tsv.bz2'
    )
    raw = fetch_bytes(url, timeout=40, max_bytes=1_500_000)
    # The download is intentionally capped: its BZip2 end marker may be
    # outside the prefix. Incremental decompression accepts those prefixes
    # without treating a normal bounded sample as corrupt.
    decoder = bz2.BZ2Decompressor()
    text = decoder.decompress(raw, max_length=2_000_000).decode('utf-8', 'replace')
    # A non-final prefix can end mid-row; never publish that truncated row.
    if not decoder.eof and not text.endswith('\n'):
        text = text.rsplit('\n', 1)[0] if '\n' in text else ''
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
