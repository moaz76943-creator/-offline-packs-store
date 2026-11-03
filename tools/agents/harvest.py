"""Bounded source adapters. A failed source is skipped; it does not invent a row."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from tools.agents.common import (
    BLOCKED_CONCEPTS, SCHEMA_VERSION, is_placeholder, policy_qids, script_matches,
)
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


_TRANSIENT_HTTP = frozenset({429, 500, 502, 503, 504})


def fetch_bytes(url, timeout=30, max_bytes=200000, attempts=3, pause=None):
    """Read a bounded body. Retry only transient HTTP statuses, at most twice."""
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise SourceAPIError('invalid fetch attempt bound')
    if pause is None:
        pause = time.sleep
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(max_bytes + 1)[:max_bytes]
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in _TRANSIENT_HTTP or attempt + 1 == attempts:
                raise
            retry_after = None
            if urllib.parse.urlsplit(url).hostname == 'www.wikidata.org':
                retry_after = exc.headers.get('Retry-After') if exc.headers else None
            if retry_after is not None:
                if (not isinstance(retry_after, str) or not retry_after.isascii()
                        or not retry_after.isdecimal() or int(retry_after) > 8):
                    raise
                pause(max(1, int(retry_after)))
            else:
                pause(attempt + 1)
    raise last


def fetch_json(url, timeout=30):
    raw = fetch_bytes(url, timeout=timeout, max_bytes=2_000_001)
    if len(raw) > 2_000_000:
        raise SourceAPIError('oversized source API response')
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


TATOEBA_MAX_BYTES = 8_000_000
UD_TREEBANK_URL = (
    'https://raw.githubusercontent.com/UniversalDependencies/UD_English-EWT/master/en_ewt-ud-dev.conllu'
)
UD_MAX_BYTES = 2_000_000


def _tatoeba_rows(text):
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
    return rows


def tatoeba_window(code, limit=40, skip=0, max_bytes=1_500_000):
    """One bounded slice of a detailed export, continuing after ``skip`` rows.

    The BZip2 stream is only readable from the start, so a later page downloads
    a longer prefix instead of inventing sentences past the bytes we fetched.
    """
    import bz2
    if type(skip) is not int or skip < 0:
        skip = 0
    if type(limit) is not int or limit < 1:
        limit = 1
    if type(max_bytes) is not int or not 1 <= max_bytes <= TATOEBA_MAX_BYTES:
        max_bytes = 1_500_000
    url = (
        'https://downloads.tatoeba.org/exports/per_language/'
        f'{code}/{code}_sentences_detailed.tsv.bz2'
    )
    raw = fetch_bytes(url, timeout=40, max_bytes=max_bytes)
    # The download is intentionally capped: its BZip2 end marker may be
    # outside the prefix. Incremental decompression accepts those prefixes
    # without treating a normal bounded sample as corrupt.
    decoder = bz2.BZ2Decompressor()
    decode_cap = min(8_000_000, max(2_000_000, max_bytes * 3))
    text = decoder.decompress(raw, max_length=decode_cap).decode('utf-8', 'replace')
    # A non-final prefix can end mid-row; never publish that truncated row.
    if not decoder.eof and not text.endswith('\n'):
        text = text.rsplit('\n', 1)[0] if '\n' in text else ''
    collected = _tatoeba_rows(text)
    window = collected[skip:skip + limit]
    return {
        'rows': window,
        'next_skip': skip + len(window),
        'exhausted': skip + len(window) >= len(collected),
    }


def tatoeba_sample(code, limit=12, skip=0, max_bytes=1_500_000):
    """Stream one detailed export. Rows without an author are dropped."""
    return tatoeba_window(code, limit=limit, skip=skip, max_bytes=max_bytes)['rows']


def _ud_rows(text):
    rows = []
    sent_id = ''
    for line in text.splitlines():
        if line.startswith('# sent_id = '):
            sent_id = line.split('=', 1)[1].strip()
        elif line.startswith('# text = '):
            sentence = line.split('=', 1)[1].strip()
            if sent_id and sentence and not is_placeholder(sentence) and script_matches(sentence, 'Latn'):
                rows.append({
                    'text': sentence,
                    'record_id': 'ud:en_ewt:' + sent_id,
                    'sentence_slot': 'sentence.question' if '?' in sentence else 'sentence.statement',
                })
    return rows


def ud_window(limit=40, skip=0, max_bytes=400_000, url=UD_TREEBANK_URL):
    """Continue through the licensed English EWT sample. The notice is per treebank."""
    if type(skip) is not int or skip < 0:
        skip = 0
    if type(limit) is not int or limit < 1:
        limit = 1
    if type(max_bytes) is not int or not 1 <= max_bytes <= UD_MAX_BYTES:
        max_bytes = 400_000
    raw = fetch_bytes(url, timeout=30, max_bytes=max_bytes)
    text = raw.decode('utf-8', 'replace')
    if len(raw) >= max_bytes and not text.endswith('\n'):
        text = text.rsplit('\n', 1)[0] if '\n' in text else ''
    collected = _ud_rows(text)
    window = collected[skip:skip + limit]
    return {
        'rows': window,
        'next_skip': skip + len(window),
        'exhausted': skip + len(window) >= len(collected),
    }


def ud_sample(limit=12, skip=0, max_bytes=80000):
    return ud_window(limit=limit, skip=skip, max_bytes=max_bytes)['rows']


def accept_notice(notice, declared, co_offered=()):
    ok, reasons = positive_match(notice or '', declared, co_offered)
    if not ok:
        raise SourceSkip(','.join(reasons) or 'license_rejected')
    return True


KAIKKI_GERMAN_URL = (
    'https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl'
)
KAIKKI_SLICE_BYTES = 1_500_000
KAIKKI_MAX_ROWS = 200
# Eight range reads stay inside the scheduled job. One read rarely reaches a catalog anchor.
KAIKKI_WINDOW_SLICES = 8
# Bump when the anchor rule changes so a cursor from the old matcher is not trusted.
KAIKKI_EXTRACTOR = 'wikidata-link-v2'
# English Wiktionary extracts covered by the stored Wiktionary copyright notice.
KAIKKI_DICTIONARIES = (
    ('de', 'German'),
    ('en', 'English'),
    ('es', 'Spanish'),
    ('fr', 'French'),
    ('it', 'Italian'),
    ('nl', 'Dutch'),
    ('pt', 'Portuguese'),
    ('sv', 'Swedish'),
)
_QID = __import__('re').compile(r'^Q[1-9][0-9]*$')
_LINK_QID = __import__('re').compile(r'^([^#]+)#([^:#]+):_(Q[1-9][0-9]*)$')


def kaikki_dictionary_url(name):
    return (
        'https://kaikki.org/dictionary/'
        f'{name}/kaikki.org-dictionary-{name}.jsonl'
    )


def _normalize_label(text):
    if not isinstance(text, str):
        return ''
    return ' '.join(text.replace('_', ' ').casefold().split())


def sense_anchors(sense):
    """Explicit Wikidata ids, plus link titles that encode one.

    The English-Wiktionary Kaikki extracts often leave ``sense['wikidata']``
    empty and store the item on the linked page as ``Title#English:_Q123``.
    """
    explicit = []
    raw = sense.get('wikidata') if isinstance(sense, dict) else None
    if isinstance(raw, list):
        for qid in raw:
            if isinstance(qid, str) and _QID.fullmatch(qid) and qid not in explicit:
                explicit.append(qid)
    linked = {}
    for link in (sense.get('links') if isinstance(sense, dict) else None) or []:
        if not isinstance(link, list) or len(link) < 2 or not isinstance(link[1], str):
            continue
        match = _LINK_QID.fullmatch(link[1])
        if not match:
            continue
        qid = match.group(3)
        if _QID.fullmatch(qid):
            linked.setdefault(qid, match.group(1))
    return explicit, linked


def kaikki_resume(cursor, language):
    """Return ``(offset, migrating)``. An older extractor restarts at byte 0.

    The previous matcher skipped link-encoded anchors. Keeping its byte cursor
    would permanently skip the rows it already passed.
    """
    if not isinstance(cursor, dict) or cursor.get('extractor') != KAIKKI_EXTRACTOR:
        return 0, True
    languages = cursor.get('languages')
    if isinstance(languages, dict) and isinstance(languages.get(language), dict):
        offset = languages[language].get('byte_offset', 0)
    elif language == 'de':
        offset = cursor.get('byte_offset', 0)
    else:
        offset = 0
    if type(offset) is not int or offset < 0 or offset > 2_000_000_000:
        return 0, True
    return offset, False


def fetch_range(url, start, length, timeout=40):
    """Read one bounded HTTP range. A full-file download is never requested."""
    if type(start) is not int or not 0 <= start <= 2_000_000_000:
        raise SourceAPIError('invalid range offset')
    if type(length) is not int or not 1 <= length <= 2_000_000:
        raise SourceAPIError('invalid range length')
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': USER_AGENT,
            'Range': f'bytes={start}-{start + length - 1}',
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # urlopen raises 416 instead of returning a response. A persisted
        # offset past a replaced shorter extract must restart, not fail forever.
        if exc.code == 416:
            return 416, None, b''
        raise
    with response:
        status = response.getcode()
        header = response.headers.get('Content-Range')
        payload = response.read(length + 1)[:length]
    return status, header, payload


def kaikki_window(offset, url=KAIKKI_GERMAN_URL, size=KAIKKI_SLICE_BYTES, fetch=fetch_range):
    """Return complete JSONL bytes and the next line-aligned offset.

    The German extract is about a gigabyte. Re-reading its first 120KB never
    reaches later Wikidata anchors. A server that ignores Range is a source
    error, not an empty harvest of that same prefix.
    """
    if type(offset) is not int or offset < 0:
        raise SourceAPIError('invalid kaikki offset')
    status, header, payload = fetch(url, offset, size)
    if status == 416 or payload == b'':
        return b'', 0, True
    if offset and (status != 206 or not isinstance(header, str)
                   or not header.startswith(f'bytes {offset}-')):
        raise SourceAPIError('kaikki range was not honored')
    if status not in (200, 206):
        raise SourceAPIError(f'unexpected kaikki status {status}')
    newline = payload.rfind(b'\n')
    if newline < 0:
        # The whole window sits inside one line. Skip the fragment.
        return b'', offset + len(payload), False
    complete = payload[:newline + 1]
    next_offset = offset + len(complete)
    total = None
    if isinstance(header, str) and '/' in header:
        raw_total = header.rsplit('/', 1)[-1]
        if raw_total.isdigit():
            total = int(raw_total)
    if total is not None and next_offset >= total:
        return complete, 0, True
    return complete, next_offset, False


def rows_from_kaikki_record(obj, concepts_by_qid, profiles, retrieved, url=KAIKKI_GERMAN_URL,
                            expected_language='de'):
    """Keep senses that carry a catalog Wikidata anchor and a real sense id.

    A missing Wiktionary revision is not a reason to drop the row: the
    Wiktextract sense id is the traceable record. Senses without that id,
    without a catalog anchor, or tied to a blocked concept are not stored.
    A link-encoded QID is kept only when the catalog label matches that link
    title, so a wrong ``_Q`` suffix cannot attach the lemma to another concept.
    """
    if not isinstance(obj, dict):
        return []
    word = obj.get('word')
    language = obj.get('lang_code')
    if (not isinstance(word, str) or not isinstance(language, str)
            or language != expected_language):
        return []
    profile = (profiles or {}).get(language) or {}
    if is_placeholder(word) or not script_matches(word, profile.get('script')):
        return []
    pos = obj.get('pos') if isinstance(obj.get('pos'), str) else ''
    rows = []
    for sense in obj.get('senses') or []:
        if not isinstance(sense, dict):
            continue
        explicit, linked = sense_anchors(sense)
        if policy_qids(explicit)[0] != 'keep':
            continue
        linked = {
            qid: title for qid, title in linked.items()
            if policy_qids([qid])[0] == 'keep'
        }
        if not explicit and not linked:
            continue
        sense_id = sense.get('id')
        if (not isinstance(sense_id, str) or not sense_id.strip()
                or any(character.isspace() for character in sense_id)
                or len(sense_id) > 200):
            continue
        glosses = sense.get('glosses') or []
        gloss = glosses[0] if glosses and isinstance(glosses[0], str) else ''
        qids = list(explicit)
        for qid in linked:
            if qid not in qids:
                qids.append(qid)
        seen = set()
        ordered = list(explicit) + [qid for qid in linked if qid not in explicit]
        for qid in ordered:
            for concept in concepts_by_qid.get(qid) or []:
                if not isinstance(concept, dict):
                    continue
                if (qid not in explicit and _normalize_label(concept.get('anchor_label'))
                        != _normalize_label(linked.get(qid))):
                    continue
                concept_id = concept.get('concept_id')
                section = concept.get('section')
                if not isinstance(concept_id, str) or not concept_id:
                    continue
                if not isinstance(section, str) or not section:
                    continue
                identity = (sense_id, concept_id)
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append({
                    'schema_version': SCHEMA_VERSION,
                    'language': language,
                    'section': section,
                    'subsection': concept.get('subsection') or '',
                    'concept_id': concept_id,
                    'wikidata': qid,
                    'qids': qids,
                    'lemma': word,
                    'gloss': gloss,
                    'pos': pos,
                    'source_id': 'kaikki.wiktextract',
                    'record_id': sense_id,
                    'sense_id': sense_id,
                    'license_id': 'CC-BY-SA-4.0',
                    'co_offered': ['GFDL-1.3-only'],
                    'retrieval_date': retrieved,
                    'origin_url': url,
                    'status': 'keep',
                })
    return rows
