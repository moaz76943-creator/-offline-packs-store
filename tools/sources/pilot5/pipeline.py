#!/usr/bin/env python3
"""Fail-closed offline Wiktextract JSONL importer; only reviewed, hashed source artifacts."""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

LANGS = {'de': 'Latn', 'ar': 'Arab', 'en': 'Latn', 'es': 'Latn', 'fr': 'Latn'}
POS = {'noun': 'noun', 'proper-noun': 'noun', 'verb': 'verb', 'adj': 'adjective',
       'adv': 'adverb', 'pron': 'pronoun', 'prep': 'preposition',
       'phrase': 'multiword', 'proverb': 'multiword', 'conj': 'conjunction',
       'det': 'determiner', 'intj': 'interjection', 'num': 'numeral',
       'particle': 'particle'}
GENDERS = {'masculine', 'feminine', 'neuter'}
SHA = re.compile(r'^[0-9a-f]{64}$')
MAX_LINE = 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def stable(prefix, lang, *parts):
    key = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()
    return f'{prefix}.{lang}.{sha(key)[:24]}'


def nonempty(v):
    return isinstance(v, str) and bool(v.strip())


def normalize(v):
    return unicodedata.normalize('NFC', v)


def verify_source(ledger, source_id, input_path, root):
    """Apply Route 05 source-specific evidence checks, not blanket license assumptions."""
    found = [s for s in ledger.get('sources', []) if s.get('source_id') == source_id]
    if len(found) != 1:
        raise ValueError('source missing or duplicated in Route 05 ledger')
    s = found[0]
    lic, get, review = s.get('license') or {}, s.get('retrieval') or {}, s.get('review') or {}
    if s.get('status') != 'APPROVED_FOR_REDISTRIBUTION' or s.get('kind') != 'dictionary':
        raise ValueError('source not independently approved for dictionary redistribution')
    if lic.get('id') not in ('CC-BY-SA-4.0', 'CC0-1.0', 'PUBLIC-DOMAIN'):
        raise ValueError('unreviewed or incompatible license; GFDL requires separate approval')
    for x in (s.get('publisher'), s.get('dataset_version'), get.get('identity'),
              review.get('reviewer'), review.get('decision_url')):
        if not nonempty(x):
            raise ValueError('missing source version, retrieval identity or manual approval')
    for u in (s.get('origin_url'), get.get('url'), lic.get('evidence_url'), review.get('decision_url')):
        parts = urlsplit(u or '')
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError('invalid evidence URL')
    root = root.resolve()
    for relative, expected in ((get.get('artifact_path'), get.get('sha256')),
                               (lic.get('evidence_path'), lic.get('evidence_sha256'))):
        if not nonempty(relative) or not isinstance(expected, str) or not SHA.fullmatch(expected):
            raise ValueError('missing original artifact and license-proof SHA-256')
        rel = Path(relative)
        proof = (root / rel).resolve()
        if rel.is_absolute() or not proof.is_relative_to(root) or not proof.is_file():
            raise ValueError('missing or escaping original source evidence')
        if file_sha(proof) != expected:
            raise ValueError('source/license artifact hash mismatch')
    if (root / get['artifact_path']).resolve() != input_path.resolve():
        raise ValueError('input differs from reviewed source artifact')
    if lic['id'] == 'PUBLIC-DOMAIN':
        proof = lic.get('public_domain_proof') or {}
        if not all(nonempty(proof.get(k)) for k in ('jurisdiction', 'legal_basis', 'work_date')):
            raise ValueError('public domain needs jurisdiction-specific proof')
    return s


def provenance(s, locator):
    return {'source_id': s['source_id'], 'origin_url': s['origin_url'],
            'publisher': s['publisher'], 'dataset_version': s['dataset_version'],
            'retrieval_id': s['retrieval']['identity'], 'license_id': s['license']['id'],
            'record_locator': locator, 'artifact_sha256': s['retrieval']['sha256'],
            'publication_approved': True, 'fixture_only': False}


