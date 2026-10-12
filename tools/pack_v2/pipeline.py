"""Public lexical v2 -> SQLite + mandatory three-file gzip envelope.

No network I/O, no private application access. Production requires independently
approved ledger artifacts; synthetic test records require explicit fixture mode.
"""
import base64
from contextlib import closing
import gzip
import hashlib
import io
import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path

CONTRACT = '1.0.0'
MAPPING = '2.0.0'
FORMAT = 'json-gzip-v1'
VERSION = '1.0.0'
MAX_ROW = 64 * 1024
MAX_JSON = 20 * 1024 * 1024
MAX_DATABASE = 80 * 1024 * 1024
MAX_ENVELOPE = 120 * 1024 * 1024
FILES = ('content/content.json', 'content/content.sqlite', 'metadata/pack.json')
SHA_RE = re.compile(r'^[a-f0-9]{64}$')

DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,description TEXT NOT NULL);
CREATE TABLE concepts(concept_id TEXT PRIMARY KEY);
CREATE TABLE lexicon(id TEXT PRIMARY KEY,surface TEXT NOT NULL,part_of_speech TEXT NOT NULL,
 pos TEXT NOT NULL,direction TEXT NOT NULL,language_code TEXT NOT NULL,script TEXT NOT NULL,
 dialect TEXT,sort_key TEXT NOT NULL,cefr_level TEXT,frequency_rank INTEGER,
 fields_json TEXT NOT NULL,source_json TEXT NOT NULL);
