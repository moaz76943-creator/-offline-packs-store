"""Offline immutable-snapshot adapter: bounded streaming, atomic disk checkpoints.

Does not retrieve sources, write GHA-02 queues, compile SQLite packs or publish.
"""
import argparse
import errno
import fcntl
import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from tools.gha_factory.admission.pipeline import route05_source, checked_file, digest_file, AdmissionError
from catalog.validate_registry import validate as registry_validate
from .normalize import VERSION, canonical, extract, partition, Reject, stable

MAX_LINE=1024*1024
MAX_EXPANDED=16*1024**3
MAX_SOURCE=8*1024**3


class Blocked(ValueError):
    pass


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise Reject('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def constant(_):raise Reject('NONFINITE_JSON')
    def finite(value):
        number=float(value)
        if not math.isfinite(number):raise Reject('NONFINITE_JSON')
        return number
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant,parse_float=finite)
    except Reject:raise
    except (ValueError,RecursionError) as exc:raise Reject('INVALID_JSON') from exc


def load(path):
    if path.stat().st_size>4*1024*1024:raise Blocked('OVERSIZED_METADATA')
    return strict_json(path.read_bytes())


@contextmanager
def stream(path):
    if path.suffix not in ('.jsonl','.gz'):raise Blocked('UNSUPPORTED_FORMAT')
    with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as handle:
        yield handle


def hash_fd(fd):
    digest=hashlib.sha256();offset=0
    while True:
        chunk=os.pread(fd,1024*1024,offset)
        if not chunk:break
        digest.update(chunk);offset+=len(chunk)
    return digest.hexdigest()


@contextmanager
def bound_bytes(path,expected_sha):
    """Keep the validated inode open. A later path replacement is not this artifact."""
    if path.is_symlink() or path.suffix not in ('.jsonl','.gz') or not isinstance(expected_sha,str):
        raise Blocked('BLOCKED_SOURCE: unsafe artifact')
    try:
        raw=os.fdopen(os.open(os.fspath(path),os.O_RDONLY|os.O_NOFOLLOW),'rb')
    except OSError as exc:
        if exc.errno==errno.ELOOP or path.is_symlink():
            raise Blocked('BLOCKED_SOURCE: unsafe artifact') from exc
        raise
    try:
        info=os.fstat(raw.fileno())
        if not stat.S_ISREG(info.st_mode) or hash_fd(raw.fileno())!=expected_sha:
            raise Blocked('BLOCKED_SOURCE: artifact hash mismatch')
        raw.seek(0)
        handle=gzip.GzipFile(fileobj=raw) if path.suffix=='.gz' else raw
        def guard():
            if hash_fd(raw.fileno())!=expected_sha:
                raise Blocked('BLOCKED_SOURCE: artifact bytes differ from validated snapshot')
        try:
            yield handle,guard
        finally:
            if handle is not raw:handle.close()
    finally:
        raw.close()


def lines(handle,max_expanded=MAX_EXPANDED):
    """Oversized line is drained in bounded chunks and rejected as exactly ONE row."""
    expanded=0
    while True:
        raw=handle.readline(MAX_LINE+1)
        if not raw:break
        expanded+=len(raw);h=hashlib.sha256(raw);oversized=len(raw)>MAX_LINE
        while not raw.endswith(b'\n') and len(raw)==MAX_LINE+1:
            chunk=handle.readline(MAX_LINE+1)
            if not chunk:break
            oversized=True;expanded+=len(chunk);h.update(chunk);raw=chunk
            if expanded>max_expanded:raise Blocked('EXPANSION_LIMIT')
        if expanded>max_expanded:raise Blocked('EXPANSION_LIMIT')
        yield None if oversized else raw,h.hexdigest()


def approved(root,source_id,language):
    try:
        ledger=load(root/'legal/ledger/sources.json')
        sources=[s for s in ledger['sources'] if s.get('source_id')==source_id]
        if len(sources)!=1:raise Blocked('BLOCKED_SOURCE: missing unique admission')
        source=sources[0];relative=source['retrieval']['artifact_path']
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>MAX_SOURCE:
            raise Blocked('BLOCKED_SOURCE: invalid/oversized artifact')
        route05_source(root,source_id,source['dataset_version'],path,'wiktextract-jsonl')
        review=source['review']
        checked_file(root,review.get('evidence_path'),review.get('evidence_sha256'),'reviewer evidence')
        registry=load(root/'catalog/language_registry.v1.json')
        readiness=load(root/'catalog/content_readiness.v1.json')
        if registry_validate(registry,readiness):raise Blocked('INVALID_REGISTRY')
        if language not in {r['id'] for r in registry['languages']}:raise Blocked('UNKNOWN_LANGUAGE')
        return source,path,registry
    except (AdmissionError,OSError,KeyError,TypeError,ValueError) as exc:
        raise Blocked('BLOCKED_SOURCE: '+str(exc)) from exc


