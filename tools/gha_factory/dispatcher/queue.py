"""Fail-closed GitHub-Issue task schema and pure queue transitions (stdlib only)."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

VERSION = '1.0'
CONTRACT = '1.0.0'
PREFIX = '[GHA-TASK] '
MARKER = '```gha-task-v1\n'
STATES = frozenset(('NEW','READY','CLAIMED','RUNNING','SUCCEEDED','FAILED',
                    'RETRY_WAIT','BLOCKED_SOURCE','QUARANTINED'))
FIELDS = frozenset(('schema_version','task_id','source_sha256','source_id','language',
                    'task_type','shard','contract_version','state','attempts',
                    'next_retry_at','lease_until','run_id','run_attempt','checkpoint','receipt'))
TASK_TYPES = frozenset((
    'registry_validate',
    'admission_partition_verify',
    'lexical_partition',
    'examples_partition',
    'release_candidate_qa',
))
HEX = re.compile(r'^[0-9a-f]{64}$')
SOURCE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,100}$')
LANG = re.compile(r'^[a-z]{2,3}$')
MAX_PARTITION_RECORDS = 10000
MAX_ATTEMPTS = 3
LEASE_MINUTES = 330


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def date_value(value):
    if value is None:
        return None
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value):
        raise ValueError('invalid timestamp')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def fingerprint(t):
    key = {k:t[k] for k in ('source_sha256','language','task_type','shard','contract_version')}
    raw = json.dumps(key,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def validate(t, language_ids=None):
    if not isinstance(t,dict) or set(t)!=FIELDS or t['schema_version']!=VERSION or t['contract_version']!=CONTRACT:
        raise ValueError('unknown task schema or fields')
    if not isinstance(t['source_sha256'],str) or not HEX.fullmatch(t['source_sha256']):
        raise ValueError('invalid source fingerprint')
    if not isinstance(t['source_id'],str) or not SOURCE.fullmatch(t['source_id']):
        raise ValueError('invalid source ID')
    if not isinstance(t['language'],str) or not LANG.fullmatch(t['language']):
        raise ValueError('invalid language')
    if language_ids is not None and t['language'] not in language_ids:
        raise ValueError('unknown canonical language')
    if t['task_type'] not in TASK_TYPES:
        raise ValueError('unapproved task type or language')
    if t['task_type']=='registry_validate' and (t['source_id']!='public-registry' or t['shard']!=0):
        raise ValueError('wrong registry task identity')
    if t['task_type'] in ('admission_partition_verify', 'lexical_partition', 'examples_partition', 'release_candidate_qa') and t['source_id']=='public-registry':
        raise ValueError('wrong source type')
    if type(t['shard']) is not int or not (0<=t['shard']<100000):
        raise ValueError('invalid shard')
    if t['state'] not in STATES or type(t['attempts']) is not int or not (0<=t['attempts']<=MAX_ATTEMPTS):
        raise ValueError('invalid state/attempt count')
    if type(t['checkpoint']) is not int or not (0<=t['checkpoint']<=MAX_PARTITION_RECORDS):
        raise ValueError('invalid checkpoint')
    for k in ('next_retry_at','lease_until'):
        date_value(t[k])
    for k in ('run_id','run_attempt'):
        if t[k] is not None and (type(t[k]) is not int or t[k]<=0):
            raise ValueError('invalid workflow run identity')
    if (t['run_id'] is None)!=(t['run_attempt'] is None):
        raise ValueError('partial workflow run identity')
    if t['receipt'] is not None:
        if not isinstance(t['receipt'],dict) or len(json.dumps(t['receipt']))>2000:
            raise ValueError('invalid bounded receipt')
        if set(t['receipt'])!={'status','checkpoint','candidate_count','candidate_sha256','error_code'}:
            raise ValueError('unexpected receipt fields')
    if not HEX.fullmatch(str(t.get('task_id',''))) or t['task_id']!=fingerprint(t):
        raise ValueError('task identity differs from deterministic fingerprint')
    return t


def serialize(t):
    validate(t)
    return MARKER+json.dumps(t,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n```'


def parse(body,language_ids=None):
    if not isinstance(body,str) or len(body.encode('utf-8'))>12000 or not body.startswith(MARKER) or not body.endswith('\n```'):
        raise ValueError('invalid queue issue envelope')
    def reject_duplicate_keys(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError('duplicate JSON key in queue task envelope')
            values[key] = value
        return values

    t=json.loads(body[len(MARKER):-4], object_pairs_hook=reject_duplicate_keys)
    return validate(t,language_ids)


def duplicates(entries):
    seen=set(); bad=set()
    for number,t in sorted(entries):
        f=t['task_id']
        if f in seen:bad.add(number)
        else:seen.add(f)
    return bad


def admission(t, context, registry_sha):
    """Check canonical registry and currently approved, artifact-bound source evidence."""
    if t['language'] not in context['languages']:
        return 'QUARANTINED'
    if t['task_type']=='registry_validate':
        return 'READY' if t['source_sha256']==registry_sha else 'QUARANTINED'
    matches=[s for s in context['sources'] if s.get('source_id')==t['source_id']]
    if len(matches)!=1:return 'BLOCKED_SOURCE'
    src=matches[0]
    allowed_kinds = {'dictionary', 'lexical', 'examples', 'qa_evidence'}
    if src.get('kind') not in allowed_kinds or src.get('status')!='APPROVED_FOR_REDISTRIBUTION':
        return 'BLOCKED_SOURCE'
    retrieval=src.get('retrieval') or {}
    if retrieval.get('sha256')!=t['source_sha256']:
        return 'QUARANTINED'
    if not src.get('review') or not src.get('license') or not retrieval.get('artifact_path'):
        return 'BLOCKED_SOURCE'
    if (t['source_id'],t['language'],t['source_sha256'],t['shard']) not in context.get('admissions', {}):
        return 'BLOCKED_SOURCE'
    # The worker independently executes the Route 05 hash+proof verification.
    return 'READY'


def choose(entries,locks,slots=3):
    if not isinstance(slots,int) or not (0<=slots<=3):raise ValueError('invalid worker capacity')
    chosen=[]
    if slots==0:return chosen
    for number,t in sorted(entries):
        lock=(t['source_id'],t['language'])
        if t['state']=='READY' and lock not in locks:
            locks.add(lock);chosen.append((number,t))
        if len(chosen)>=slots:break
    return chosen


def backoff(t,now):
    result=dict(t)
    result['lease_until']=None
    if result['attempts']>=MAX_ATTEMPTS:
        result['state']='FAILED';result['next_retry_at']=None
    else:
        result['state']='RETRY_WAIT'
        result['next_retry_at']=iso(now+timedelta(minutes=30*2**(result['attempts']-1)))
    return validate(result)


def recover(t,now):
    if t['state'] not in ('CLAIMED','RUNNING') or date_value(t['lease_until']) is None or date_value(t['lease_until'])>now:
        return t
    # Delay is based on the elapsed lease deadline, not current polling time.
    return backoff(t,date_value(t['lease_until']))


def claim(t,now,run_id,run_attempt):
    if t['state']!='READY':raise ValueError('cannot claim non-ready task')
    result=dict(t,state='CLAIMED',attempts=t['attempts']+1,run_id=run_id,
                run_attempt=run_attempt,lease_until=iso(now+timedelta(minutes=LEASE_MINUTES)),
                next_retry_at=None)
    return validate(result)


def finalize(t,receipt,now):
    if t['state'] not in ('CLAIMED','RUNNING'):
        raise ValueError('task was not owned by active worker')
    if receipt is None:return backoff(t,now)
    expected={'schema_version','task_id','run_id','run_attempt','status','checkpoint','candidate_count','candidate_sha256','error_code'}
    if not isinstance(receipt,dict) or set(receipt)!=expected or receipt['schema_version']!=VERSION:
        raise ValueError('invalid receipt envelope')
    if receipt['task_id']!=t['task_id'] or receipt['run_id']!=t['run_id'] or receipt['run_attempt']!=t['run_attempt']:
        raise ValueError('wrong run receipt (replay rejected)')
    if receipt['status'] not in ('SUCCEEDED','FAILED','BLOCKED_SOURCE') or type(receipt['checkpoint']) is not int or receipt['checkpoint']<t['checkpoint'] or type(receipt['candidate_count']) is not int or not (0<=receipt['candidate_count']<=MAX_PARTITION_RECORDS):
        raise ValueError('invalid result counters')
    if receipt['candidate_sha256'] is not None and not HEX.fullmatch(str(receipt['candidate_sha256'])):
        raise ValueError('invalid candidate digest')
    if receipt['error_code'] is not None and receipt['error_code'] not in ('EXECUTION','SOURCE_NOT_APPROVED','SOURCE_CHANGED','INVALID_INPUT','TIMEOUT','INJECTED_FAILURE'):
        raise ValueError('unexpected error category')
    result=dict(t)
    result['receipt']={k:receipt[k] for k in ('status','checkpoint','candidate_count','candidate_sha256','error_code')}
    result['checkpoint']=receipt['checkpoint']
    result['lease_until']=None
    result['next_retry_at']=None
    if receipt['status']=='SUCCEEDED':result['state']='SUCCEEDED'
    elif receipt['status']=='BLOCKED_SOURCE':result['state']='BLOCKED_SOURCE'
    else:return backoff(result,now)
    return validate(result)
