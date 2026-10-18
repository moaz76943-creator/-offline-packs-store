#!/usr/bin/env python3
"""Fail-closed, source-backed, disk-bounded lexical candidate ingestion.

Never approves a corpus, guesses translations, or publishes a SQLite pack.
GHA-01/Route05 approval is a prerequisite on every invocation.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.gha_factory.admission import pipeline as gha01

MAX_LINE = 1024 * 1024
POS = {'noun': 'noun', 'proper-noun': 'noun', 'verb': 'verb', 'adj': 'adjective',
       'adv': 'adverb', 'pron': 'pronoun', 'prep': 'preposition', 'conj': 'conjunction',
       'det': 'determiner', 'intj': 'interjection', 'num': 'numeral',
       'particle': 'particle', 'phrase': 'multiword', 'proverb': 'multiword',
       'classifier': 'classifier'}
COUNTERS = ('source_rows', 'selected_rows', 'accepted_lexemes', 'accepted_senses',
            'rejected_rows', 'duplicate_rows', 'translation_gaps', 'form_gaps')


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def identifier(prefix, lang, *parts):
    return f'{prefix}.{lang}.{digest(parts)[:24]}'


def language_registry(root):
    path = Path(root) / 'catalog/language_registry.v1.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        rows = data['languages']
        if data['schema_version'] != '1.0.0' or len(rows) != 100:
            raise ValueError('invalid canonical registry cardinality')
        entries = {row['id']: row['default_script'] for row in rows}
        if len(entries) != len(rows) or not all(isinstance(s, str) and s for s in entries.values()):
            raise ValueError('duplicate/invalid language identity')
        return entries
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ValueError('BLOCKED_LANGUAGE: invalid canonical 100-language registry') from exc


def json_object(raw):
    def no_repeated(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('repeated JSON key')
            result[key] = value
        return result
    obj = json.loads(raw.decode('utf-8'), object_pairs_hook=no_repeated,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
    if not isinstance(obj, dict):
        raise ValueError('non-object input')
    return obj


def attested(row, lang, script, source, line):
    """Return Route06-shaped lexeme/senses; absent facts remain absent."""
    if row.get('lang_code') != lang:
        raise ValueError('LANGUAGE_LABEL_MISMATCH')
    if row.get('source_id', source['source_id']) != source['source_id']:
        raise ValueError('SOURCE_LABEL_MISMATCH')
    if row.get('license_id', source['license']['id']) != source['license']['id']:
        raise ValueError('LICENSE_LABEL_MISMATCH')
    word = row.get('word')
    pos = POS.get(row.get('pos'))
    if not isinstance(word, str) or not word.strip() or len(word) > 256 or not pos:
        raise ValueError('INVALID_LEMMA_POS')
    if not gha01.script_valid(word, script):
        raise ValueError('LANGUAGE_SCRIPT_MISMATCH_OR_UNVERIFIED')
    original_id = row.get('id')
    if original_id is not None and (not isinstance(original_id, (str, int)) or isinstance(original_id, bool)):
        raise ValueError('INVALID_SOURCE_RECORD_ID')
    etym = row.get('etymology_number')
    if etym is not None and (type(etym) is not int or etym < 0):
        raise ValueError('INVALID_ETYMOLOGY_NUMBER')
    if not isinstance(row.get('senses'), list) or len(row['senses']) > 256:
        raise ValueError('INVALID_SENSES')
    lexid = identifier('lex', lang, source['source_id'], original_id if original_id is not None else
                       [word, pos, etym, row.get('etymology_text')])
    src = {'source_id': source['source_id'], 'origin_url': source['origin_url'],
           'publisher': source['publisher'], 'dataset_version': source['dataset_version'],
           'retrieval_id': source['retrieval']['identity'], 'license_id': source['license']['id'],
           'record_locator': f'line:{line}' + (f';record:{original_id}' if original_id is not None else ''),
           'artifact_sha256': source['retrieval']['sha256'],
           'publication_approved': False, 'fixture_only': False}
    lex = {'lexeme_id': lexid, 'language': lang, 'script': script,
           'direction': 'rtl' if script in ('Arab', 'Hebr') else 'ltr',
           'lemma': word, 'surface': word, 'pos': pos, 'source': src}
    if isinstance(row.get('dialect'), str) and row['dialect'].strip():
        lex['dialect'] = row['dialect']
    if isinstance(row.get('register'), str) and row['register'].strip():
        lex['register'] = row['register']
    if etym is not None:
        lex['homograph_key'] = f'etymology:{etym}'
    forms = []
    if isinstance(row.get('forms'), list):
        if len(row['forms']) > 512:
            raise ValueError('TOO_MANY_FORMS')
        for form in row['forms']:
            if not isinstance(form, dict) or not isinstance(form.get('form'), str) or not form['form'].strip():
                continue
            tags = form.get('tags', [])
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                continue
            if any(tag in ('canonical', 'table-tags', 'romanization') for tag in tags):
                continue
            # Inflections must use the headword script. Latin transliterations are not Arabic forms.
            if not gha01.script_valid(form['form'], script):
                continue
            features = {'tag_' + str(i): tag for i, tag in enumerate(tags[:20])}
            item = {'surface': form['form'], 'features': features, 'attested': True, 'source': src}
            if item not in forms:
                forms.append(item)
    if forms:
        lex['morphology'] = {'inflections': forms}
    pronunciations = []
    sounds = row.get('sounds', [])
    if isinstance(sounds, list):
        for item in sounds[:50]:
            if isinstance(item, dict) and isinstance(item.get('ipa'), str) and item['ipa'].strip():
                pron = {'notation': 'ipa', 'value': item['ipa'], 'source': src}
                if pron not in pronunciations:
                    pronunciations.append(pron)
    if pronunciations:
        lex['pronunciations'] = pronunciations
    senses = []
    for index, sense in enumerate(row['senses']):
        if not isinstance(sense, dict) or not isinstance(sense.get('glosses'), list):
            continue
        glosses = sense['glosses']
        if len(glosses) > 64:
            raise ValueError('TOO_MANY_GLOSSES')
        for n, definition in enumerate(glosses):
            if not isinstance(definition, str) or not definition.strip() or len(definition) > 10000:
                continue
            sid = identifier('sense', lang, lexid, sense.get('id', index), n, definition)
            datum = {'sense_id': sid, 'lexeme_id': lexid,
                     'concept_id': identifier('concept.unmapped', lang, sid),
                     'definition': definition, 'source': src}
            tags = sense.get('tags', [])
            if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
                labels = [t for t in tags if t in ('formal', 'informal', 'colloquial', 'slang', 'archaic')]
                if len(labels) == 1:
                    datum['register'] = labels[0]
            senses.append(datum)
    if not senses:
        raise ValueError('NO_ATTESTED_SENSES')
    return lex, senses


def shard_for(row, raw, lang, source_id, count):
    if isinstance(row, dict) and row.get('lang_code') == lang:
        key = [source_id, lang, row.get('id'), row.get('word'), row.get('pos'),
               row.get('etymology_number'), row.get('etymology_text')]
    else:
        key = [raw.hex()[:128], hashlib.sha256(raw).hexdigest()]
    return int(digest(key)[:16], 16) % count


def approved(root, source_id, lang):
    root = Path(root).resolve()
    registry = language_registry(root)
    if lang not in registry:
        raise ValueError('BLOCKED_LANGUAGE: unknown language identity')
    ledger = json.loads((root / 'legal/ledger/sources.json').read_text(encoding='utf-8'))
    matching = [s for s in ledger.get('sources', []) if s.get('source_id') == source_id]
    if len(matching) != 1:
        raise ValueError('BLOCKED_SOURCE: missing/duplicate source')
    source = matching[0]
    retrieval = source.get('retrieval') or {}
    path = gha01.checked_file(root, retrieval.get('artifact_path'), retrieval.get('sha256'), 'source')
    gha01.route05_source(root, source_id, source.get('dataset_version'), path, 'wiktextract-jsonl')
    reviewer = source.get('review') or {}
    gha01.checked_file(root, reviewer.get('evidence_path'), reviewer.get('evidence_sha256'), 'review')
    if path.suffix != '.jsonl':
        raise ValueError('BLOCKED_SOURCE: immutable plain JSONL only (compressed snapshots require separately audited adapter)')
    return registry[lang], source, path, digest(registry)


def quality_flags(counts):
    samples = [v.get('accepted_lexemes', 0) for v in counts.values() if v.get('accepted_lexemes', 0) >= 1000]
    return ['SUSPICIOUS_UNIFORM_COUNTS'] if len(samples) >= 4 and len(set(samples)) == 1 else []


def ingest(root, source_id, lang, checkpoint, *, shard=0, shards=1, batch=512, max_rows=None):
    if type(shard) is not int or type(shards) is not int or not 1 <= shards <= 4096 or not 0 <= shard < shards:
        raise ValueError('INVALID_SHARD')
    if type(batch) is not int or not 1 <= batch <= 10000 or (max_rows is not None and
              (type(max_rows) is not int or max_rows < 1)):
        raise ValueError('INVALID_BATCH_OR_LIMIT')
    script, source, path, reg_sha = approved(root, source_id, lang)
    key = digest([source_id, source['dataset_version'], source['retrieval']['identity'],
                  source['retrieval']['sha256'], reg_sha, lang, shard, shards, 'lexical-scale-v1'])
    checkpoint = Path(checkpoint)
    if checkpoint.exists() and checkpoint.is_symlink():
        raise ValueError('CHECKPOINT_SYMLINK')
    if not checkpoint.parent.is_dir():
        raise ValueError('CHECKPOINT_PARENT_MISSING')
    with sqlite3.connect(checkpoint, timeout=0.1) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL, offset INTEGER NOT NULL, line INTEGER NOT NULL, counters TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS lexemes (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS senses (id TEXT PRIMARY KEY, lexeme TEXT NOT NULL, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS evidence (source_line INTEGER PRIMARY KEY, raw_sha256 TEXT NOT NULL, lexeme_id TEXT NOT NULL)')
        db.commit()
        state = db.execute('SELECT identity,offset,line,counters FROM state WHERE id=1').fetchone()
        if state is not None and state[0] != key:
            raise ValueError('CHECKPOINT_IDENTITY_MISMATCH')
        offset, line, counts = (state[1], state[2], json.loads(state[3])) if state else (0, 0, dict.fromkeys(COUNTERS, 0))
        processed = 0
        size = path.stat().st_size
        with path.open('rb') as stream:
            stream.seek(offset)
            while stream.tell() < size and (max_rows is None or processed < max_rows):
                raw = stream.readline(MAX_LINE + 1)
                if not raw:
                    break
                oversized = len(raw) > MAX_LINE or not raw.endswith(b'\n')
                if not raw.endswith(b'\n'):
                    while raw and not raw.endswith(b'\n') and stream.tell() < size:
                        raw = stream.readline(MAX_LINE + 1)
                line += 1
                processed += 1
                counts['source_rows'] += 1
                selected = False
                invalid_owner = shard_for(None, raw, lang, source_id, shards) == shard
                try:
                    if oversized:
                        raise ValueError('INVALID_JSONL_FRAMING')
                    record = json_object(raw)
                    selected = shard_for(record, raw, lang, source_id, shards) == shard
                    if selected:
                        counts['selected_rows'] += 1
                        lex, senses = attested(record, lang, script, source, line)
                        old = db.execute('SELECT payload FROM lexemes WHERE id=?', (lex['lexeme_id'],)).fetchone()
                        if old is not None and any(json.loads(old[0])[k] != lex[k] for k in ('lemma', 'pos', 'script')):
                            raise ValueError('STABLE_ID_COLLISION')
                        if old is None:
                            db.execute('INSERT INTO lexemes VALUES (?,?)', (lex['lexeme_id'], canonical(lex)))
                            counts['accepted_lexemes'] += 1
                        added = 0
                        for sense in senses:
                            before = db.total_changes
                            db.execute('INSERT OR IGNORE INTO senses VALUES (?,?,?)',
                                       (sense['sense_id'], lex['lexeme_id'], canonical(sense)))
                            added += db.total_changes - before
                        counts['accepted_senses'] += added
                        if old is not None and not added:
                            counts['duplicate_rows'] += 1
                        db.execute('INSERT OR REPLACE INTO evidence VALUES (?,?,?)',
                                   (line, hashlib.sha256(raw).hexdigest(), lex['lexeme_id']))
                        if record.get('translations') or record.get('translation'):
                            counts['translation_gaps'] += 1
                        if not lex.get('morphology'):
                            counts['form_gaps'] += 1
                except (ValueError, TypeError, UnicodeError, OverflowError):
                    # Count malformed or unroutable records in exactly one deterministic shard.
                    if selected or invalid_owner:
                        counts['rejected_rows'] += 1
                if processed % batch == 0:
                    db.execute('INSERT OR REPLACE INTO state VALUES (1,?,?,?,?)',
                               (key, stream.tell(), line, canonical(counts)))
                    db.commit()
            position = stream.tell()
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?,?,?,?)',
                   (key, position, line, canonical(counts)))
        db.commit()
        result = {'status': 'REVIEW_REQUIRED', 'source_id': source_id, 'language': lang,
                  'source_sha256': source['retrieval']['sha256'], 'shard': shard, 'shards': shards,
                  'checkpoint_id': key, 'checkpoint_line': line, 'checkpoint_byte': position,
                  'complete': position == size, **counts,
                  'coverage_gaps': ['translations_unresolved', 'unattested_forms_not_inferred'],
                  'publication_approved': False}
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--source-id', required=True)
    p.add_argument('--language', required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=1)
    p.add_argument('--batch', type=int, default=512)
    p.add_argument('--max-rows', type=int)
    args = p.parse_args(argv)
    try:
        print(canonical(ingest(args.root, args.source_id, args.language, args.checkpoint,
                               shard=args.shard, shards=args.shards, batch=args.batch,
                               max_rows=args.max_rows)))
    except (OSError, ValueError, sqlite3.Error, gha01.AdmissionError) as exc:
        print(canonical({'status': 'BLOCKED_SOURCE_OR_VALIDATION', 'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
