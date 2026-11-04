"""Bounded fail-closed conformance adapter. No compiler, queue or release mutations."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unicodedata

from tools.pack_v2 import pipeline
from tools.gha_factory.release import candidate

MAX_METADATA = 1024 * 1024
MAX_ROWS = 1000000
MAX_SOURCES = 1024
SQL_SECONDS = 30
VERSION = '1.0.0'


class ConformanceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ': ' + message)


def fail(code, message):
    raise ConformanceError(code, message)


def strict_json(raw, limit=MAX_METADATA):
    if isinstance(raw, str):
        try:
            raw = raw.encode('utf-8', errors='strict')
        except UnicodeError:
            fail('UNICODE_INVALID', 'invalid Unicode scalar')
    if not isinstance(raw, bytes) or len(raw) > limit:
        fail('ARCHIVE_OVERSIZED', 'JSON size limit')
    def distinct(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                fail('INVALID_RECEIPT', 'duplicate JSON key')
            obj[key] = value
        return obj
    def constant(_):
        fail('INVALID_RECEIPT', 'nonfinite JSON number')
    try:
        obj = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=distinct,
                         parse_constant=constant)
        # Check escaped lone surrogates and overflowed exponent floats too.
        pending = [(obj, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                fail('INVALID_RECEIPT', 'JSON nesting limit')
            if isinstance(item, dict):
                pending.extend((k, depth+1) for k in item)
                pending.extend((v, depth+1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth+1) for v in item)
            elif isinstance(item, str):
                item.encode('utf-8', errors='strict')
                if any(ord(c) < 32 and c not in '\t\n\r' for c in item):
                    fail('UNICODE_INVALID', 'forbidden control character')
            elif isinstance(item, float) and not math.isfinite(item):
                constant(None)
        return obj
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        fail('UNICODE_INVALID' if isinstance(exc, UnicodeError) else 'INVALID_RECEIPT',
             'invalid JSON/UTF-8')


def object_json(raw, limit=MAX_METADATA):
    obj = strict_json(raw, limit)
    if not isinstance(obj, dict):
        fail('INVALID_RECEIPT', 'object required')
    return obj


def canonical_schema(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


def registered(root):
    registry = object_json((root/'catalog/language_registry.v1.json').read_bytes())
    # Reuse exactly the current registry identities, independently of manifest claims.
    codes = [r['id'] for r in registry['languages']]
    if len(codes) != 100 or len(set(codes)) != 100:
        fail('LANGUAGE_ID_MISMATCH', 'canonical 100-language registry')
    return set(codes)


def database_checks(data, language, info, root, fixture):
    if len(data) > pipeline.MAX_DATABASE or not data.startswith(b'SQLite format 3\x00'):
        fail('SQLITE_CORRUPT', 'SQLite header/size')
    counts = info['tableCounts']
    if sum(counts.values()) > MAX_ROWS:
        fail('ARCHIVE_OVERSIZED', 'record count limit')
    from jsonschema import Draft202012Validator
    schema = object_json((root/'standards/lexical/lexical.schema.json').read_bytes())
    validators = {key:Draft202012Validator({'$ref':'#/$defs/'+key,'$defs':schema['$defs']})
                  for key in ('lexeme','sense','translation','example','relation','source')}
    def record_schema(payload, kind):
        if next(validators[kind].iter_errors(payload),None) is not None:
            fail('PROVENANCE_MISSING' if kind == 'source' else 'INVALID_RECEIPT',kind+' canonical payload schema')
    sources = {}
    language_ids = registered(root)
    registry = object_json((root/'catalog/language_registry.v1.json').read_bytes())
    language_specs = {r['id']:r for r in registry['languages']}
    def provenance(src):
        if not isinstance(src, dict) or not isinstance(src.get('source_id'), str):
            fail('PROVENANCE_MISSING', 'record source proof missing')
        if fixture and (src.get('fixture_only') is not True or src.get('publication_approved') is not False):
            fail('SOURCE_NOT_APPROVED', 'fixture source promoted')
        record_schema(src,'source')
        key = pipeline.compact(src)
        if len(sources) >= MAX_SOURCES and key not in sources:
            fail('ARCHIVE_OVERSIZED', 'source evidence identity limit')
        sources[key] = src
    with tempfile.TemporaryDirectory(prefix='strict-conformance-') as td:
        path = Path(td)/'candidate.sqlite'
        path.write_bytes(data)
        with closing(sqlite3.connect(path)) as db, closing(sqlite3.connect(':memory:')) as ref:
            db.row_factory = sqlite3.Row
            deadline = time.monotonic()+SQL_SECONDS
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, pipeline.MAX_ROW*4)
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('PRAGMA cache_size=-4096')
            db.execute('PRAGMA busy_timeout=500')
            ref.executescript(pipeline.DDL)
            # Convert Rows to tuples for equality. Reject extra triggers/views/tables too.
            if [tuple(r) for r in canonical_schema(db)] != canonical_schema(ref):
                fail('SQLITE_SCHEMA_MISMATCH', 'canonical producer DDL differs')
            if db.execute('PRAGMA user_version').fetchone()[0] != 2:
                fail('SQLITE_SCHEMA_MISMATCH', 'user_version')
            if [tuple(r) for r in db.execute('SELECT version,description FROM schema_migrations')] != [(pipeline.MAPPING,'public v2 lexical mapping')]:
                fail('SQLITE_SCHEMA_MISMATCH', 'unsupported schema migration')
            meta = dict(db.execute('SELECT key,value FROM metadata'))
            if meta != {'contract_version':pipeline.CONTRACT,'mapping_version':pipeline.MAPPING,
                        'document_id':info.get('documentId'),'language_code':language}:
                fail('LANGUAGE_ID_MISMATCH', 'SQLite metadata/document identity')
            if [tuple(r) for r in db.execute('PRAGMA integrity_check')] != [('ok',)]:
                fail('SQLITE_CORRUPT', 'integrity_check')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                fail('SQLITE_CORRUPT', 'foreign_key_check')
            actual = {t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in counts}
            if actual != counts or not actual['lexicon'] or not actual['senses']:
                fail('INVALID_RECEIPT', 'actual row counts/empty corpus')
            if db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0] != actual['lexicon']:
                fail('FTS5_CORRUPT', 'FTS5 count')
            # SQLite enforces uniqueness only within each table. The stable
            # identifier namespace includes concept and grammar records too.
            id_union = ' UNION ALL '.join('SELECT '+col+' AS stable_id FROM '+table
                for table,col in [('concepts','concept_id'),('lexicon','id'),
                                  ('senses','sense_id'),('translations','translation_id'),
                                  ('examples','example_id'),('lexical_relations','relation_id'),
                                  ('grammar','grammar_id')])
            if db.execute('SELECT stable_id FROM ('+id_union+') GROUP BY stable_id HAVING COUNT(*)>1 LIMIT 1').fetchone():
                fail('INVALID_RECEIPT','duplicate global stable ID')
            # All producer concepts come from recorded senses. FK checks alone
            # cannot catch extra concepts when the manifest counts are forged.
            if actual['concepts'] != db.execute(
                    'SELECT COUNT(DISTINCT concept_id) FROM senses').fetchone()[0]:
                fail('INVALID_RECEIPT', 'unreferenced concept differs from canonical producer')
            # Internal FTS5 content/index verification runs ONLY in this disposable copy.
            db.execute("INSERT INTO lexicon_fts(lexicon_fts,rank) VALUES('integrity-check',1)")
            for row in db.execute('SELECT rowid,* FROM lexicon ORDER BY rowid'):
                payload = object_json(row['fields_json'], pipeline.MAX_ROW)
                src = object_json(row['source_json'], pipeline.MAX_ROW)
                if src != payload.get('source'):
                    fail('PROVENANCE_MISSING', 'source projection mismatch')
                provenance(src)
                record_schema(payload,'lexeme')
                stub = {'lexemes':[payload],'senses':[],'translations':[],'examples':[],'relations':[]}
                for source in pipeline.source_records(stub):
                    provenance(source)
                fields = {'id':'lexeme_id','surface':'surface','language_code':'language',
                          'part_of_speech':'pos','pos':'pos','direction':'direction','script':'script'}
                if any(row[col] != payload.get(key) for col,key in fields.items()):
                    fail('LANGUAGE_ID_MISMATCH', 'lexeme payload projection mismatch')
                if row['language_code'] not in language_ids:
                    fail('LANGUAGE_ID_MISMATCH', 'unregistered lexical language')
                if (row['script'] not in language_specs[row['language_code']]['scripts']
                        or row['direction'] != registry['scripts'][row['script']]['direction']):
                    fail('LANGUAGE_ID_MISMATCH','registered script/direction mismatch')
                if row['sort_key'] != unicodedata.normalize('NFKC',row['surface']).casefold():
                    fail('SQLITE_SCHEMA_MISMATCH', 'search sort key projection')
                fts = db.execute('SELECT surface,lemma,gloss,language_code FROM lexicon_fts WHERE rowid=?', (row['rowid'],)).fetchone()
                # Stream per-lexeme definitions through the mandatory index (no corpus RAM).
                definitions = {r[0] for r in db.execute('SELECT definition FROM senses WHERE lexeme_id=?',(row['id'],))}
                outbound = {r[0] for r in db.execute('SELECT t.text FROM senses s JOIN translations t ON t.from_sense_id=s.sense_id WHERE s.lexeme_id=?',(row['id'],))}
                expected = (row['surface'],payload.get('lemma'),' '.join(sorted(definitions|outbound)),row['language_code'])
                if fts is None or tuple(fts) != expected:
                    fail('FTS5_CORRUPT', 'FTS5 rowid/surface/lemma/gloss/language mismatch')
            projections = {
                'senses':{'sense_id':'sense_id','lexeme_id':'lexeme_id','concept_id':'concept_id','definition':'definition'},
                'translations':{'translation_id':'translation_id','from_sense_id':'from_sense_id','to_sense_id':'to_sense_id','language_code':'language','text':'text'},
                'examples':{'example_id':'example_id','sense_id':'sense_id','language_code':'language','text':'text'},
                'lexical_relations':{'relation_id':'relation_id','from_lexeme_id':'from_lexeme_id','to_lexeme_id':'to_lexeme_id','kind':'kind'},
                'grammar':{'grammar_id':'grammar_id','category':'category','title':'title'},
            }
            sense_links = {r[0]: (r[1], r[2]) for r in db.execute('SELECT s.sense_id, s.lexeme_id, l.language_code FROM senses s JOIN lexicon l ON l.id=s.lexeme_id')}
            for table, fields in projections.items():
                for row in db.execute('SELECT * FROM '+table):
                    payload = object_json(row['payload_json'],pipeline.MAX_ROW)
                    if any(row[col] != payload.get(key) for col,key in fields.items()):
                        fail('INVALID_RECEIPT', table+' payload projection')
                    provenance(payload.get('source'))
                    if table != 'grammar':
                        record_schema(payload,{'senses':'sense','translations':'translation','examples':'example','lexical_relations':'relation'}[table])
                    if table == 'grammar':
                        if row['language_code'] != language or object_json(row['source_json'],pipeline.MAX_ROW) != payload['source']:
                            fail('LANGUAGE_ID_MISMATCH', 'grammar identity/source')
                    if table == 'examples':
                        link = sense_links.get(row['sense_id'])
                        if link is None or link != (row['lexeme_id'],row['language_code']):
                            fail('LANGUAGE_ID_MISMATCH', 'example sense language/reference')
                        for tr in payload.get('translations',[]):
                            provenance(tr.get('source'))
                    if table == 'translations':
                        target_link = sense_links.get(row['to_sense_id'])
                        if target_link is None or target_link[1] != row['language_code']:
                            fail('LANGUAGE_ID_MISMATCH', 'directed target language')
            present = sorted({r[0] for r in db.execute('SELECT DISTINCT language_code FROM lexicon')})
            if present != info.get('languagesPresent') or language not in present:
                fail('LANGUAGE_ID_MISMATCH', 'languagesPresent differs from actual rows')
    if sorted({s['source_id'] for s in sources.values()}) != info['sourceIds']:
        fail('PROVENANCE_MISSING', 'source IDs differ from actual record proofs')
    if not fixture:
        # Existing Route 07 / Route 05 rights+immutable artifact checks remain authoritative.
        try:
            pipeline.approve_sources(list(sources.values()),root)
        except (ValueError, OSError) as exc:
            fail('SOURCE_NOT_APPROVED', str(exc))
    return actual


def inspect(blob, language, *, root, allow_fixture=False, expected_sha256=None):
    root = Path(root).resolve()
    if language not in registered(root):
        fail('LANGUAGE_ID_MISMATCH', 'unregistered candidate')
    if expected_sha256 is not None and pipeline.sha(blob) != expected_sha256:
        fail('SOURCE_HASH_MISMATCH', 'candidate archive hash')
    raw = candidate.bounded_gzip(blob)
    env = object_json(raw,pipeline.MAX_ENVELOPE)
    if set(env) != {'packId','version','contractVersion','schemaVersion','format','files'}:
        fail('INVALID_RECEIPT', 'unexpected envelope properties')
    members = candidate._members(env)
    for entry in env['files']:
        if set(entry) != {'path','contentBase64'}:
            fail('INVALID_RECEIPT', 'unexpected envelope entry properties')
        data = members[entry['path']]
        if base64.b64encode(data).decode('ascii') != entry['contentBase64']:
            fail('INVALID_RECEIPT', 'noncanonical base64')
    info = object_json(members['content/content.json'])
    meta = object_json(members['metadata/pack.json'])
    if (info.get('contractVersion') != pipeline.CONTRACT or meta.get('contractVersion') != pipeline.CONTRACT
            or meta.get('format') != pipeline.FORMAT):
        fail('SQLITE_SCHEMA_MISMATCH', 'metadata contract/format')
    fixture = info.get('fixtureOnly')
    counts = info.get('tableCounts')
    if type(fixture) is not bool or (fixture and not allow_fixture):
        fail('SOURCE_NOT_APPROVED','synthetic fixture forbidden for production candidate')
    if (not isinstance(counts,dict) or set(counts) != {'concepts','lexicon','senses','translations','examples','lexical_relations','grammar'}
            or any(type(v) is not int or v < 0 for v in counts.values())):
        fail('INVALID_RECEIPT','actual count contract')
    try:
        counts = database_checks(members['content/content.sqlite'],language,info,root,fixture)
    except sqlite3.Error as exc:
        fail('WORKER_TIMEOUT' if 'interrupted' in str(exc) else 'SQLITE_CORRUPT',str(exc))
    report = candidate.inspect_archive(blob,language,allow_fixture=allow_fixture)
    report.update(conformance_version=VERSION, actual_counts=counts,
                  sqlite_bytes=len(members['content/content.sqlite']),
                  compiler_ddl_sha256=pipeline.sha(pipeline.DDL.encode()),
                  status='FIXTURE_QUARANTINED' if report['fixture_only'] else 'QUARANTINED_PENDING_RELEASE_GATES',
                  signature_status='NOT_RUN',publication_approved=False,semantic_accuracy='NOT_VERIFIED')
    return report


def audit(root):
    root = Path(root).resolve()
    codes = registered(root)
    ledger = object_json((root/'legal/ledger/sources.json').read_bytes())
    manifest = object_json((root/'manifest.json').read_bytes())
    if {r['code'] for r in manifest['languages']} != codes:
        fail('LANGUAGE_ID_MISMATCH','manifest identities differ from registry')
    approved = [s for s in ledger['sources'] if s.get('status') == 'APPROVED_FOR_REDISTRIBUTION']
    if not approved and manifest.get('packs'):
        fail('SOURCE_NOT_APPROVED','published references without approved source')
    return {'status':'BLOCKED_SOURCE' if not approved else 'BLOCKED_DEPENDENCY',
            'registered_languages':len(codes),'approved_ledger_sources':len(approved),
            'actual_packs_verified':0,'publication_approved':False,
            'queue_dependency':'GHA-02 v1 has no candidate QA task type',
            'language_status':{c:'REGISTERED_ONLY' for c in sorted(codes)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('.'))
    ap.add_argument('--archive',type=Path)
    ap.add_argument('--language')
    ap.add_argument('--sha256')
    args = ap.parse_args(argv)
    try:
        if args.archive:
            if not args.language or not args.sha256 or args.archive.is_symlink() or args.archive.stat().st_size > candidate.MAX_ARCHIVE:
                fail('INVALID_RECEIPT','archive identity/hash/size required')
            result = inspect(args.archive.read_bytes(),args.language,root=args.root,expected_sha256=args.sha256)
        else:
            result = audit(args.root)
        print(pipeline.compact(result))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(pipeline.compact({'status':'FAIL','error_code':getattr(exc,'code','UNKNOWN_FAILURE'),
                               'reason':str(exc),'publication_approved':False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
