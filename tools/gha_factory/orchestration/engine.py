"""Short serialized mutations, independently running worker jobs, fail-closed recovery."""
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from tools.gha_factory.admission import pipeline
from tools.gha_factory.dispatcher import controller as legacy, queue as v1, worker as legacy_worker
from . import protocol as p

REPO=legacy.REPO
OWNER=legacy.OWNER
WORKFLOW='.github/workflows/gha_dispatcher.yml'
CREATORS=frozenset((OWNER,'github-actions[bot]'))
MAX_CONTROLLER_BYTES=64*1024*1024

def trusted(issue):
    if not isinstance(issue,dict) or 'pull_request' in issue:
        return False
    user=issue.get('user')
    title=issue.get('title')
    number=issue.get('number')
    return (isinstance(user,dict) and user.get('login') in CREATORS
        and type(number) is int and number>0
        and isinstance(title,str) and title.startswith(p.PREFIX))

def inventory(api,ctx,invalid_active=None):
    entries=[]
    for issue in api.issues():
        if not trusted(issue):continue
        try:
            t=p.parse(issue.get('body'),ctx['languages'])
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            print('QUARANTINED_INVALID_ISSUE', issue['number'],
                  type(exc).__name__, file=sys.stderr)
            continue
        if issue['title']!=p.PREFIX+t['task_id']:
            print('QUARANTINED_INVALID_ISSUE', issue['number'],
                  'TitleIdentityMismatch', file=sys.stderr)
            if t['state'] not in p.ACTIVE:
                continue
            # A validated active lease retains its capacity and source/language
            # lock, even with a changed title. Never mutate or execute it.
            if invalid_active is not None:
                invalid_active.add(issue['number'])
        entries.append((issue['number'],t))
    if len(entries)>2000:raise ValueError('queue inventory exceeds 2000 tasks')
    return sorted(entries)

def source_gate(t,ctx,registry_sha,root):
    """Review metadata alone never authorizes work. Only bounded local pinned bytes.

    Large snapshots require the separately owned durable handoff adapter; do not
    download URLs or hash multi-gigabyte sources in a short queue controller.
    """
    if t['language'] not in ctx['languages']:return 'QUARANTINED'
    if t['task_type']=='registry_validate':
        return 'READY' if t['source_sha256']==registry_sha else 'QUARANTINED'
    matches=[s for s in ctx['sources'] if s.get('source_id')==t['source_id']]
    if len(matches)!=1:return 'BLOCKED_SOURCE'
    src=matches[0]
    if src.get('status')!='APPROVED_FOR_REDISTRIBUTION':return 'BLOCKED_SOURCE'
    retrieval=src.get('retrieval') or {}
    if retrieval.get('sha256')!=t['source_sha256']:return 'QUARANTINED'
    for section in (retrieval,src.get('review') or {}):
        # If expiry is declared it is enforced; no inferred expiry is invented.
        expiry=section.get('expires_at')
        if expiry is not None:
            try:
                if date.fromisoformat(expiry)<=date.today():return 'BLOCKED_SOURCE'
            except (TypeError,ValueError):return 'BLOCKED_SOURCE'
    if t['task_type'] not in p.EXECUTABLE:return 'BLOCKED_DEPENDENCY'
    key=(t['source_id'],t['language'],t['source_sha256'],t['shard'])
    approved=ctx.get('admissions',{}).get(key)
    if approved is None:return 'BLOCKED_SOURCE'
    relative=retrieval.get('artifact_path')
    evidence=(src.get('license') or {}).get('evidence_path')
    try:
        for rel in (relative,evidence):
            if not isinstance(rel,str) or Path(rel).is_absolute() or '..' in Path(rel).parts or '.git' in Path(rel).parts:return 'BLOCKED_SOURCE'
            path=(root/rel).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():return 'BLOCKED_SOURCE'
            if path.stat().st_size>MAX_CONTROLLER_BYTES:return 'BLOCKED_DEPENDENCY'
        path=(root/relative).resolve()
        pipeline.route05_source(root,t['source_id'],src['dataset_version'],path,'wiktextract-jsonl')
        report=approved['report'];job=approved['job']
        if report.get('dataset_version')!=src['dataset_version'] or report.get('source_artifact_sha256')!=t['source_sha256']:return 'QUARANTINED'
        partition_link=approved['folder']/job['path']
        if partition_link.is_symlink():return 'BLOCKED_SOURCE'
        partition=partition_link.resolve()
        if not partition.is_relative_to(approved['folder'].resolve()) or not partition.is_file():return 'BLOCKED_SOURCE'
        if partition.stat().st_size>40_000_000:return 'BLOCKED_DEPENDENCY'
        if pipeline.digest_file(partition)!=job['sha256']:return 'QUARANTINED'
    except (OSError,ValueError,KeyError,TypeError):return 'BLOCKED_SOURCE'
    return 'READY'

