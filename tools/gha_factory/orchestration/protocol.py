"""Versioned compact issue protocol. Existing v1 bytes and fingerprints stay intact."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from tools.gha_factory.dispatcher import queue as v1

VERSION = '2.0'
CONTRACT = '2.0.0'
MARKER = '```gha-task-v2\n'
PREFIX = v1.PREFIX
TYPES = frozenset(('registry_validate', 'admission_partition_verify',
    'approved_snapshot_verify', 'lexical_partition', 'morphology_partition',
    'sentence_partition', 'exercise_partition', 'examples_partition',
    'sqlite_candidate_qa', 'unicode_search_qa', 'security_fuzz_qa',
    'release_candidate_qa', 'release_evidence_verify'))
# Only independently integrated, audited adapters are executable. Other enum values
# are contracts, not claims of implementations or production readiness.
EXECUTABLE = frozenset(('registry_validate','admission_partition_verify','approved_snapshot_verify'))
STATES = v1.STATES | {'BLOCKED_DEPENDENCY'}
FIELDS = v1.FIELDS | {'dependencies'}
ACTIVE = frozenset(('CLAIMED','RUNNING'))
MAX_ATTEMPTS = 3
LEASE_MINUTES = 330

def fingerprint(t):
    if t.get('schema_version') == v1.VERSION:
        return v1.fingerprint(t)
    fields = ('schema_version','source_id','source_sha256','language','task_type',
              'shard','contract_version','dependencies')
    return hashlib.sha256(json.dumps({k:t[k] for k in fields},sort_keys=True,
        separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()

def validate(t, languages=None):
    if isinstance(t,dict) and t.get('schema_version') == v1.VERSION:
        v1.validate(t,languages)
        if any(type(t[k]) is bool for k in ('run_id','run_attempt','attempts','checkpoint','shard')):
            raise ValueError('boolean counter')
        return t
    if not isinstance(t,dict) or set(t)!=FIELDS or t['schema_version']!=VERSION or t['contract_version']!=CONTRACT:
        raise ValueError('unsupported v2 schema')
    if t['task_type'] not in TYPES or t['state'] not in STATES:
        raise ValueError('unknown worker/state')
    if not isinstance(t['source_id'],str) or not v1.SOURCE.fullmatch(t['source_id']):
        raise ValueError('invalid source ID')
    if not isinstance(t['source_sha256'],str) or not v1.HEX.fullmatch(t['source_sha256']):
        raise ValueError('invalid source digest')
    if not isinstance(t['language'],str) or not v1.LANG.fullmatch(t['language']) or (languages is not None and t['language'] not in languages):
        raise ValueError('unknown language')
    for key,low,high in [('attempts',0,MAX_ATTEMPTS),('checkpoint',0,10000),('shard',0,99999)]:
        if type(t[key]) is not int or not low<=t[key]<=high:raise ValueError('invalid counter')
    for key in ('run_id','run_attempt'):
        if t[key] is not None and (type(t[key]) is not int or t[key]<=0):raise ValueError('invalid run')
    if (t['run_id'] is None)!=(t['run_attempt'] is None):raise ValueError('partial run')
    for key in ('lease_until','next_retry_at'):v1.date_value(t[key])
    if t['state'] in ACTIVE and (t['lease_until'] is None or t['run_id'] is None or t['attempts']<1):
        raise ValueError('active lease absent')
    if t['state']=='RETRY_WAIT' and t['next_retry_at'] is None:raise ValueError('retry deadline absent')
    deps=t['dependencies']
    if not isinstance(deps,list) or len(deps)>32 or any(not isinstance(x,str) or not v1.HEX.fullmatch(x) for x in deps) or deps!=sorted(set(deps)):
        raise ValueError('invalid dependencies')
    if t['task_type']=='registry_validate' and (t['source_id']!='public-registry' or t['shard']!=0):raise ValueError('wrong registry identity')
    if t['task_type']!='registry_validate' and t['source_id']=='public-registry':raise ValueError('wrong source identity')
    if t['task_id']!=fingerprint(t) or not v1.HEX.fullmatch(str(t['task_id'])):raise ValueError('identity mismatch')
    if t['task_id'] in deps:raise ValueError('self dependency')
    if t['receipt'] is not None:
        if not isinstance(t['receipt'],dict) or set(t['receipt'])!={'status','checkpoint','candidate_count','candidate_sha256','error_code'}:
            raise ValueError('invalid compact receipt')
        if len(json.dumps(t['receipt']))>2000:raise ValueError('oversized receipt')
    return t

def new(source_id,digest,language,kind,shard,dependencies=()):
    t=dict(schema_version=VERSION,contract_version=CONTRACT,source_id=source_id,
        source_sha256=digest,language=language,task_type=kind,shard=shard,
        dependencies=sorted(dependencies),state='NEW',attempts=0,checkpoint=0,
        next_retry_at=None,lease_until=None,run_id=None,run_attempt=None,receipt=None)
    t['task_id']=fingerprint(t)
    return validate(t)

def _unique(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError('duplicate JSON key')
        result[k]=v
    return result

def parse(body,languages=None):
    if not isinstance(body,str) or len(body.encode())>12000 or not body.endswith('\n```'):
        raise ValueError('invalid task envelope')
    marker=next((m for m in (MARKER,v1.MARKER) if body.startswith(m)),None)
    if marker is None:raise ValueError('unknown envelope')
    t=json.loads(body[len(marker):-4],object_pairs_hook=_unique)
    if t.get('schema_version')!=(VERSION if marker==MARKER else v1.VERSION):raise ValueError('envelope/version mismatch')
    return validate(t,languages)

def serialize(t):
    validate(t)
    if t['schema_version']==v1.VERSION:return v1.serialize(t)
    return MARKER+json.dumps(t,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n```'

def claim(t,now,run_id,attempt):
    validate(t)
    if t['state']!='READY' or t['attempts']>=MAX_ATTEMPTS:raise ValueError('claim forbidden')
    return validate(dict(t,state='CLAIMED',attempts=t['attempts']+1,run_id=run_id,
        run_attempt=attempt,lease_until=v1.iso(now+timedelta(minutes=LEASE_MINUTES)),
        next_retry_at=None))

def fail(t,now):
    validate(t)
    exhausted=t['attempts']>=MAX_ATTEMPTS
    return validate(dict(t,state='FAILED' if exhausted else 'RETRY_WAIT',
        lease_until=None,next_retry_at=None if exhausted else
        v1.iso(now+timedelta(minutes=30*2**max(0,t['attempts']-1)))))

def receipt(t,status,checkpoint,count,digest,error):
    return dict(schema_version=t['schema_version'],task_id=t['task_id'],
        run_id=t['run_id'],run_attempt=t['run_attempt'],status=status,
        checkpoint=checkpoint,candidate_count=count,candidate_sha256=digest,error_code=error)

def finish(t,r,now):
    validate(t)
    fields={'schema_version','task_id','run_id','run_attempt','status','checkpoint','candidate_count','candidate_sha256','error_code'}
    if not isinstance(r,dict) or set(r)!=fields:raise ValueError('invalid receipt fields')
    for k in ('schema_version','task_id','run_id','run_attempt'):
        if type(r[k]) is not type(t[k]) or r[k]!=t[k]:raise ValueError('receipt replay')
    if r['status'] not in ('SUCCEEDED','FAILED','BLOCKED_SOURCE'):raise ValueError('invalid status')
    if type(r['checkpoint']) is not int or not t['checkpoint']<=r['checkpoint']<=10000 or type(r['candidate_count']) is not int or not 0<=r['candidate_count']<=10000:
        raise ValueError('invalid result counters')
    if r['candidate_sha256'] is not None and (not isinstance(r['candidate_sha256'],str) or not v1.HEX.fullmatch(r['candidate_sha256'])):raise ValueError('invalid output hash')
    if t['schema_version']==VERSION and r['candidate_count']>0 and r['candidate_sha256'] is None:raise ValueError('missing candidate digest')
    if r['error_code'] not in (None,'EXECUTION','SOURCE_NOT_APPROVED','SOURCE_CHANGED','INVALID_INPUT','TIMEOUT','INJECTED_FAILURE'):raise ValueError('invalid error code')
    compact={k:r[k] for k in ('status','checkpoint','candidate_count','candidate_sha256','error_code')}
    if t['state']=='SUCCEEDED':
        if t['receipt']==compact:return t
        raise ValueError('conflicting completion')
    if t['state'] not in ACTIVE or v1.date_value(t['lease_until'])<now:raise ValueError('lease expired/unowned')
    # Failed attempts never advance a non-durable partial checkpoint.
    if r['status']=='FAILED':return fail(t,now)
    return validate(dict(t,state=r['status'],receipt=compact,checkpoint=r['checkpoint'],lease_until=None,next_retry_at=None))

def verify_output(folder,r):
    digest=r.get('candidate_sha256')
    if digest is None:return
    p=Path(folder)/'candidates.jsonl'
    if p.is_symlink() or not p.is_file() or p.stat().st_size>500_000:raise ValueError('missing/oversized output')
    if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('tampered candidate')
