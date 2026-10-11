#!/usr/bin/env python3
"""Compile local <language>.json/.sqlite sources into canonical json-gzip-v1 packs.

Requires only Python 3.9+ standard library; no network or external tooling.

Usage:
    python tools/compile_store_packs.py --source-dir tools/sources --dry-run
    python tools/compile_store_packs.py --source-dir tools/sources

JSON input: {"languageCode":"de", "displayName":"German", "direction":"ltr",
 "lexicon":[{"id":"1","surface":"Haus","part_of_speech":"noun",
             "fields_json":{"artikel":"das"}}], "concepts":[]}
SQLite input: a database with a nonempty lexicon table and columns
id, surface, part_of_speech, fields_json; direction may come from either
that table or the existing manifest language entry. The legacy pack binaries
are intentionally NEVER treated as source content.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

VERSION = '1.0.0'
SCHEMA_VERSION = '2.0.0'
FORMAT = 'json-gzip-v1'
REPO_CDN = 'https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs'
CODE_RE = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')
DDL = '''
CREATE TABLE lexicon (
 id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
 direction TEXT NOT NULL, fields_json TEXT NOT NULL,
 cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_lexicon_cefr_freq ON lexicon(cefr_level, frequency_rank);
CREATE INDEX IF NOT EXISTS idx_lexicon_surface_nocase ON lexicon(surface COLLATE NOCASE);
CREATE VIRTUAL TABLE IF NOT EXISTS lexicon_fts USING fts5(surface, translation_ar, tokenize='trigram');
CREATE TABLE IF NOT EXISTS verbs (verb_id TEXT PRIMARY KEY, infinitive TEXT NOT NULL, translation_ar TEXT, frequency_rank INTEGER);
CREATE TABLE IF NOT EXISTS verb_conjugations (conjugation_id TEXT PRIMARY KEY, verb_id TEXT NOT NULL, tense TEXT NOT NULL, person TEXT NOT NULL, conjugated_form TEXT NOT NULL, FOREIGN KEY(verb_id) REFERENCES verbs(verb_id));
CREATE INDEX IF NOT EXISTS idx_verb_conjugations_verb_tense ON verb_conjugations(verb_id, tense);
CREATE TABLE IF NOT EXISTS idioms (idiom_id TEXT PRIMARY KEY, expression TEXT NOT NULL, translation_ar TEXT, explanation TEXT, language_code TEXT);
CREATE TABLE IF NOT EXISTS nominals (id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id))>0), lemma TEXT NOT NULL CHECK(length(trim(lemma))>0), part_of_speech TEXT NOT NULL CHECK(part_of_speech IN ('noun','adjective','pronoun')), gender TEXT NOT NULL CHECK(length(trim(gender))>0), number TEXT NOT NULL CHECK(length(trim(number))>0));
CREATE TABLE IF NOT EXISTS nominal_declensions (id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id))>0), nominal_id TEXT NOT NULL CHECK(length(trim(nominal_id))>0), grammatical_case TEXT NOT NULL CHECK(length(trim(grammatical_case))>0), number TEXT NOT NULL CHECK(length(trim(number))>0), definiteness TEXT NOT NULL CHECK(length(trim(definiteness))>0), inflected_form TEXT NOT NULL CHECK(length(trim(inflected_form))>0), FOREIGN KEY(nominal_id) REFERENCES nominals(id) ON DELETE RESTRICT);
CREATE INDEX IF NOT EXISTS idx_nominal_declensions_nominal_case_number ON nominal_declensions(nominal_id, grammatical_case, number);
CREATE TABLE concepts (
 concept_id TEXT PRIMARY KEY, lemma TEXT, part_of_speech TEXT, cefr TEXT
);
CREATE VIEW lexemes AS
 SELECT id, surface, part_of_speech, direction, fields_json FROM lexicon;
CREATE VIEW examples AS
 SELECT id AS lexeme_id, surface,
        json_extract(fields_json, '$.examples') AS examples_json
 FROM lexicon WHERE json_type(fields_json, '$.examples') IS NOT NULL;
'''


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty UTF-8 text')
    return value


def fields_json(value):
    if isinstance(value, str):
        obj = json.loads(value)
    else:
        obj = value
    if not isinstance(obj, dict):
        raise ValueError('fields_json must be a JSON object')
    return canonical_json(obj).decode('utf-8').rstrip('\n')


def arabic_translations(fields):
    """Index only explicit Arabic translations; do not synthesize translations."""
    output = []

    def add(value):
        if isinstance(value, str) and value.strip():
            output.append(value.strip())
        elif isinstance(value, list):
            for piece in value:
                add(piece)

    add(fields.get('translation_ar'))
    translated = fields.get('translations')
    if isinstance(translated, dict):
        add(translated.get('ar'))
    elif isinstance(translated, list):
        for item in translated:
            if isinstance(item, dict) and item.get('languageCode', item.get('language_code')) == 'ar':
                add(item.get('text'))
    if fields.get('translationLanguageCode', fields.get('translation_language_code')) == 'ar':
        add(fields.get('translation'))
    return '\n'.join(dict.fromkeys(output))


def lexicon_metadata(entry):
    """Preserve source-backed CEFR/rank and provide deterministic Unicode sort key."""
    raw = fields_json(entry.get('fields_json'))
    fields = json.loads(raw)
    canonical = fields.get('canonical')
    if not isinstance(canonical, dict):
        canonical = {}
    cefr = next((value for value in (
        entry.get('cefr_level'), canonical.get('cefr'), fields.get('cefr_level'), fields.get('cefr')
    ) if value is not None), None)
    if cefr is not None and cefr not in ('unknown', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2'):
        raise ValueError(f'invalid CEFR label: {cefr!r}')
    rank = next((value for value in (
        entry.get('frequency_rank'), canonical.get('frequencyRank'),
        canonical.get('frequency_rank'), fields.get('frequency_rank'), fields.get('frequencyRank')
    ) if value is not None), None)
    if rank is not None and (type(rank) is not int or rank < 1):
        raise ValueError(f'invalid frequency rank: {rank!r}')
    sort_key = entry.get('sort_key') or unicodedata.normalize(
        'NFKC', required_text(entry.get('surface'), 'surface')).casefold()
    if not isinstance(sort_key, str):
        raise ValueError('sort_key must be text')
    return raw, fields, cefr, rank, sort_key


def verify_legacy_files(languages, output_dir):
    """Fail closed if existing published legacy size/hash metadata is stale."""
    for item in languages:
        if not isinstance(item, dict):
            raise ValueError('legacy manifest language entry must be an object')
        keys = ('pack_file', 'size_bytes', 'sha256')
        if not any(key in item for key in keys):
            continue  # An unpublished language descriptor, not a package.
        if not all(key in item for key in keys):
            raise ValueError('incomplete legacy pack integrity metadata')
        name = item['pack_file']
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.pack.gz'):
            raise ValueError(f'unsafe legacy pack filename: {name!r}')
        expected_url = f'{REPO_CDN}/{name}'
        if item.get('pack_url', expected_url) != expected_url:
            raise ValueError(f'legacy package URL mismatch: {name}')
        source = output_dir / name
        if not source.is_file():
            raise FileNotFoundError(f'missing legacy pack {source}')
        actual = source.read_bytes()
        if len(actual) != item['size_bytes'] or digest(actual) != item['sha256']:
            raise ValueError(f'legacy package checksum/size mismatch: {name}')


def input_rows(src, language):
    """Yield lexicon and concepts without manufacturing absent content."""
    if src.suffix == '.json':
        root = json.loads(src.read_text(encoding='utf-8'))
        if not isinstance(root, dict) or root.get('languageCode', language) != language:
            raise ValueError(f'{src.name}: invalid languageCode')
        lexicon = root.get('lexicon')
        concepts = root.get('concepts', [])
        if not isinstance(lexicon, list) or not isinstance(concepts, list):
            raise ValueError(f'{src.name}: lexicon/concepts must be arrays')
        return root, lexicon, concepts
    if src.suffix != '.sqlite':
        raise ValueError(f'unsupported source {src.name}')
    uri = 'file:' + quote(str(src.resolve()), safe='/') + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        cols = {row[1] for row in conn.execute('PRAGMA table_info(lexicon)')}
        mandatory = {'id', 'surface', 'part_of_speech', 'fields_json'}
        if not mandatory.issubset(cols):
            raise ValueError(f'{src.name}: missing lexicon columns {sorted(mandatory - cols)}')
        fields = 'id,surface,part_of_speech,fields_json' + ''.join(',' + key for key in ('direction','cefr_level','frequency_rank','sort_key') if key in cols)
        lexicon = [dict(zip([c.strip() for c in fields.split(',')], row))
                   for row in conn.execute('SELECT ' + fields + ' FROM lexicon ORDER BY id')]
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='concepts'").fetchone()
        concepts = []
        if exists:
            cc = {row[1] for row in conn.execute('PRAGMA table_info(concepts)')}
            if {'concept_id', 'lemma', 'part_of_speech', 'cefr'}.issubset(cc):
                keys = ['concept_id', 'lemma', 'part_of_speech', 'cefr']
                concepts = [dict(zip(keys, row)) for row in
                            conn.execute('SELECT concept_id,lemma,part_of_speech,cefr FROM concepts ORDER BY concept_id')]
            else:
                raise ValueError(f'{src.name}: concepts schema mismatch')
    return {}, lexicon, concepts


def compile_one(source, language, legacy, work_dir):
    source_meta, lexicon, concepts = input_rows(source, language)
    if not lexicon:
        raise ValueError(f'{source.name}: refusing to publish an empty lexicon')
    display = required_text(source_meta.get('displayName') or legacy.get('name') or language,
                            'displayName')
    direction = source_meta.get('direction') or legacy.get('direction')
    if direction not in ('ltr', 'rtl'):
        raise ValueError(f'{source.name}: direction must be declared as ltr or rtl')
    db_path = work_dir / f'{language}.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute('PRAGMA page_size=4096')
        db.executescript(DDL)
        for entry in sorted(lexicon, key=lambda item: required_text(item.get('id'), 'lexicon.id')):
            if not isinstance(entry, dict):
                raise ValueError(f'{language}: malformed lexicon row')
            row_direction = entry.get('direction') or direction
            if row_direction not in ('ltr', 'rtl'):
                raise ValueError(f'{language}: invalid row direction')
            raw, fields, cefr, rank, sort_key = lexicon_metadata(entry)
            inserted = db.execute(
                'INSERT INTO lexicon(id,surface,part_of_speech,direction,fields_json,cefr_level,frequency_rank,sort_key) VALUES (?,?,?,?,?,?,?,?)',
                (required_text(entry.get('id'), 'id'),
                 required_text(entry.get('surface'), 'surface'),
                 required_text(entry.get('part_of_speech'), 'part_of_speech'),
                 row_direction, raw, cefr, rank, sort_key))
            db.execute('INSERT INTO lexicon_fts(rowid,surface,translation_ar) VALUES (?,?,?)',
                       (inserted.lastrowid, entry['surface'], arabic_translations(fields)))
        for entry in sorted(concepts, key=lambda item: required_text(item.get('concept_id'), 'concept_id')):
            if not isinstance(entry, dict):
                raise ValueError(f'{language}: malformed concept row')
            db.execute('INSERT INTO concepts VALUES (?,?,?,?)', (
                required_text(entry.get('concept_id'), 'concept_id'),
                *[entry.get(key) for key in ('lemma', 'part_of_speech', 'cefr')]))
        db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
        if db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0] != len(lexicon):
            raise ValueError(f'{language}: FTS5 row count mismatch')
        db.execute('PRAGMA user_version=2')
        db.commit()
        db.execute('VACUUM')
        row_count = db.execute('SELECT count(*) FROM lexicon').fetchone()[0]
        verb_count = db.execute("SELECT count(*) FROM lexicon WHERE lower(part_of_speech) IN ('verb','v')").fetchone()[0]
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError(f'{language}: SQLite integrity_check failed')
    db_bytes = db_path.read_bytes()
    content_hash = digest(db_bytes)
    metadata = canonical_json({
        'packId': language, 'languageCode': language, 'displayName': display,
        'version': VERSION, 'contractVersion': VERSION, 'bundleFormat': FORMAT,
        'schemaVersion': SCHEMA_VERSION, 'format': FORMAT,
        'contentSha256': content_hash, 'contentRows': row_count, 'verbRows': verb_count
    })
    envelope = canonical_json({
        'packId': language, 'version': VERSION, 'contractVersion': VERSION,
        'schemaVersion': SCHEMA_VERSION, 'format': FORMAT,
        'files': [
            {'path': 'content/content.sqlite', 'contentBase64': base64.b64encode(db_bytes).decode('ascii')},
            {'path': 'metadata/pack.json', 'contentBase64': base64.b64encode(metadata).decode('ascii')},
        ]
    })
    archive_stream = io.BytesIO()
    with gzip.GzipFile(fileobj=archive_stream, mode='wb', filename='', mtime=0, compresslevel=9) as handle:
        handle.write(envelope)
    archive = archive_stream.getvalue()
    filename = f'{language}-{VERSION}.pack.gz'
    return archive, {
        'id': language, 'languageCode': language, 'displayName': display,
        'version': VERSION, 'contractVersion': VERSION, 'bundleFormat': FORMAT,
        'schemaVersion': SCHEMA_VERSION, 'format': FORMAT,
        'archiveUrl': f'{REPO_CDN}/{filename}',
        'sha256': digest(archive), 'contentSha256': content_hash,
        'archiveSizeBytes': len(archive), 'installedSizeBytes': len(db_bytes) + len(metadata),
    }


def store_if_different(path, data):
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.compile-', delete=False) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return True


def run(args):
    if not args.source_dir.is_dir():
        raise FileNotFoundError(f'source directory not found: {args.source_dir}')
    existing = json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest.exists() else {}
    if not isinstance(existing, dict):
        raise ValueError('manifest.json must be an object')
    prior_entries = existing.get('packs', [])
    if not isinstance(prior_entries, list):
        raise ValueError('manifest.packs must be a list')
    indexed = {}
    for item in prior_entries:
        if not isinstance(item, dict) or not CODE_RE.fullmatch(str(item.get('id', ''))):
            raise ValueError('invalid existing manifest pack')
        if item['id'] in indexed:
            raise ValueError(f'duplicate manifest pack id: {item["id"]}')
        indexed[item['id']] = item
    old_languages = existing.get('languages', [])
    if not isinstance(old_languages, list):
        raise ValueError('manifest.languages must be a list')
    verify_legacy_files(old_languages, args.output_dir)
    legacy = {item['code']: item for item in old_languages
              if isinstance(item, dict) and isinstance(item.get('code'), str)}
    sources = {}
    for source in sorted(args.source_dir.iterdir()):
        if source.is_file() and source.suffix in ('.sqlite', '.json') and not source.name.endswith('.meta.json'):
            language = source.stem
            if not CODE_RE.fullmatch(language):
                raise ValueError(f'unsafe or invalid language source name: {source.name}')
            if language in sources:
                raise ValueError(f'duplicate input language {language}')
            sources[language] = source
    if args.language:
        requested = set(args.language)
        absent = requested - sources.keys()
        if absent:
            raise FileNotFoundError('missing requested source(s): ' + ', '.join(sorted(absent)))
        sources = {code: source for code, source in sources.items() if code in requested}
    if not sources:
        raise FileNotFoundError('no valid language source (.json/.sqlite); refusing placeholder packs')
    with tempfile.TemporaryDirectory(prefix='store-pack-stage-') as directory:
        stage = Path(directory)
        produced = {}
        for language, source in sorted(sources.items()):
            archive, record = compile_one(source, language, legacy.get(language, {}), stage)
            filename = f'{language}-{VERSION}.pack.gz'
            (stage / filename).write_bytes(archive)
            produced[language] = record
            print(f'{"DRY-RUN " if args.dry_run else "BUILT "}{language}: rows ready, '
                  f'archive={record["archiveSizeBytes"]} bytes sha256={record["sha256"]}')
        indexed.update(produced)
        for item in indexed.values():
            filename = f"{item['id']}-{item.get('version', VERSION)}.pack.gz"
            if Path(filename).name != filename:
                raise ValueError('unsafe new-pack filename')
            archive = (stage / filename).read_bytes() if item['id'] in produced else (args.output_dir / filename).read_bytes()
            if len(archive) != item['archiveSizeBytes'] or digest(archive) != item['sha256']:
                raise ValueError(f'pack hash/size mismatch: {filename}')
            expected_url = f'{REPO_CDN}/{filename}'
            if item.get('archiveUrl') != expected_url:
                raise ValueError(f'pack URL mismatch: {filename}')
        updated = dict(existing)
        updated['schemaVersion'] = SCHEMA_VERSION
        updated['format'] = FORMAT
        updated['legacyCompatibility'] = {
            'format': 'legacy-json-gzip',
            'metadataField': 'languages',
            'packDirectory': 'packs/',
            'schemaVersion': 'legacy',
            'checksumAlgorithm': 'sha256'
        }
        updated['packs'] = [indexed[key] for key in sorted(indexed)]
        manifest_bytes = json.dumps(updated, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False).encode('utf-8') + b'\n'
        if args.dry_run:
            print('DRY-RUN: no packs or manifest modified')
            return
        for language in sorted(produced):
            filename = f'{language}-{VERSION}.pack.gz'
            changed = store_if_different(args.output_dir / filename, (stage / filename).read_bytes())
            print(f'{"UPDATED" if changed else "UNCHANGED"} {filename}')
        changed = store_if_different(args.manifest, manifest_bytes)
        print(f'{"UPDATED" if changed else "UNCHANGED"} {args.manifest}')


def main():
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=repo_root / 'tools' / 'sources')
    parser.add_argument('--output-dir', type=Path, default=repo_root / 'packs')
    parser.add_argument('--manifest', type=Path, default=repo_root / 'manifest.json')
    parser.add_argument('--language', action='append', help='Only compile specified language (repeatable)')
    parser.add_argument('--dry-run', action='store_true', help='Validate and hash without modifying repository files')
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, sqlite3.Error, TypeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
