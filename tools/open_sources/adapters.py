"""Parse open-licensed records into candidate fills. Missing words stay gaps."""

import json
from pathlib import Path

from tools.language_production.catalog import ROOT, load_blocklist, load_json
from tools.open_sources.assess import source_is_compatible
from tools.open_sources.attribution import render_attribution
from tools.open_sources.policy import decide

SOURCES_PATH = ROOT / 'catalog' / 'organization' / 'sources.v1.json'
QID = __import__('re').compile(r'^Q[1-9][0-9]*$')


def load_sources(path=SOURCES_PATH):
    data = load_json(path)
    return {row['id']: row for row in data.get('sources') or [] if isinstance(row, dict) and row.get('id')}


def _notice(source, root=ROOT):
    evidence = source.get('evidence_path')
    if not evidence:
        return ''
    path = Path(root) / evidence
    if not path.is_file():
        return ''
    return path.read_text(encoding='utf-8')


def _qids(value):
    found = []
    if isinstance(value, str) and QID.fullmatch(value):
        found.append(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and QID.fullmatch(item):
                found.append(item)
    return found


def _level(text):
    count = len((text or '').split())
    if count <= 6:
        level = 'A1'
    elif count <= 10:
        level = 'A2'
    elif count <= 16:
        level = 'B1'
    elif count <= 24:
        level = 'B2'
    else:
        level = 'C1'
    return {
        'framework_id': 'cefr',
        'level_id': level,
        'evidence': f'estimated:heuristic-v1; tokens={count}; not a certified CEFR placement',
    }


def _base(source, status, reason, **fields):
    row = {
        'source_id': source['id'],
        'status': status,
        'reason': reason,
        'license_id': source.get('stated_license'),
        'publication_approved': False,
        'ledger_compatible': bool(source.get('compatible')) and status == 'keep',
    }
    row.update(fields)
    return row


def adapt_records(source_id, records, *, sources=None, blocklist=None, root=ROOT):
    """Return candidate rows and one attribution document. Incompatible sources reject every row."""
    sources = sources or load_sources()
    source = sources[source_id]
    if blocklist is None:
        blocked_concepts, blocked_lemmas = load_blocklist()
    else:
        blocked_concepts, blocked_lemmas = blocklist
    compatible, reasons = source_is_compatible(source, _notice(source, root))
    allow_candidate = bool(source.get('candidate_when_attributed'))
    parser = _PARSERS.get(source_id, _reject_unknown)
    kept = []
    rows = []
    for record in records or []:
        if not compatible and not allow_candidate:
            rows.append(_base(source, 'reject', reasons[0] if reasons else 'source_blocked'))
            continue
        parsed = parser(source, record, blocked_concepts, blocked_lemmas)
        rows.append(parsed)
        if parsed['status'] == 'keep':
            kept.append(parsed)
    changes = 'no words invented; records that fail the license or the content policy are rejected'
    authors = sorted({row.get('author') for row in kept if row.get('author')})
    if authors:
        source = dict(source)
        attribution_fields = dict(source.get('attribution') or {})
        creators = list(attribution_fields.get('creators') or [])
        for name in authors:
            if name not in creators:
                creators.append(name)
        attribution_fields['creators'] = creators
        source['attribution'] = attribution_fields
    attribution = render_attribution(source, record_count=len(kept), changes=changes)
    return {'rows': rows, 'attribution': attribution, 'kept': len(kept)}


def _reject_unknown(source, record, blocked_concepts, blocked_lemmas):
    return _base(source, 'reject', 'no adapter')


def _kaikki(source, record, blocked_concepts, blocked_lemmas):
    if not isinstance(record, dict):
        return _base(source, 'reject', 'malformed_record')
    lemma = record.get('word') if isinstance(record.get('word'), str) else ''
    language = record.get('lang_code') if isinstance(record.get('lang_code'), str) else ''
    qids = []
    gloss = ''
    for sense in record.get('senses') or []:
        if not isinstance(sense, dict):
            continue
        qids.extend(_qids(sense.get('wikidata')))
        glosses = sense.get('glosses') or []
        if not gloss and glosses and isinstance(glosses[0], str):
            gloss = glosses[0]
    decision, reason = decide(lemma, qids, blocked_concepts, blocked_lemmas)
    if decision != 'keep':
        return _base(source, decision, reason, language=language)
    if not lemma or not language:
        return _base(source, 'reject', 'missing_lemma_or_language')
    concept_id = f'concept.{qids[0].lower()}' if qids else None
    if concept_id is None:
        return _base(source, 'unplaced', 'no_wikidata_anchor', language=language, lemma=lemma)
    return _base(
        source, 'keep', '', language=language, lemma=lemma, gloss=gloss,
        concept_id=concept_id, wikidata=qids[0],
    )


def _tatoeba(source, record, blocked_concepts, blocked_lemmas):
    if not isinstance(record, dict):
        return _base(source, 'reject', 'malformed_record')
    text = record.get('text') if isinstance(record.get('text'), str) else ''
    author = record.get('author') if isinstance(record.get('author'), str) else ''
    language = record.get('language') if isinstance(record.get('language'), str) else ''
    decision, reason = decide(text, [], blocked_concepts, blocked_lemmas)
    if decision != 'keep':
        return _base(source, decision, reason, language=language)
    if not text or not language:
        return _base(source, 'reject', 'missing_text_or_language')
    if not author.strip():
        return _base(source, 'quarantine', 'missing_attribution', language=language)
    level = _level(text)
    return _base(
        source, 'keep', 'candidate_only_not_ledger_license', language=language,
        text=text, author=author.strip(), level=level, ledger_compatible=False,
    )


def _morphology(source, record, blocked_concepts, blocked_lemmas, license_notice):
    if not isinstance(record, dict):
        return _base(source, 'reject', 'malformed_record')
    ok, reasons = source_is_compatible(
        {'compatible': True, 'declared_license': 'CC-BY-SA-4.0', 'co_offered_licenses': []},
        license_notice,
    )
    # A per-record notice can also be CC0 or GFDL. Try the allowed declarations.
    if not ok:
        for declared in ('CC0-1.0', 'GFDL-1.3-only', 'PUBLIC-DOMAIN'):
            ok, reasons = source_is_compatible(
                {'compatible': True, 'declared_license': declared, 'co_offered_licenses': []},
                license_notice,
            )
            if ok:
                break
    if not ok:
        return _base(source, 'reject', reasons[0] if reasons else 'license_not_in_ledger')
    lemma = record.get('lemma') if isinstance(record.get('lemma'), str) else ''
    language = record.get('language') if isinstance(record.get('language'), str) else ''
    decision, reason = decide(lemma, _qids(record.get('wikidata')), blocked_concepts, blocked_lemmas)
    if decision != 'keep':
        return _base(source, decision, reason, language=language)
    if not lemma or not language:
        return _base(source, 'reject', 'missing_lemma_or_language')
    return _base(
        source, 'keep', '', language=language, lemma=lemma,
        features=record.get('features') if isinstance(record.get('features'), str) else '',
    )


def _ud(source, record, blocked_concepts, blocked_lemmas):
    notice = record.get('license_notice') if isinstance(record, dict) else ''
    return _morphology(source, record, blocked_concepts, blocked_lemmas, notice)


def _blocked_source(source, record, blocked_concepts, blocked_lemmas):
    return _base(source, 'reject', source.get('blocked_reason') or 'source_blocked')


_PARSERS = {
    'kaikki.wiktextract': _kaikki,
    'tatoeba.sentences': _tatoeba,
    'universal-dependencies': _ud,
    'unimorph': _blocked_source,
    'apertium': _blocked_source,
    'omegawiki': _blocked_source,
}


def read_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
