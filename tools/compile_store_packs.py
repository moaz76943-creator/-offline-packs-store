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
from pathlib import Path
from urllib.parse import quote

VERSION = '1.0.0'
FORMAT = 'json-gzip-v1'
REPO_CDN = 'https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs'
CODE_RE = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')
DDL = '''
CREATE TABLE lexicon (
 id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
 direction TEXT NOT NULL, fields_json TEXT NOT NULL
);
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
        fields = 'id,surface,part_of_speech,fields_json' + (',direction' if 'direction' in cols else '')
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
            db.execute('INSERT INTO lexicon VALUES (?,?,?,?,?)', (
                required_text(entry.get('id'), 'id'),
                required_text(entry.get('surface'), 'surface'),
                required_text(entry.get('part_of_speech'), 'part_of_speech'),
                row_direction, fields_json(entry.get('fields_json'))))
        for entry in sorted(concepts, key=lambda item: required_text(item.get('concept_id'), 'concept_id')):
            if not isinstance(entry, dict):
                raise ValueError(f'{language}: malformed concept row')
            db.execute('INSERT INTO concepts VALUES (?,?,?,?)', (
                required_text(entry.get('concept_id'), 'concept_id'),
                *[entry.get(key) for key in ('lemma', 'part_of_speech', 'cefr')]))
        db.execute('PRAGMA user_version=1')
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
        'contentSha256': content_hash, 'contentRows': row_count, 'verbRows': verb_count
    })
    envelope = canonical_json({
        'packId': language, 'version': VERSION, 'contractVersion': VERSION,
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
    legacy = {item['code']: item for item in existing.get('languages', [])
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
        updated = dict(existing)
        updated['schemaVersion'] = 2
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
