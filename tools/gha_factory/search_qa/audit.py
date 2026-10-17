"""Read-only bounded SQLite v2 Unicode/FTS5 search QA; never publishes packs."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time

from tools.pack_v2 import pipeline

MAX_ARCHIVE = 40 * 1024 * 1024
MAX_SAMPLES = 12
MAX_SQLITE_BYTES = pipeline.MAX_DATABASE
# FTS glosses aggregate many individually bounded senses/translations. SQLite's
# length limit also applies to complete encoded rows, so use the producer's
# physical database ceiling rather than its per-source-record ceiling.
MAX_SQL_VALUE_BYTES = pipeline.MAX_DATABASE
SQL_SECONDS = 30
HEX = re.compile(r'^[0-9a-f]{64}$')
VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')


class AuditError(ValueError):
    pass


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise AuditError('duplicate JSON metadata key')
        result[key] = value
    return result


def _json(data):
    return json.loads(data, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(AuditError('invalid JSON number')))


def check_sqlite(path, language):
    """Verify a standalone SQLite file as an untrusted read-only QA subject."""
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}', language):
        raise AuditError('invalid language')
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise AuditError('missing/unsafe SQLite file')
    if path.stat().st_size > MAX_SQLITE_BYTES:
        raise AuditError('oversized SQLite file')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1',
                                     uri=True)) as con:
            deadline = time.monotonic() + SQL_SECONDS
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQL_VALUE_BYTES)
            con.execute('PRAGMA cache_size=-4096')
            con.execute('PRAGMA temp_store=FILE')
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            con.execute('PRAGMA busy_timeout=500')
            if con.execute('PRAGMA user_version').fetchone()[0] != 2:
                raise AuditError('SQLite version mismatch')
            if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise AuditError('SQLite integrity failure')
            if con.execute('PRAGMA foreign_key_check').fetchone():
                raise AuditError('SQLite foreign keys failed')
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            if not {'metadata','lexicon','lexicon_fts'}.issubset(tables):
                raise AuditError('mandatory search tables missing')
            metadata = dict(con.execute('SELECT key,value FROM metadata'))
            if (metadata.get('mapping_version') != '2.0.0'
                    or metadata.get('contract_version') != '1.0.0'):
                raise AuditError('SQLite metadata version mismatch')
            total = con.execute('SELECT COUNT(*) FROM lexicon').fetchone()[0]
            if total <= 0:
                raise AuditError('empty lexical corpus is not search-ready')
            if con.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0] != total:
                raise AuditError('FTS5 count mismatch')
            # Count equality does not prove row identity. Check the complete set
            # in both directions without collecting the corpus in Python memory.
            if con.execute(
                'SELECT 1 FROM lexicon l LEFT JOIN lexicon_fts f ON f.rowid=l.rowid '
                'WHERE f.rowid IS NULL LIMIT 1'
            ).fetchone() or con.execute(
                'SELECT 1 FROM lexicon_fts f LEFT JOIN lexicon l ON l.rowid=f.rowid '
                'WHERE l.rowid IS NULL LIMIT 1'
            ).fetchone():
                raise AuditError('FTS5 rowid alignment mismatch')
            # IS NOT also rejects NULL projections, unlike !=.
            if con.execute(
                'SELECT 1 FROM lexicon l JOIN lexicon_fts f ON f.rowid=l.rowid '
                'WHERE f.surface IS NOT l.surface OR '
                'f.language_code IS NOT l.language_code LIMIT 1'
            ).fetchone():
                raise AuditError('FTS5 surface/language mismatch')
            if con.execute('SELECT 1 FROM lexicon WHERE language_code IS NOT ? LIMIT 1',
                           (language,)).fetchone():
                raise AuditError('wrong language in lexicon')
            samples = con.execute('SELECT rowid,surface FROM lexicon WHERE language_code=? '
                                  'ORDER BY id LIMIT ?', (language, MAX_SAMPLES)).fetchall()
            if not samples:
                raise AuditError('language has no searchable lexical records')
            matched, fallback = 0, 0
            for rowid, surface in samples:
                if not isinstance(surface, str) or not surface or '\x00' in surface:
                    raise AuditError('invalid lexical surface')
                fts = con.execute('SELECT surface,language_code FROM lexicon_fts WHERE rowid=?',
                                  (rowid,)).fetchone()
                if fts != (surface, language):
                    raise AuditError('FTS5 rowid/surface/language mismatch')
                # Exact-surface fallback covers short queries independently of FTS5.
                prefix = surface[:min(2, len(surface))]
                escaped = prefix.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
                found = con.execute("SELECT 1 FROM lexicon WHERE rowid=? AND language_code=? "
                                    "AND surface LIKE ? ESCAPE '\\'", (rowid, language, escaped+'%')).fetchone()
                if not found:
                    raise AuditError('short-query fallback failed')
                fallback += 1
                if any(char.isalnum() for char in surface):
                    phrase = '"' + surface.replace('"','""') + '"'
                    found = con.execute('SELECT 1 FROM lexicon_fts WHERE rowid=? AND lexicon_fts MATCH ?',
                                        (rowid, phrase)).fetchone()
                    if not found:
                        raise AuditError('FTS5 match failed')
                    matched += 1
            return {'language':language, 'lexical_count': total,
                    'sampled': len(samples), 'matched_samples':matched,
                    'fallback_samples':fallback, 'qa_status':'PASS_SYNTACTIC_SEARCH_ONLY'}
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise AuditError(f'SQLite search validation failed: {exc}') from exc


def audit_manifest(root, *, shard=0, shards=10):
    """Inspect only declared real production archives, without writing public state."""
    if type(shards) is not int or type(shard) is not int or not 1 <= shards <= 100 or not 0 <= shard < shards:
        raise AuditError('invalid shard plan')
    root = Path(root).resolve()
    manifest = _json((root/'manifest.json').read_bytes())
    ledger = _json((root/'legal/ledger/sources.json').read_bytes())
    entries = manifest.get('languages')
    if not isinstance(entries, list) or len(entries) != 100:
        raise AuditError('100 canonical language registry not found')
    codes = [item.get('code') for item in entries]
    if len(set(codes)) != 100 or any(not isinstance(code,str) for code in codes):
        raise AuditError('ambiguous registered language IDs')
    packs = manifest.get('packs')
    sources = ledger.get('sources')
    if not isinstance(packs,list) or not isinstance(sources,list):
        raise AuditError('malformed manifest or source ledger')
    if not sources and packs:
        raise AuditError('production packs advertised with no approved source')
    ids = set()
    indexed = []
    for pack in packs:
        if not isinstance(pack,dict) or pack.get('id') not in codes or pack['id'] in ids:
            raise AuditError('invalid/duplicate language pack identity')
        ids.add(pack['id'])
        indexed.append(pack)
    if not indexed:
        return {'status':'BLOCKED_SOURCE' if not sources else 'NO_PUBLISHED_PACKS',
                'registered_languages': 100, 'verified_packs':0, 'shard':shard,
                'shards':shards}
    from tools.gha_factory.release import candidate
    verified = []
    for pack in sorted(indexed,key=lambda x:x['id'])[shard::shards]:
        language = pack['id']
        version = pack.get('version')
        digest = pack.get('sha256')
        if not isinstance(version,str) or not VERSION.fullmatch(version) or not isinstance(digest,str) or not HEX.fullmatch(digest):
            raise AuditError('invalid published archive identity/hash')
        path = root/'packs'/f'{language}-{version}.pack.gz'
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARCHIVE:
            raise AuditError('missing, symlink or oversized published archive')
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != digest:
            raise AuditError('published archive checksum mismatch')
        canonical = candidate.inspect_archive(blob,language)
        members = candidate._members(_json(candidate.bounded_gzip(blob)))
        if 'content/content.sqlite' not in members:
            raise AuditError('archive is missing SQLite content')
        with tempfile.TemporaryDirectory(prefix='search-qa-') as td:
            sqlfile = Path(td)/'pack.sqlite'
            sqlfile.write_bytes(members['content/content.sqlite'])
            checks = check_sqlite(sqlfile,language)
        verified.append({'language':language, 'sha256':digest, 'lexical_count':checks['lexical_count'],
                         'sampled':checks['sampled'], 'matched_samples':checks['matched_samples'],
                         'canonical_archive_sha256':canonical['archive_sha256']})
    return {'status':'QA_PASS_NOT_RELEASE_APPROVAL', 'registered_languages':100,
            'verified_packs':len(verified),'shard':shard,'shards':shards,'packs':verified}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=10)
    args = p.parse_args(argv)
    try:
        print(json.dumps(audit_manifest(args.root,shard=args.shard,shards=args.shards),sort_keys=True))
        return 0
    except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status':'FAIL','reason':str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