def snapshot(repo_root,source_id,language,max_expanded=MAX_EXPANDED):
    root=Path(repo_root).resolve()
    if type(max_expanded) is not int or not 1<=max_expanded<=MAX_EXPANDED:
        raise Blocked('INVALID_EXPANSION_BOUND')
    source,path,_=approved(root,source_id,language)
    rows=0
    try:
        # Hash and row count share one descriptor so a swapped path cannot be verified.
        with bound_bytes(path,source['retrieval']['sha256']) as (handle,guard):
            for _,_ in lines(handle,max_expanded):rows+=1
            if rows<1:raise Blocked('REJECTED_RECORD: empty source artifact')
            guard()
    except Blocked:
        raise
    except (OSError,EOFError,ValueError) as exc:
        raise Blocked('INCOMPLETE_OR_INVALID_SOURCE: '+str(exc)) from exc
    desc={'status':'VERIFIED_IMMUTABLE','adapter_version':VERSION,'contract_version':'1.0.0',
          'source_id':source_id,'dataset_version':source['dataset_version'],
          'source_sha256':source['retrieval']['sha256'],
          'license_id':source['license']['id'],
          'license_sha256':source['license']['evidence_sha256'],
          'review_sha256':source['review']['evidence_sha256'],
          'registry_sha256':digest_file(root/'catalog/language_registry.v1.json'),
          'ledger_sha256':digest_file(root/'legal/ledger/sources.json'),
          'language':language,'source_rows':rows,'max_expanded':max_expanded}
    desc['snapshot_id']=stable('snapshot',desc)
    return desc


@contextmanager
def lock(path):
    if path.is_symlink():raise Blocked('UNSAFE_CHECKPOINT')
    path.parent.mkdir(parents=True,exist_ok=True)
    flags=os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW
    with os.fdopen(os.open(str(path)+'.lock',flags,0o600),'a+b') as handle:
        try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise Blocked('PARTITION_OWNED') from exc
        yield


