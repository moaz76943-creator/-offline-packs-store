#!/usr/bin/env python3
"""Read-only canonical SQLite v2/FTS5 evidence; never rebuild published bytes.

This QA receipt is NOT content admission or release authorization.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

SHA = re.compile(r'^[a-f0-9]{64}$')
MAX_DB = 80 * 1024 * 1024

class IndexBlocked(ValueError):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(65536), b''):
            h.update(data)
    return h.hexdigest()


def schema(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


def inspect(path, language, expected_sha256, *, canonical_ddl=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DB:
        raise IndexBlocked('missing, escaping or oversized SQLite candidate')
    if not SHA.fullmatch(str(expected_sha256)) or digest(path) != expected_sha256:
        raise IndexBlocked('SQLite artifact SHA-256 mismatch')
    if canonical_ddl is None:
        from tools.pack_v2.pipeline import DDL as canonical_ddl
    try:
        with closing(sqlite3.connect(':memory:')) as reference:
            reference.executescript(canonical_ddl)
            expected_schema = schema(reference)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            deadline = time.monotonic() + 20
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA query_only=ON')
            if schema(db) != expected_schema:
                raise IndexBlocked('FTS5/schema differs from canonical SQLite v2 producer')
            if db.execute('PRAGMA user_version').fetchone()[0] != 2:
                raise IndexBlocked('SQLite user_version differs from 2')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise IndexBlocked('SQLite integrity failure')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise IndexBlocked('SQLite foreign key failure')
            meta = dict(db.execute('SELECT key,value FROM metadata'))
            if (meta.get('contract_version') != '1.0.0'
                    or meta.get('mapping_version') != '2.0.0'
                    or meta.get('language_code') != language):
                raise IndexBlocked('SQLite contract or pack language mismatch')
            count = db.execute('SELECT count(*) FROM lexicon').fetchone()[0]
            if count <= 0 or db.execute('SELECT count(*) FROM lexicon_fts').fetchone()[0] != count:
                raise IndexBlocked('empty or incorrect FTS5 row count')
            wrong = db.execute('''SELECT count(*) FROM lexicon l JOIN lexicon_fts f
                                  ON l.rowid=f.rowid WHERE l.surface!=f.surface
                                  OR l.language_code!=f.language_code''').fetchone()[0]
            if wrong or db.execute('SELECT 1 FROM lexicon WHERE language_code=? LIMIT 1', (language,)).fetchone() is None:
                raise IndexBlocked('FTS5-to-lexicon surface or language mismatch')
            samples = db.execute('''SELECT l.id,l.surface,l.rowid FROM lexicon l
                                    WHERE l.language_code=? ORDER BY l.id LIMIT 10''', (language,)).fetchall()
            matches = 0
            for lexeme_id, surface, rowid in samples:
                if not isinstance(surface,str) or not surface.strip():
                    raise IndexBlocked('invalid lexical surface')
                query = '"' + surface.replace('"','""') + '"'
                match = db.execute('SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ? AND rowid=?',
                                   (query,rowid)).fetchone()
                if match is None:
                    raise IndexBlocked('FTS5 exact MATCH failed for ' + str(lexeme_id))
                matches += 1
    except sqlite3.DatabaseError as exc:
        raise IndexBlocked('malformed SQLite or FTS5 input') from exc
    if digest(path) != expected_sha256:
        raise IndexBlocked('SQLite candidate mutated during read-only inspection')
    return {'status':'QA_ONLY_NOT_PUBLICATION', 'language':language,
            'sqlite_sha256':expected_sha256, 'actual_lexeme_count':count,
            'fts5_exact_matches':matches,'original_pack_mutated':False,
            'optional_diacritic_matching_proven':False,
            'source_rights_verified':False,'publication_approved':False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sqlite',type=Path,required=True)
    p.add_argument('--language',required=True)
    p.add_argument('--sha256',required=True)
    args=p.parse_args(argv)
    try:
        report=inspect(args.sqlite,args.language,args.sha256)
        print(json.dumps(report,sort_keys=True))
        return 0
    except (IndexBlocked,OSError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'publication_approved':False}))
        return 2


if __name__=='__main__':
    sys.exit(main())