def extract(row, lang, source, locator):
    """Only explicit attested forms, original glosses and recorded pronunciation."""
    if not isinstance(row, dict) or row.get('lang_code') != lang:
        return None
    word, pos = row.get('word'), POS.get(row.get('pos'))
    if not nonempty(word) or not pos or not isinstance(row.get('senses'), list):
        return None
    word = normalize(word)
    if lang == 'en' and pos == 'verb' and ' ' in word.strip():
        pos = 'multiword'
    etym = row.get('etymology_number')
    if etym is not None and (not isinstance(etym, int) or isinstance(etym, bool)):
        return None
    lid = stable('lex', lang, word, pos, etym)
    src = provenance(source, locator)
    lex = {'lexeme_id': lid, 'language': lang, 'script': LANGS[lang],
           'direction': 'rtl' if lang == 'ar' else 'ltr',
           'lemma': word, 'surface': word, 'pos': pos, 'source': src}
    if nonempty(row.get('dialect')):
        lex['dialect'] = row['dialect']
    if nonempty(row.get('etymology_text')):
        lex['homograph_key'] = stable('etym', lang, etym, row['etymology_text'])
    morph = {}
    head_tags = row.get('tags', [])
    genders = set(head_tags) & GENDERS if isinstance(head_tags, list) else set()
    if len(genders) == 1:
        morph['gender'] = next(iter(genders))
    forms = row.get('forms', [])
    if isinstance(forms, list):
        inflections, conjugations, articles = [], [], []
        for entry in forms[:200]:
            if not isinstance(entry, dict) or not nonempty(entry.get('form')):
                continue
            raw_tags = entry.get('tags', [])
            if not isinstance(raw_tags, list):
                continue
            tags = set(x for x in raw_tags if isinstance(x, str))
            if tags & {'canonical', 'table-tags'}:
                continue
            features = {}
            for key, options in (('number', {'singular', 'plural'}),
                                 ('tense', {'past', 'present', 'future'}),
                                 ('degree', {'comparative', 'superlative'})):
                v = tags & options
                if len(v) == 1:
                    features[key] = next(iter(v))
            if {'article', 'definite'} <= tags:
                features['definiteness'] = 'definite'
                bucket = articles
            else:
                bucket = conjugations if pos == 'verb' else inflections
            if not features:
                continue
            item = {'surface': normalize(entry['form']), 'features': features, 'attested': True}
            if item not in bucket:
                bucket.append(item)
        for key, values in (('articles', articles), ('inflections', inflections),
                            ('conjugations', conjugations)):
            if values:
                morph[key] = values
    if morph:
        lex['morphology'] = morph
    sounds = row.get('sounds', [])
    phonetics = []
    if isinstance(sounds, list):
        for sound in sounds[:100]:
            if isinstance(sound, dict) and nonempty(sound.get('ipa')):
                p = {'notation': 'ipa', 'value': sound['ipa'], 'source': src}
                if p not in phonetics:
                    phonetics.append(p)
    if phonetics:
        lex['pronunciations'] = phonetics[:20]
    senses, used = [], set()
    for item in row['senses']:
        if not isinstance(item, dict):
            continue
        glosses = item.get('glosses', [])
        if not isinstance(glosses, list):
            continue
        raw_tags = item.get('tags', [])
        tags = sorted(set(x for x in raw_tags if nonempty(x))) if isinstance(raw_tags, list) else []
        for gloss in glosses:
            if not nonempty(gloss):
                continue
            definition = normalize(gloss)
            sid = stable('sense', lang, lid, definition, tags)
            if sid in used:
                continue
            used.add(sid)
            senses.append({'sense_id': sid, 'lexeme_id': lid,
                           'concept_id': stable('concept.unmapped', lang, sid),
                           'definition': definition, 'source': src})
    return (lex, senses) if senses else None