def connect(path,identity):
    if path.is_symlink():raise Blocked('UNSAFE_CHECKPOINT')
    db=sqlite3.connect(path)
    db.execute('PRAGMA cache_size=-2048');db.execute('PRAGMA temp_store=FILE')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS lexemes(id TEXT PRIMARY KEY,logical_id TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS senses(id TEXT PRIMARY KEY,lexeme_id TEXT NOT NULL REFERENCES lexemes(id),payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS sense_lex ON senses(lexeme_id,id);
    CREATE TABLE IF NOT EXISTS evidence(line INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,raw TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS links(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review(line INTEGER PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS errors(line INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,code TEXT NOT NULL);
    ''')
    saved=db.execute("SELECT v FROM meta WHERE k='identity'").fetchone()
    if saved and saved[0]!=canonical(identity):
        db.close();raise Blocked('CHECKPOINT_IDENTITY_MISMATCH')
    if not saved:
        state={'input_rows':0,'owned_rows':0,'rejected_records':0,'duplicates':0,
               'review_records':0,'complete':False}
        db.executemany('INSERT INTO meta VALUES (?,?)',
                       [('identity',canonical(identity)),('state',canonical(state))]);db.commit()
    return db


def merge(db,result):
    lex=result['lexeme'];lid=lex['lexeme_id'];changed=False
    previous=db.execute('SELECT payload FROM lexemes WHERE id=?',(lid,)).fetchone()
    if previous:
        old=json.loads(previous[0]);m=old.setdefault('morphology',{})
        for field,value in lex.get('morphology',{}).items():
            if isinstance(value,list):
                bucket=m.setdefault(field,[])
                for item in value:
                    signature={k:v for k,v in item.items() if k!='source'} if isinstance(item,dict) else item
                    if not any((({k:v for k,v in previous.items() if k!='source'}) if isinstance(previous,dict) else previous)==signature for previous in bucket):
                        bucket.append(item);changed=True
                if len(bucket)>4096:raise Reject('OVERSIZED_MERGED_FORMS')
            elif field in m and m[field]!=value:raise Reject('CONFLICTING_MORPHOLOGY')
            elif field not in m:m[field]=value;changed=True
        sounds=old.setdefault('pronunciations',[])
        for item in lex.get('pronunciations',[]):
            if not any({k:v for k,v in previous.items() if k!='source'}=={k:v for k,v in item.items() if k!='source'} for previous in sounds):
                sounds.append(item);changed=True
        if len(sounds)>1024:raise Reject('OVERSIZED_MERGED_SOUNDS')
        if changed:
            payload=canonical(old)
            if len(payload.encode())>4*MAX_LINE:raise Reject('OVERSIZED_MERGED_LEXEME')
            db.execute('UPDATE lexemes SET payload=? WHERE id=?',(payload,lid))
    else:
        db.execute('INSERT INTO lexemes VALUES (?,?,?)',(lid,result['logical_identity'],canonical(lex)));changed=True
    for sense in result['senses']:
        # Existing ID is semantic equality; preserve every original line in evidence.
        if not db.execute('SELECT 1 FROM senses WHERE id=?',(sense['sense_id'],)).fetchone():
            db.execute('INSERT INTO senses VALUES (?,?,?)',(sense['sense_id'],lid,canonical(sense)));changed=True
    if db.execute('SELECT COUNT(*) FROM senses WHERE lexeme_id=?',(lid,)).fetchone()[0]>4096:
        raise Reject('OVERSIZED_MERGED_SENSES')
    for link in result['links']:
        db.execute('INSERT OR IGNORE INTO links VALUES (?,?)',(stable('link',link),canonical(link)))
    return changed


def receipt(db):
    state=json.loads(db.execute("SELECT v FROM meta WHERE k='state'").fetchone()[0])
    identity=json.loads(db.execute("SELECT v FROM meta WHERE k='identity'").fetchone()[0])
    return dict(state,identity=identity,
                accepted_lexemes=db.execute('SELECT COUNT(*) FROM lexemes').fetchone()[0],
                accepted_senses=db.execute('SELECT COUNT(*) FROM senses').fetchone()[0],
                status='LEXICAL_REVIEW_REQUIRED',publication_approved=False)


def process(repo_root,descriptor,checkpoint,*,shard=0,shards=1,limit=100000,batch_size=128,after_row=None):
    if type(limit) is not int or not 1<=limit<=100000 or type(batch_size) is not int or not 1<=batch_size<=1024:
        raise Blocked('INVALID_JOB_BOUND')
    partition('bounds',shards)
    if type(shard) is not int or not 0<=shard<shards:raise Blocked('INVALID_SHARD')
    root=Path(repo_root).resolve()
    expected=snapshot(root,descriptor['source_id'],descriptor['language'],descriptor['max_expanded'])
    if descriptor!=expected:raise Blocked('SNAPSHOT_DESCRIPTOR_MISMATCH')
    source,path,registry=approved(root,descriptor['source_id'],descriptor['language'])
    identity={'snapshot':descriptor,'shard':shard,'shards':shards,'adapter_version':VERSION}
    with lock(Path(checkpoint)):
        db=connect(Path(checkpoint),identity)
        try:
            state=json.loads(db.execute("SELECT v FROM meta WHERE k='state'").fetchone()[0])
            if state['complete']:return receipt(db)
            start=state['input_rows'];processed=0
            db.execute('BEGIN')
            with bound_bytes(path,descriptor['source_sha256']) as (handle,guard):
                for number,(raw,line_sha) in enumerate(lines(handle,descriptor['max_expanded']),1):
                    if number<=start:continue
                    owner=0
                    db.execute('SAVEPOINT record')
                    try:
                        if raw is None:raise Reject('OVERSIZED_ROW')
                        decoded=raw.decode('utf-8',errors='strict')
                        if decoded.startswith('\ufeff'):raise Reject('UTF8_BOM')
                        obj=strict_json(decoded)
                        result=extract(obj,source,registry,descriptor['language'],f'line:{number}')
                        owner=partition(result['lexeme']['lexeme_id'],shards)
                        if owner==shard:
                            changed=merge(db,result)
                            db.execute('INSERT INTO evidence VALUES (?,?,?)',(number,line_sha,decoded))
                            state['owned_rows']+=1
                            state['duplicates']+=int(not changed)
                            state['review_records']+=int(bool(result['review'] or result['links']))
                            if result['review']:
                                db.execute('INSERT INTO review VALUES (?,?)',(number,canonical(result['review'])))
                    except (Reject,UnicodeError,json.JSONDecodeError,RecursionError) as exc:
                        db.execute('ROLLBACK TO record')
                        # Parse/extraction failures belong to zero; merge conflicts
                        # belong to the already resolved lexeme partition.
                        if shard==owner:
                            code=str(exc) if isinstance(exc,Reject) else 'INVALID_JSON_OR_UNICODE'
                            db.execute('INSERT INTO errors VALUES (?,?,?)',(number,line_sha,code))
                            state['rejected_records']+=1;state['owned_rows']+=1
                    finally:db.execute('RELEASE record')
                    state['input_rows']=number;processed+=1
                    if after_row:after_row(processed) # test interruption seam; never exposed via CLI
                    if processed%batch_size==0:
                        guard()
                        db.execute("UPDATE meta SET v=? WHERE k='state'",(canonical(state),));db.commit();db.execute('BEGIN')
                    if processed>=limit:break
                state['complete']=state['input_rows']==descriptor['source_rows']
                guard()
                db.execute("UPDATE meta SET v=? WHERE k='state'",(canonical(state),));db.commit()
                return receipt(db)
        except BaseException:
            db.rollback();raise
        finally:db.close()


def export(checkpoint,out_dir):
    out=Path(out_dir).absolute()
    if out.exists() or out.is_symlink():raise Blocked('OUTPUT_EXISTS')
    if not Path(checkpoint).is_file():raise Blocked('CHECKPOINT_MISSING')
    with lock(Path(checkpoint)):
        db=sqlite3.connect(f'file:{Path(checkpoint).resolve()}?mode=ro',uri=True)
        stage=None
        try:
            result=receipt(db)
            if not result['complete']:raise Blocked('INCOMPLETE_PARTITION')
            out.parent.mkdir(parents=True,exist_ok=True)
            stage=Path(tempfile.mkdtemp(prefix='.ingestion-',dir=out.parent))
            with (stage/'lexical.jsonl').open('w',encoding='utf-8') as handle:
                for lid,payload in db.execute('SELECT id,payload FROM lexemes ORDER BY id'):
                    lex=json.loads(payload)
                    # One self-contained Route06 fragment per sense; bounded even for very polysemous lemmas.
                    for (sense,) in db.execute('SELECT payload FROM senses WHERE lexeme_id=? ORDER BY id',(lid,)):
                        doc={'contract_version':'1.0.0','document_id':stable('batch',lid,json.loads(sense)['sense_id']),
                             'lexemes':[lex],'senses':[json.loads(sense)],'translations':[],'examples':[],'relations':[]}
                        handle.write(canonical(doc)+'\n')
            for name,query in [('evidence.jsonl','SELECT line,sha256,raw FROM evidence ORDER BY line'),
                               ('errors.jsonl','SELECT line,sha256,code FROM errors ORDER BY line'),
                               ('review.jsonl','SELECT line,payload FROM review ORDER BY line'),
                               ('translation_review.jsonl','SELECT payload FROM links ORDER BY id')]:
                with (stage/name).open('w',encoding='utf-8') as handle:
                    for record in db.execute(query):
                        value=({'line':record[0],'codes':json.loads(record[1])} if name=='review.jsonl' else
                               json.loads(record[0]) if name=='translation_review.jsonl' else dict(zip(
                            ('line','sha256','raw') if name=='evidence.jsonl' else ('line','sha256','code'),record))
                               )
                        handle.write(canonical(value)+'\n')
            result['files']={p.name:digest_file(p) for p in sorted(stage.iterdir())}
            (stage/'receipt.json').write_text(canonical(result)+'\n',encoding='utf-8')
            os.rename(stage,out);stage=None
            return result
        finally:
            db.close()
            if stage:shutil.rmtree(stage)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,default=Path('.'))
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('snapshot');s.add_argument('--source-id',required=True);s.add_argument('--language',required=True)
    w=sub.add_parser('process');w.add_argument('--descriptor',type=Path,required=True);w.add_argument('--checkpoint',type=Path,required=True)
    w.add_argument('--shard',type=int,default=0);w.add_argument('--shards',type=int,default=1);w.add_argument('--limit',type=int,default=100000)
    e=sub.add_parser('export');e.add_argument('--checkpoint',type=Path,required=True);e.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    try:
        if args.command=='snapshot':result=snapshot(args.repo_root,args.source_id,args.language)
        elif args.command=='process':result=process(args.repo_root,load(args.descriptor),args.checkpoint,shard=args.shard,shards=args.shards,limit=args.limit)
        else:result=export(args.checkpoint,args.out)
        print(canonical(result));return 0
    except (Blocked,Reject,OSError,ValueError,KeyError,TypeError) as exc:
        print(canonical({'status':'BLOCKED_SOURCE_OR_DEPENDENCY','error':str(exc),'publication_approved':False}));return 2


if __name__=='__main__':raise SystemExit(main())