def _blocked(t,state):
    if t['schema_version']==v1.VERSION and state=='BLOCKED_DEPENDENCY':state='BLOCKED_SOURCE'
    return p.validate(dict(t,state=state))

def control(api,run_id,attempt,now,root,ctx=None,registry_sha=None,telemetry=None):
    if ctx is None:ctx,registry_sha=legacy.context(root)
    invalid_active=set()
    entries=inventory(api,ctx,invalid_active)
    if telemetry is not None:
        observed=Counter(t['state'] for _,t in entries)
        telemetry.update(queue_total=len(entries),
                         task_states=dict(sorted(observed.items())))
    groups=defaultdict(list)
    for n,t in entries:groups[t['task_id']].append((n,t))
    # Any duplicate is ambiguous: completed receipts are immutable; only incomplete
    # duplicate entries are quarantined. Source-ID collisions in v1 are not remapped.
    unique=[]
    for group in groups.values():
        if len(group)>1:
            for n,t in group:
                if t['state'] not in ('SUCCEEDED','QUARANTINED'):
                    if t['state'] in p.ACTIVE:raise ValueError('duplicate active ownership: fail closed')
                    api.update(n,dict(t,state='QUARANTINED'))
        else:unique.extend(group)
    completed={t['task_id'] for group in groups.values() if len(group)==1 for _,t in group if t['state']=='SUCCEEDED'}
    active=[];candidates=[];runs={};gates={};run_jobs={}
    source_entries=[(n,t) for n,t in sorted(unique) if t['state'] in ('NEW','READY','BLOCKED_SOURCE','BLOCKED_DEPENDENCY') and t['task_type']!='registry_validate']
    # Rotate bounded source inspection hourly so blocked old issues do not starve
    # later tasks. Registry-only checks are cheap and are not subject to this cap.
    width=5
    start=(int(now.timestamp()//3600)%max(1,(len(source_entries)+width-1)//width))*width
    examined={n for n,_ in source_entries[start:start+width]}
    for n,original in sorted(unique):
        t=original
        if t['state'] in p.ACTIVE:
            if len(active)>=32:raise ValueError('unexpected active lease count')
            if n in invalid_active:
                # Fail closed: reserve the slot and lock until title correction.
                active.append((n,t))
                continue
            if t['run_id'] not in runs:runs[t['run_id']]=api.run(t['run_id'])
            r=runs[t['run_id']]
            exact=(r.get('id')==t['run_id'] and r.get('run_attempt')==t['run_attempt']
                   and r.get('head_branch')=='main' and r.get('path')==WORKFLOW)
            # A still-live or unverifiable GH run owns its slot even after lease
            # expiry. Never replay on time alone, or after a changed run attempt.
            if (exact and r.get('status')=='completed' and t['lease_until'] is not None
                    and v1.date_value(t['lease_until'])<=now):
                t=p.fail(t,now)
            else:
                if exact and hasattr(api,'jobs'):
                    if t['run_id'] not in run_jobs:run_jobs[t['run_id']]=api.jobs(t['run_id'])
                    expected=f"worker ({n}, {t['task_id']})"
                    if any(j.get('name')==expected and j.get('status') in ('in_progress','completed') for j in run_jobs[t['run_id']]):
                        t=dict(t,state='RUNNING')
                active.append((n,t))
        if t['state']=='RETRY_WAIT' and v1.date_value(t['next_retry_at'])<=now:
            t=dict(t,state='NEW',next_retry_at=None)
        if t['state'] in ('NEW','READY','BLOCKED_SOURCE','BLOCKED_DEPENDENCY'):
            if t['attempts']>=p.MAX_ATTEMPTS:t=dict(t,state='FAILED')
            else:
                # A short controller examines at most five distinct source shards.
                key=(t['source_id'],t['source_sha256'],t['language'],t['shard'],t['task_type'])
                if key not in gates and (t['task_type']=='registry_validate' or n in examined):gates[key]=source_gate(t,ctx,registry_sha,root)
                if key in gates:
                    gate=gates[key]
                    deps=t.get('dependencies',[])
                    if gate=='READY' and (t['task_type'] not in p.EXECUTABLE or any(d not in completed for d in deps)):gate='BLOCKED_DEPENDENCY'
                    t=_blocked(t,gate)
                else:
                    # Untested READY metadata must not become runnable.
                    continue
        if t!=original:api.update(n,t)
        if t['state']=='READY':candidates.append((n,t))
    locks={(t['source_id'],t['language']) for _,t in active}
    slots=max(0,3-len(active));jobs=[]
    # Fresh first attempts precede retries, then oldest issue first. No fabricated
    # timestamp is added to immutable historical v1 task identities.
    for n,t in sorted(candidates,key=lambda x:(x[1]['attempts'],x[0])):
        if len(jobs)>=slots:break
        lock=(t['source_id'],t['language'])
        if lock in locks:continue
        reread=api.one(n)
        if not trusted(reread) or p.parse(reread['body'])!=t:continue
        claimed=p.claim(t,now,run_id,attempt)
        api.update(n,claimed)
        # Job-level shared concurrency in the workflow is the atomic exclusion
        # mechanism. GitHub Issues PATCH is not a compare-and-swap primitive.
        locks.add(lock);jobs.append({'number':n,'task_id':t['task_id']})
    return jobs

def seed(api,ctx,registry_sha,root):
    entries=inventory(api,ctx)
    known={t['task_id'] for _,t in entries};v1_known=set()
    for _,t in entries:
        if t['schema_version']==v1.VERSION:v1_known.add((t['source_id'],t['language'],t['source_sha256'],t['shard']))
    created=[];pending=[]
    for key in sorted(ctx.get('admissions',{})):
        sid,lang,digest,shard=key
        identity=p.new(sid,digest,lang,'approved_snapshot_verify',shard)['task_id']
        if identity not in known and key not in v1_known:pending.append(key)
    start=(int(v1.utc_now().timestamp()//3600)%max(1,(len(pending)+4)//5))*5
    for key in pending[start:start+5]:
        sid,lang,digest,shard=key
        t=p.new(sid,digest,lang,'approved_snapshot_verify',shard)
        if t['task_id'] in known or key in v1_known:continue
        if source_gate(t,ctx,registry_sha,root)!='READY':continue
        t=dict(t,state='READY');created.append(api.create(t));known.add(t['task_id'])
    return created

def strict_partition_row(raw):
    """Decode one bounded queue row without ambiguous JSON or invalid scalars."""
    def unique_object(pairs):
        item = {}
        for key, value in pairs:
            if key in item:
                raise ValueError('duplicate JSON property')
            item[key] = value
        return item

    def reject_constant(_value):
        raise ValueError('nonfinite JSON constant')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('overflowed JSON number')
        return number

    try:
        row = json.loads(raw.decode('utf-8', 'strict'),
                         object_pairs_hook=unique_object,
                         parse_constant=reject_constant,
                         parse_float=finite_float)
        # json.loads permits escaped lone UTF-16 surrogates. Never pass these
        # through as legitimate Arabic, German or other Unicode source text.
        pending = [row]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                value.encode('utf-8', 'strict')
        return row
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError('invalid partition JSON') from exc

def verify_partition(t,ctx):
    approved=ctx['admissions'][(t['source_id'],t['language'],t['source_sha256'],t['shard'])]
    job=approved['job'];report=approved['report']
    path=approved['folder']/job['path'];digest=hashlib.sha256();count=0
    with path.open('rb') as stream:
        while True:
            raw=stream.readline(1_048_577)
            if not raw:break
            if len(raw)>1_048_576 or not raw.endswith(b'\n'):raise ValueError('invalid partition line')
            count+=1
            if count>10000:raise ValueError('partition limit')
            digest.update(raw);row=strict_partition_row(raw)
            if (not isinstance(row,dict) or row.get('source_id')!=t['source_id']
                    or row.get('language')!=t['language'] or row.get('source_artifact_sha256')!=t['source_sha256']
                    or row.get('dataset_version')!=report['dataset_version']):raise ValueError('partition record identity mismatch')
    if count!=job['record_count'] or digest.hexdigest()!=job['sha256'] or count<t['checkpoint']:
        raise ValueError('partition content changed')
    return ('SUCCEEDED',count,0 if t['schema_version']==p.VERSION else count-t['checkpoint'],None,None)

def execute(api,n,task_id,run_id,attempt,directory,root,now):
    issue=api.one(n)
    if not trusted(issue):raise ValueError('untrusted issue')
    t=p.parse(issue['body'])
    if issue['title']!=p.PREFIX+task_id or t['task_id']!=task_id or t['state']!='CLAIMED' or t['run_id']!=run_id or t['run_attempt']!=attempt or v1.date_value(t['lease_until'])<=now:
        raise ValueError('worker lease mismatch')
    directory.mkdir(parents=True,exist_ok=True)
    try:
        ctx,sha=legacy.context(root)
        gate=source_gate(t,ctx,sha,root)
        if gate!='READY':result=('BLOCKED_SOURCE',t['checkpoint'],0,None,'SOURCE_NOT_APPROVED')
        elif t['task_type'] not in p.EXECUTABLE:raise ValueError('adapter not integrated')
        else:
            if t['task_type']=='registry_validate':
                result=legacy_worker.work(t,directory,root)
            else:result=verify_partition(t,ctx)
    except (OSError,ValueError,KeyError,TypeError):result=('FAILED',t['checkpoint'],0,None,'EXECUTION')
    r=p.receipt(t,*result)
    temp=directory/'receipt.tmp';temp.write_text(json.dumps(r,sort_keys=True,separators=(',',':')))
    temp.replace(directory/'receipt.json')
    return r

class FinalizationError(ValueError):
    """One or more tasks failed validation; independent results are durable."""
    def __init__(self, results, errors):
        super().__init__('one or more worker receipts could not be finalized')
        self.results = results
        self.errors = errors


def _finalize_job(api,job,folder,run_id,attempt,now):
    n=job['number'];issue=api.one(n)
    if not trusted(issue):raise ValueError('untrusted finalization issue')
    t=p.parse(issue['body'])
    if t['task_id']!=job['task_id'] or t['run_id']!=run_id or t['run_attempt']!=attempt:raise ValueError('changed ownership')
    directory=folder/f'dispatcher-{n}'
    # Never read a receipt or candidate through an extracted directory link.
    if directory.is_symlink() or directory.resolve().parent!=folder.resolve():
        raise ValueError('unsafe receipt directory')
    path=directory/'receipt.json'
    if path.is_symlink():raise ValueError('unsafe receipt')
    if path.is_file():
        if path.stat().st_size>4096:raise ValueError('oversized receipt')
        r=json.loads(path.read_text())
        if not isinstance(r, dict):
            raise ValueError('receipt must be a JSON object')
        p.verify_output(directory,r)
        updated=p.finish(t,r,now)
    else:
        if t['state'] not in p.ACTIVE:raise ValueError('missing receipt for completed task')
        updated=p.fail(t,now)
    if updated!=t:api.update(n,updated)
    return {'issue':n,'state':updated['state'],'task_id':t['task_id'],'run_id':run_id,'run_attempt':attempt}


def finalize(api,jobs,folder,run_id,attempt,now):
    if not isinstance(jobs,list) or len(jobs)>3:raise ValueError('invalid matrix')
    if folder.is_symlink():raise ValueError('unsafe artifact root')
    run=api.run(run_id)
    if run.get('id')!=run_id or run.get('run_attempt')!=attempt or run.get('head_branch')!='main' or run.get('path')!=WORKFLOW:raise ValueError('unverified run identity')
    # Reject an invalid matrix before performing any mutation. Receipt failures
    # below are per-task, while run identity remains a global security gate.
    for job in jobs:
        if not isinstance(job,dict) or set(job)!={'number','task_id'} or type(job['number']) is not int or job['number']<=0 or not v1.HEX.fullmatch(str(job['task_id'])):raise ValueError('invalid matrix item')
    done=[];errors=[]
    for job in jobs:
        try:
            done.append(_finalize_job(api,job,folder,run_id,attempt,now))
        except (OSError,ValueError,TypeError,KeyError) as exc:
            # Do not accept invalid/replayed receipts, release their leases, or
            # expose artifact contents. Continue finalizing independent tasks.
            errors.append({'issue':job['number'],'task_id':job['task_id'],
                           'error':'FINALIZATION_REJECTED','category':type(exc).__name__})
    if errors:raise FinalizationError(done,errors)
    return done