CREATE INDEX idx_lexicon_order ON lexicon(language_code,sort_key,id);
CREATE INDEX idx_lexicon_surface ON lexicon(language_code,surface);
CREATE TABLE senses(sense_id TEXT PRIMARY KEY,lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
 concept_id TEXT NOT NULL REFERENCES concepts(concept_id),definition TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE translations(translation_id TEXT PRIMARY KEY,from_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 to_sense_id TEXT NOT NULL REFERENCES senses(sense_id),language_code TEXT NOT NULL,
 text TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE examples(example_id TEXT PRIMARY KEY,sense_id TEXT NOT NULL REFERENCES senses(sense_id),
 lexeme_id TEXT NOT NULL REFERENCES lexicon(id),language_code TEXT NOT NULL,text TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE lexical_relations(relation_id TEXT PRIMARY KEY,from_lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
 to_lexeme_id TEXT NOT NULL REFERENCES lexicon(id),kind TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE grammar(grammar_id TEXT PRIMARY KEY,language_code TEXT NOT NULL,category TEXT NOT NULL,
 title TEXT NOT NULL,payload_json TEXT NOT NULL,source_json TEXT NOT NULL);
CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED,
 tokenize='unicode61 remove_diacritics 0');
CREATE VIEW lexemes AS SELECT id,surface,part_of_speech,direction,fields_json FROM lexicon;
CREATE INDEX idx_senses_lexeme ON senses(lexeme_id,sense_id);
CREATE INDEX idx_examples_sense ON examples(sense_id,example_id);
CREATE INDEX idx_translations_directed ON translations(from_sense_id,language_code,translation_id);
'''


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utf8(value):
    result = compact(value).encode('utf-8')
    if len(result) > MAX_ROW:
        raise ValueError('record exceeds maximum serialized row size')
    return result.decode('utf-8')


def read_json(path):
    if path.stat().st_size > MAX_JSON:
        raise ValueError('source JSON exceeds limit')
    # Reject NaN/Infinity, ambiguous duplicated properties and invalid text.
    def distinct(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError('duplicate JSON key: ' + k)
            obj[k] = v
        return obj
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=distinct,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON numeric constant')))


def source_records(doc):
    for collection in ('lexemes', 'senses', 'translations', 'examples', 'relations'):
        for row in doc[collection]:
            yield row['source']
            if collection == 'lexemes':
                for group in ('articles','classifiers','inflections','conjugations','irregular_forms'):
                    for form in row.get('morphology', {}).get(group, []):
                        yield form.get('source', row['source'])
                for pronunciation in row.get('pronunciations', []):
                    if 'source' in pronunciation:
                        yield pronunciation['source']
                    elif not row['source'].get('fixture_only'):
                        raise ValueError('pronunciation requires explicit approved source')
            if collection == 'examples':
                for tr in row.get('translations', []):
                    yield tr['source']


def validate_document(doc, language, repo_root, fixture_only):
    if not isinstance(doc, dict) or doc.get('contract_version') != CONTRACT:
        raise ValueError('expected lexical contract 1.0.0')
    for key in ('lexemes','senses','translations','examples','relations'):
        if not isinstance(doc.get(key), list):
            raise ValueError('invalid lexical collection: ' + key)
    if not isinstance(doc.get('document_id'), str) or not doc['document_id']:
        raise ValueError('missing document_id')
    if not doc['lexemes'] or not any(row.get('language') == language for row in doc['lexemes']):
        raise ValueError('source language does not match requested pack language')
    # The independently approved public lexical schema is authoritative when present.
    schema_path = repo_root / 'standards/lexical/lexical.schema.json'
    if schema_path.is_file():
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise ValueError('jsonschema>=4 required for approved lexical schema') from exc
        validator = Draft202012Validator(read_json(schema_path))
        violation = next(iter(validator.iter_errors(doc)), None)
        if violation:
            raise ValueError(f'lexical schema violation: {violation.message}')
    elif not fixture_only:
        raise ValueError('approved lexical schema missing')
    ids = set()
    indexed = {}
    fields = {'lexemes':'lexeme_id','senses':'sense_id','translations':'translation_id',
              'examples':'example_id','relations':'relation_id'}
    for coll, field in fields.items():
        indexed[coll] = {}
        for row in doc[coll]:
            rid = row[field]
            if rid in ids:
                raise ValueError('duplicate global record ID')
            ids.add(rid)
            indexed[coll][rid] = row
            utf8(row)
    for row in doc['senses']:
        if row['lexeme_id'] not in indexed['lexemes']:
            raise ValueError('orphan sense')
    for row in doc['translations']:
        if row['from_sense_id'] not in indexed['senses'] or row['to_sense_id'] not in indexed['senses']:
            raise ValueError('orphan translation')
        target = indexed['lexemes'][indexed['senses'][row['to_sense_id']]['lexeme_id']]
        if target['language'] != row['language']:
            raise ValueError('translation target language mismatch')
    for row in doc['examples']:
        if row['sense_id'] not in indexed['senses']:
            raise ValueError('orphan example')
        item = indexed['lexemes'][indexed['senses'][row['sense_id']]['lexeme_id']]
        if item['language'] != row['language']:
            raise ValueError('example language mismatch')
    for row in doc['relations']:
        if row['from_lexeme_id'] not in indexed['lexemes'] or row['to_lexeme_id'] not in indexed['lexemes']:
            raise ValueError('orphan relation')
    sources = list(source_records(doc))
    if not sources:
        raise ValueError('content has no source provenance')
    if fixture_only:
        if not all(s.get('fixture_only') is True and s.get('publication_approved') is False for s in sources):
            raise ValueError('fixture mode only accepts explicitly nonapproved fixture data')
    else:
        approve_sources(sources, repo_root)
    return indexed, sorted({s['source_id'] for s in sources})


def _verified_artifact(repo_root, relative, hash_value):
    if not isinstance(relative, str) or not SHA_RE.fullmatch(str(hash_value)):
        raise ValueError('missing artifact evidence hash/path')
    path = Path(relative)
    root = repo_root.resolve()
    target = (root / path).resolve()
    if path.is_absolute() or '..' in path.parts or not target.is_relative_to(root) or not target.is_file():
        raise ValueError('artifact proof not in approved public repository')
    hasher=hashlib.sha256()
    with target.open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):
            hasher.update(chunk)
    if hasher.hexdigest() != hash_value:
        raise ValueError('source artifact hash mismatch')


def approve_sources(records, repo_root):
    ledger = read_json(repo_root / 'legal/ledger/sources.json')
    if ledger.get('schema_version') != '1.0.0':
        raise ValueError('unsupported licensing ledger')
    listed = {s['source_id']:s for s in ledger.get('sources', [])}
    for rec in records:
        ref = listed.get(rec.get('source_id'))
        if not ref or rec.get('fixture_only') or rec.get('publication_approved') is not True:
            raise ValueError('source not approved in public ledger')
        retrieval = ref.get('retrieval', {})
        license_info = ref.get('license', {})
        if (ref.get('status') != 'APPROVED_FOR_REDISTRIBUTION'
                or not isinstance(ref.get('review'), dict)
                or not ref['review'].get('decision_url', '').startswith('https://')
                or not ref['review'].get('reviewer')):
            raise ValueError('source lacks reviewed redistribution clearance')
        if any((rec.get('origin_url') != ref.get('origin_url'),
                rec.get('publisher') != ref.get('publisher'),
                rec.get('dataset_version') != ref.get('dataset_version'),
                rec.get('retrieval_id') != retrieval.get('identity'),
                rec.get('artifact_sha256') != retrieval.get('sha256'),
                rec.get('license_id') != license_info.get('id'))):
            raise ValueError('record source identity/hash/license differs from ledger')
        if license_info.get('id') not in ('CC0-1.0','CC-BY-SA-4.0','GFDL-1.3-only','PUBLIC-DOMAIN'):
            raise ValueError('unsupported license')
        if not license_info.get('evidence_url','').startswith('https://') or not ref.get('origin_url','').startswith('https://'):
            raise ValueError('missing source-specific license proof')
        _verified_artifact(repo_root, retrieval.get('artifact_path'), retrieval.get('sha256'))
        _verified_artifact(repo_root, license_info.get('evidence_path'), license_info.get('evidence_sha256'))
        if license_info['id'] == 'PUBLIC-DOMAIN' and not all(
                license_info.get('public_domain_proof', {}).get(k) for k in ('jurisdiction','legal_basis','work_date')):
            raise ValueError('public-domain jurisdiction proof required')
        if not ref.get('alterations'):
            raise ValueError('source change disclosure missing')


def grammar_records(sidecar, language, fixture_only, root):
    if sidecar is None:
        return []
    doc = read_json(sidecar)
    if not isinstance(doc, dict) or doc.get('languageCode') != language or doc.get('contract_version') != CONTRACT:
        raise ValueError('grammar sidecar language/contract mismatch')
    entries = doc.get('rules')
    if not isinstance(entries, list):
        raise ValueError('grammar rules must be an array')
    ids = set()
    for item in entries:
        if not isinstance(item, dict) or not all(isinstance(item.get(k),str) and item[k].strip()
                  for k in ('grammar_id','category','title')) or not isinstance(item.get('source'), dict):
            raise ValueError('invalid grammar record')
        if item['grammar_id'] in ids:
            raise ValueError('duplicate grammar ID')
        ids.add(item['grammar_id'])
        utf8(item)
    sources = [item['source'] for item in entries]
    if fixture_only:
        if not all(s.get('fixture_only') is True and s.get('publication_approved') is False for s in sources):
            raise ValueError('nonfixture grammar in fixture mode')
    elif sources:
        approve_sources(sources, root)
    return sorted(entries, key=lambda row: row['grammar_id'])


def make_database(doc, language, grammar, path):
    lexemes = {r['lexeme_id']:r for r in doc['lexemes']}
    senses = {r['sense_id']:r for r in doc['senses']}
    definitions, outbound = {}, {}
    for r in doc['senses']:
        definitions.setdefault(r['lexeme_id'], []).append(r['definition'])
    for r in doc['translations']:
        outbound.setdefault(senses[r['from_sense_id']]['lexeme_id'], []).append(r['text'])
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA page_size=4096')
        db.executescript(DDL)
        for k,v in (('contract_version',CONTRACT),('mapping_version',MAPPING),
                    ('document_id',doc['document_id']),('language_code',language)):
            db.execute('INSERT INTO metadata VALUES (?,?)',(k,v))
        db.execute('INSERT INTO schema_migrations VALUES (?,?)',(MAPPING,'public v2 lexical mapping'))
        for cid in sorted({r['concept_id'] for r in doc['senses']}):
            db.execute('INSERT INTO concepts VALUES (?)',(cid,))
        for rid in sorted(lexemes, key=lambda k:(lexemes[k]['language'],
                unicodedata.normalize('NFKC',lexemes[k]['surface']).casefold(),k)):
            r=lexemes[rid]
            levels=[lvl['level_id'] for s in doc['senses'] if s['lexeme_id']==rid
                    for lvl in s.get('levels',[]) if lvl['framework_id']=='cefr']
            cefr = levels[0] if levels and len(set(levels))==1 else None
            db.execute('''INSERT INTO lexicon(id,surface,part_of_speech,pos,direction,language_code,
               script,dialect,sort_key,cefr_level,frequency_rank,fields_json,source_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (rid,r['surface'],r['pos'],r['pos'],r['direction'],
               r['language'],r['script'],r.get('dialect'),unicodedata.normalize('NFKC',r['surface']).casefold(),
               cefr,None,utf8(r),utf8(r['source'])))
            rowid=db.execute('SELECT rowid FROM lexicon WHERE id=?',(rid,)).fetchone()[0]
            gloss=' '.join(sorted(set(definitions.get(rid,[])+outbound.get(rid,[]))))
            db.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES(?,?,?,?,?)',
                       (rowid,r['surface'],r['lemma'],gloss,r['language']))
        for sid in sorted(senses):
            r=senses[sid]
            db.execute('INSERT INTO senses VALUES(?,?,?,?,?)',(sid,r['lexeme_id'],r['concept_id'],r['definition'],utf8(r)))
        for r in sorted(doc['translations'],key=lambda x:x['translation_id']):
            db.execute('INSERT INTO translations VALUES(?,?,?,?,?,?)',(r['translation_id'],r['from_sense_id'],
                      r['to_sense_id'],r['language'],r['text'],utf8(r)))
        for r in sorted(doc['examples'],key=lambda x:x['example_id']):
            db.execute('INSERT INTO examples VALUES(?,?,?,?,?,?)',(r['example_id'],r['sense_id'],
                       senses[r['sense_id']]['lexeme_id'],r['language'],r['text'],utf8(r)))
        for r in sorted(doc['relations'],key=lambda x:x['relation_id']):
            db.execute('INSERT INTO lexical_relations VALUES(?,?,?,?,?)',(r['relation_id'],r['from_lexeme_id'],
                      r['to_lexeme_id'],r['kind'],utf8(r)))
        for r in grammar:
            db.execute('INSERT INTO grammar VALUES(?,?,?,?,?,?)',(r['grammar_id'],language,
                       r['category'],r['title'],utf8(r),utf8(r['source'])))
        db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")
        db.execute('PRAGMA user_version=2')
        db.commit()
        db.execute('VACUUM')
    if path.stat().st_size > MAX_DATABASE:
        raise ValueError('SQLite exceeds decompressed database size limit')
    return check_sqlite(path, language)


def check_sqlite(path, language):
    uri='file:'+str(path.resolve())+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('SQLite integrity_check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite foreign_key_check failed')
        if db.execute('PRAGMA user_version').fetchone()[0]!=2:
            raise ValueError('SQLite user version mismatch')
        meta=dict(db.execute('SELECT key,value FROM metadata'))
        if meta.get('mapping_version')!=MAPPING or meta.get('contract_version')!=CONTRACT or meta.get('language_code')!=language:
            raise ValueError('SQLite metadata mismatch')
        tables=('lexicon','concepts','senses','translations','examples','lexical_relations','grammar')
        counts={k:db.execute(f'SELECT COUNT(*) FROM {k}').fetchone()[0] for k in tables}
        if not counts['lexicon'] or not db.execute('SELECT 1 FROM lexicon WHERE language_code=?',(language,)).fetchone():
            raise ValueError('missing target-language lexicon')
        if db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0]!=counts['lexicon']:
            raise ValueError('FTS5 row count mismatch')
        # Actual MATCH is mandatory, not mere sqlite_master table existence.
        word=db.execute('SELECT surface FROM lexicon WHERE language_code=? ORDER BY id LIMIT 1',(language,)).fetchone()[0]
        query='"'+word.replace('"','""')+'"'
        if not db.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1',(query,)).fetchone():
            raise ValueError('FTS5 MATCH smoke test failed')
    return counts


def check_envelope(payload, language):
    if len(payload)>MAX_ENVELOPE:
        raise ValueError('decompressed archive limit exceeded')
    envelope=json.loads(payload)
    if envelope.get('packId')!=language or envelope.get('schemaVersion')!=MAPPING or envelope.get('format')!=FORMAT:
        raise ValueError('envelope identity/version mismatch')
    rows=envelope.get('files')
    if not isinstance(rows,list) or len(rows)!=len(FILES) or {i.get('path') for i in rows}!=set(FILES):
        raise ValueError('mandatory envelope file missing/duplicate')
    content={}
    for item in rows:
        raw=base64.b64decode(item['contentBase64'],validate=True)
        if len(raw)>MAX_DATABASE:
            raise ValueError('envelope member exceeds size limit')
        content[item['path']]=raw
    manifest=json.loads(content['metadata/pack.json'])
    info=json.loads(content['content/content.json'])
    sqlite_bytes=content['content/content.sqlite']
    if (manifest['languageCode']!=language or info['languageCode']!=language
        or manifest['contentSha256']!=sha(sqlite_bytes)
        or info['sqliteSha256']!=sha(sqlite_bytes)
        or manifest['contentMetadataSha256']!=sha(content['content/content.json'])
        or manifest['contentRows']!=info['tableCounts']['lexicon']):
        raise ValueError('envelope hashes/content metadata mismatch')
    with tempfile.TemporaryDirectory(prefix='pack-verify-') as td:
        db=Path(td)/'content.sqlite'
        db.write_bytes(sqlite_bytes)
        counts=check_sqlite(db, language)
        if counts!=info['tableCounts']:
            raise ValueError('envelope SQLite table counts mismatch')
    return content


def compile_pack(src, language, workspace, repo_root, fixture_only=False):
    if src.suffix!='.json' or src.name.endswith('.grammar.json'):
        raise ValueError('requires canonical lexical JSON; unverified legacy SQLite sources cannot be republished')
    doc=read_json(src)
    _, sources=validate_document(doc,language,repo_root,fixture_only)
    sidecar=src.with_name(language+'.grammar.json')
    grammar=grammar_records(sidecar if sidecar.is_file() else None,language,fixture_only,repo_root)
    sources=sorted(set(sources)|{r['source']['source_id'] for r in grammar})
    db_path=workspace/(language+'.sqlite')
    counts=make_database(doc,language,grammar,db_path)
    data=db_path.read_bytes()
    info={
       'contractVersion':CONTRACT,'schemaVersion':MAPPING,'documentId':doc['document_id'],
       'languageCode':language,'languagesPresent':sorted({r['language'] for r in doc['lexemes']}),
       'tableCounts':counts,'sqliteSha256':sha(data),'sourceIds':sources,
       'fixtureOnly':fixture_only,
    }
    info_bytes=(compact(info)+'\n').encode()
    manifest={
        'packId':language,'languageCode':language,'version':VERSION,'contractVersion':CONTRACT,
        'schemaVersion':MAPPING,'format':FORMAT,'contentRows':counts['lexicon'],
        'contentSha256':sha(data),'contentMetadataSha256':sha(info_bytes),
        'sourceIds':sources,'fixtureOnly':fixture_only,
    }
    meta_bytes=(compact(manifest)+'\n').encode()
    content={'content/content.json':info_bytes,'content/content.sqlite':data,'metadata/pack.json':meta_bytes}
    envelope={'packId':language,'version':VERSION,'contractVersion':CONTRACT,
              'schemaVersion':MAPPING,'format':FORMAT,
              'files':[{'path':p,'contentBase64':base64.b64encode(content[p]).decode('ascii')} for p in FILES]}
    raw=(compact(envelope)+'\n').encode()
    check_envelope(raw,language)
    sink=io.BytesIO()
    with gzip.GzipFile(fileobj=sink,mode='wb',filename='',mtime=0,compresslevel=9) as zip_file:
        zip_file.write(raw)
    archive=sink.getvalue()
    item={
      'id':language,'languageCode':language,'displayName':language,'version':VERSION,
      'contractVersion':CONTRACT,'schemaVersion':MAPPING,'format':FORMAT,
      'bundleFormat':FORMAT,'sha256':sha(archive),'contentSha256':sha(data),
      'archiveSizeBytes':len(archive),'installedSizeBytes':sum(map(len,content.values())),
    }
    return archive,item
