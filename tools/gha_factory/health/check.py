#!/usr/bin/env python3
"""Advisory, read-only GHA issue queue health check. Never mutates queue state."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = 'moaz76943-creator/-offline-packs-store'
OWNER = REPO.split('/')[0]
ENVELOPE = re.compile(r'\A```gha-task-v1\n([^`]{1,11000})\n```\Z')
VALID_STATES = {'NEW','READY','CLAIMED','RUNNING','SUCCEEDED','FAILED','RETRY_WAIT','BLOCKED_SOURCE','QUARANTINED'}
MAX_ISSUES = 600
MAX_RUNS = 100


def parse_task(issue):
    if not isinstance(issue,dict):
        return None
    if ('pull_request' in issue or not str(issue.get('title','')).startswith('[GHA-TASK] ')
            or (issue.get('user') or {}).get('login') != OWNER):
        return None
    body = issue.get('body') or ''
    if not isinstance(body, str) or len(body.encode('utf-8')) > 12000:
        raise ValueError('invalid task body length')
    m = ENVELOPE.fullmatch(body)
    if not m:
        raise ValueError('invalid task envelope')
    task = json.loads(m.group(1))
    if not isinstance(task, dict) or task.get('schema_version') != '1.0':
        raise ValueError('invalid task schema')
    if task.get('state') not in VALID_STATES or not re.fullmatch(r'[a-f0-9]{64}', str(task.get('task_id',''))):
        raise ValueError('invalid task identity/state')
    if issue.get('title') != '[GHA-TASK] '+task['task_id']:
        raise ValueError('unmatched issue identity')
    for name in ('run_id','run_attempt'):
        value = task.get(name)
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError('invalid worker identity')
    return task


def date_utc(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value):
        raise ValueError('invalid UTC date')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def assess(issues, workflow_runs, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(issues,list) or len(issues)>MAX_ISSUES or not isinstance(workflow_runs,list) or len(workflow_runs)>MAX_RUNS:
        raise ValueError('unbounded GitHub issue/workflow page')
    runs={}
    for run in workflow_runs:
        if isinstance(run,dict) and type(run.get('id')) is int and type(run.get('run_attempt')) is int:
            runs[(run['id'],run['run_attempt'])]=run
    seen=set(); states=Counter(); alerts=[]; number=0
    for issue in issues:
        try:
            t=parse_task(issue)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as e:
            if isinstance(issue,dict) and (issue.get('title') or '').startswith('[GHA-TASK] '):
                alerts.append({'issue':issue.get('number'),'severity':'UNKNOWN','reason':'INVALID_TASK_EVIDENCE'})
            continue
        if t is None:
            continue
        number+=1; key=t['task_id']; state=t['state']; states[state]+=1
        if key in seen:
            alerts.append({'issue':issue.get('number'),'severity':'REVIEW','reason':'DUPLICATE_TASK_ID'})
        seen.add(key)
        if state in ('RUNNING','CLAIMED'):
            lease=t.get('lease_until')
            try:
                expired= date_utc(lease) <= now
            except (ValueError,TypeError):
                alerts.append({'issue':issue.get('number'),'severity':'UNKNOWN','reason':'INVALID_LEASE'});continue
            if expired:
                run=runs.get((t.get('run_id'),t.get('run_attempt')))
                status=run.get('status') if run else None
                # Expired lease alone never proves the worker died. No automatic state edits.
                reason='EXPIRED_LEASE_RUN_COMPLETED' if status=='completed' else 'EXPIRED_LEASE_RUN_ACTIVE' if status in ('queued','in_progress','waiting','pending','requested') else 'EXPIRED_LEASE_RUN_UNKNOWN'
                alerts.append({'issue':issue.get('number'),'severity':'REVIEW','reason':reason})
        if state=='RETRY_WAIT' and t.get('attempts',0)>=3:
            alerts.append({'issue':issue.get('number'),'severity':'REVIEW','reason':'RETRY_LIMIT_INSPECT'})
    return {'status':'OBSERVED_ONLY','queue_issues':number,'states':dict(states),'alerts':alerts,
            'supported_merged_task_types':['registry_validate','admission_partition_verify'],
            'production_lexical_workers_verified':False,'note':'No worker is restarted or marked dead based on this report.'}


def gh_get(path):
    if not re.fullmatch(r'/repos/moaz76943-creator/-offline-packs-store/(?:issues\?state=open&per_page=100&page=[1-6]|actions/workflows/gha_dispatcher.yml/runs\?per_page=100)',path):
        raise ValueError('unsafe path')
    cmd=['gh','api',path]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=25,check=False)
    if p.returncode or len(p.stdout)>12_000_000:
        raise RuntimeError('GitHub API unavailable or oversized')
    return json.loads(p.stdout)


def live():
    issues=[]
    for page in range(1,7):
        entries=gh_get(f'/repos/{REPO}/issues?state=open&per_page=100&page={page}')
        if not isinstance(entries,list):raise ValueError('GitHub issue listing malformed')
        issues.extend(entries)
        if len(entries)<100: break
        if page==6:raise ValueError('issue scan bound reached')
    runs=gh_get(f'/repos/{REPO}/actions/workflows/gha_dispatcher.yml/runs?per_page=100')
    if not isinstance(runs,dict):raise ValueError('workflow listing malformed')
    return issues,runs.get('workflow_runs',[])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,help='Offline JSON containing issues and workflow_runs')
    p.add_argument('--output',type=Path)
    a=p.parse_args(argv)
    try:
        if a.snapshot:
            obj=json.loads(a.snapshot.read_text(encoding='utf-8'))
            issues,runs=obj['issues'],obj['workflow_runs']
        else:
            issues,runs=live()
        result=assess(issues,runs)
        code=0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,subprocess.TimeoutExpired) as err:
        result={'status':'UNKNOWN','reason':type(err).__name__,'queue_issues':None};code=2
    data=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(data,encoding='utf-8')
    print(data,end='')
    return code

if __name__=='__main__':
    sys.exit(main())