def ingest(path, lang, source, limit=200, previous=None):
    """Stream source artifact line by line, bound accepted vocabulary and senses."""
    if lang not in LANGS or not (1 <= limit <= 10000):
        raise ValueError('unsupported language or limit')
    doc = previous or {'contract_version': '1.0.0', 'document_id': 'pilot5.' + lang,
                       'lexemes': [], 'senses': [], 'translations': [],
                       'examples': [], 'relations': []}
    if doc.get('document_id') != 'pilot5.' + lang:
        raise ValueError('incorrect previous partition identity')
    lexemes = {x['lexeme_id']: x for x in doc['lexemes']}
    senses = {x['sense_id']: x for x in doc['senses']}
    if any(x['language'] != lang for x in lexemes.values()):
        raise ValueError('previous partition language mismatch')
    evidence = []
    counts = {'seen': 0, 'accepted': 0, 'accepted_senses': 0,
              'rejected': 0, 'duplicates': 0, 'limit_skipped': 0}
    with path.open('rb') as stream:
        for lineno, raw in enumerate(stream, 1):
            counts['seen'] += 1
            if len(raw) > MAX_LINE:
                counts['rejected'] += 1
                continue
            try:
                candidate = extract(json.loads(raw), lang, source, f'line:{lineno}')
            except (ValueError, UnicodeError, TypeError):
                candidate = None
            if not candidate:
                counts['rejected'] += 1
                continue
            lex, new_senses = candidate
            is_new = lex['lexeme_id'] not in lexemes
            if not is_new and (lexemes[lex['lexeme_id']]['lemma'] != lex['lemma'] or
                               lexemes[lex['lexeme_id']]['pos'] != lex['pos']):
                raise ValueError('stable ID collision')
            if is_new and len(lexemes) >= limit:
                counts['limit_skipped'] += 1
                continue
            unique = [s for s in new_senses if s['sense_id'] not in senses]
            if not is_new and not unique:
                counts['duplicates'] += 1
                continue
            if len(senses) + len(unique) > limit * 32:
                counts['limit_skipped'] += 1
                continue
            if is_new:
                lexemes[lex['lexeme_id']] = lex
                counts['accepted'] += 1
            for s in unique:
                senses[s['sense_id']] = s
            counts['accepted_senses'] += len(unique)
            evidence.append({'language': lang, 'source_id': source['source_id'],
                             'record_locator': f'line:{lineno}', 'raw_line_sha256': sha(raw),
                             'raw_line_utf8': raw.decode('utf-8')})
    doc['lexemes'] = sorted(lexemes.values(), key=lambda x: x['lexeme_id'])
    doc['senses'] = sorted(senses.values(), key=lambda x: x['sense_id'])
    return doc, evidence, counts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, default=Path.cwd())
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--source-id', required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--language', choices=sorted(LANGS), required=True)
    p.add_argument('--gloss-language', choices=sorted(LANGS), required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--previous', type=Path)
    p.add_argument('--limit', type=int, default=200)
    a = p.parse_args(argv)
    try:
        ledger = json.loads(a.ledger.read_text(encoding='utf-8'))
        source = verify_source(ledger, a.source_id, a.input, a.repo_root)
        previous = json.loads(a.previous.read_text(encoding='utf-8')) if a.previous else None
        doc, evidence, counts = ingest(a.input, a.language, source, a.limit, previous)
        if a.out.exists():
            raise ValueError('output exists; snapshots must be immutable')
        a.out.mkdir(parents=True)
        (a.out / 'lexical.json').write_text(
            json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        (a.out / 'evidence.jsonl').write_text(
            ''.join(json.dumps(x, ensure_ascii=False, sort_keys=True) + '\n' for x in evidence),
            encoding='utf-8')
        (a.out / 'provenance.json').write_text(json.dumps({
            'source_id': source['source_id'],
            'artifact_sha256': source['retrieval']['sha256'],
            'dataset_version': source['dataset_version'], 'license_id': source['license']['id'],
            'language': a.language, 'definition_language': a.gloss_language,
            'counts': counts}, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'IMPORTED_REVIEW_REQUIRED', 'language': a.language,
                          'counts': counts}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps({'status': 'BLOCKED_SOURCE', 'language': a.language,
                          'accepted': 0, 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
