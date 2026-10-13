"""GitHub-native serialized controller. Issues are the durable task ledger."""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import queue

ROOT = Path(__file__).resolve().parents[3]
REPO = 'moaz76943-creator/-offline-packs-store'
OWNER = REPO.split('/')[0]


class GitHub:
    """Only the documented, fixed GitHub Issue GET/PATCH endpoints are used."""
    def __init__(self, token=None, repo=REPO):
        if repo != REPO:
            raise ValueError('dispatcher repository mismatch')
        self.token = token if token is not None else os.environ['GITHUB_TOKEN']
        if not self.token:
            raise ValueError('missing GitHub token')
        self.base = f'https://api.github.com/repos/{repo}'

    def request(self, path, patch=None):
        if not re.fullmatch(r'/issues(?:\?state=open&per_page=100&page=[1-6]|/[1-9][0-9]{0,9})',path):
            raise ValueError('unsafe GitHub API path')
        data = None if patch is None else json.dumps(patch,separators=(',',':')).encode()
        request = urllib.request.Request(self.base+path, data=data, method='PATCH' if patch is not None else 'GET',
            headers={'Authorization':'Bearer '+self.token, 'Accept':'application/vnd.github+json',
                     'X-GitHub-Api-Version':'2022-11-28','User-Agent':'public-queue-controller'})
        with urllib.request.urlopen(request,timeout=25) as response:
            raw = response.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError('oversized GitHub response')
        return json.loads(raw)

    def issues(self):
        for page in range(1,7):
            items = self.request(f'/issues?state=open&per_page=100&page={page}')
            if not isinstance(items,list):
                raise ValueError('invalid issue listing')
            for issue in items:
                if ('pull_request' not in issue and issue.get('title','').startswith(queue.PREFIX)
                        and (issue.get('user') or {}).get('login') == OWNER):
                    yield issue
            if len(items)<100:
                return
        raise RuntimeError('more than 600 open issues: manual queue partition required')

    def update(self,number,t):
        queue.validate(t)
        self.request(f'/issues/{int(number)}',{'body':queue.serialize(t)})

    def one(self,number):
        return self.request(f'/issues/{int(number)}')


def context(root=ROOT):
    registry_bytes=(root/'catalog/language_registry.v1.json').read_bytes()
    registry=json.loads(registry_bytes)
    ledger=json.loads((root/'legal/ledger/sources.json').read_text(encoding='utf-8'))
    langs=[item['id'] for item in registry['languages']]
    if registry.get('schema_version')!='1.0.0' or len(langs)!=100 or len(set(langs))!=100 or ledger.get('schema_version')!='1.0.0' or not isinstance(ledger.get('sources'),list):
        raise ValueError('canonical registry/admission ledger invalid')
    admissions={}
    base=root/'tools/gha_factory/admission/accepted'
    if base.is_dir():
        batches=sorted(base.iterdir())
        if len(batches)>300:
            raise ValueError('admission output inventory exceeds safe bound')
        for batch in batches:
            if batch.is_symlink() or not batch.is_dir():
                continue
            manifest=batch/'queue.json'
            if not manifest.is_file() or manifest.stat().st_size>2_000_000:
                continue
            report=json.loads(manifest.read_text(encoding='utf-8'))
            if (report.get('schema_version')!='1.0.0' or report.get('status')!='ACCEPTED_FOR_QUEUE'
                    or report.get('publication_approved') is not False or not isinstance(report.get('jobs'),list)
                    or len(report['jobs'])>200):
                continue
            for job in report['jobs']:
                if not isinstance(job,dict):continue
                i=job.get('partition_index')
                if type(i) is not int or i<0 or i>=100000:continue
                if (job.get('source_id')!=report.get('source_id') or job.get('language')!=report.get('language')
                        or job.get('dataset_version')!=report.get('dataset_version')
                        or job.get('category')!='dictionary' or job.get('path')!=f'partition-{i:08d}.jsonl'
                        or type(job.get('record_count')) is not int or not (1<=job['record_count']<=queue.MAX_PARTITION_RECORDS)
                        or not queue.HEX.fullmatch(str(job.get('sha256','')))):
                    continue
                key=(job['source_id'],job['language'],report.get('source_artifact_sha256'),i)
                if key in admissions:raise ValueError('duplicate immutable admitted partition identity')
                admissions[key]={'folder':batch,'job':job,'report':report}
    return ({'languages':frozenset(langs),'sources':ledger['sources'],'admissions':admissions},hashlib.sha256(registry_bytes).hexdigest())


def advance(task,now,ctx,registry_sha):
    old=task
    if old['state'] in ('RUNNING','CLAIMED'):
        task=queue.recover(old,now)
    if task['state']=='RETRY_WAIT' and queue.date_value(task['next_retry_at'])<=now:
        task=dict(task,state='READY',next_retry_at=None)
    if task['state'] in ('NEW','READY','BLOCKED_SOURCE'):
        gate=queue.admission(task,ctx,registry_sha)
        if gate!=task['state']:
            task=dict(task,state=gate)
    return queue.validate(task,ctx['languages'])


def controller(api,run_id,run_attempt,now=None,root=ROOT):
    now=now or queue.utc_now()
    ctx,sha=context(root)
    entries=[]
    for issue in api.issues():
        try:
            t=queue.parse(issue.get('body'),ctx['languages'])
        except (ValueError,TypeError,KeyError,UnicodeError,json.JSONDecodeError):
            # No untrusted metadata is executed; issue requires manual correction.
            print('QUARANTINED_INVALID_ISSUE',issue['number'],file=sys.stderr)
            continue
        entries.append((issue['number'],t))
    invalid=queue.duplicates(entries)
    candidates=[]
    locks=set()
    active=0
    for number,t in sorted(entries):
        if number in invalid:
            if t['state']!='QUARANTINED':api.update(number,dict(t,state='QUARANTINED'))
            continue
        updated=advance(t,now,ctx,sha)
        if updated!=t:api.update(number,updated)
        if updated['state'] in ('RUNNING','CLAIMED'):
            active += 1
            locks.add((updated['source_id'],updated['language']))
        candidates.append((number,updated))
    selected=queue.choose(candidates,locks,max(0,3-active))
    jobs=[]
    for number,t in selected:
        claimed=queue.claim(t,now,run_id,run_attempt)
        api.update(number,claimed)
        jobs.append({'number':number,'task_id':t['task_id']})
    return jobs


def finish(api,jobs,artifact_dir,run_id,run_attempt,now=None):
    now=now or queue.utc_now()
    if not isinstance(jobs,list) or len(jobs)>3:
        raise ValueError('invalid matrix size')
    done=[]
    for job in jobs:
        if not isinstance(job,dict) or set(job)!={'number','task_id'} or type(job['number']) is not int or not queue.HEX.fullmatch(str(job['task_id'])):
            raise ValueError('invalid matrix job')
        number=job['number']
        issue=api.one(number)
        if (issue.get('user') or {}).get('login')!=OWNER or not issue.get('title','').startswith(queue.PREFIX):
            raise ValueError('untrusted task ownership')
        t=queue.parse(issue['body'])
        if t['task_id']!=job['task_id'] or t['run_id']!=run_id or t['run_attempt']!=run_attempt:
            raise ValueError('task lease/run changed after dispatch')
        folder=Path(artifact_dir)/f'dispatcher-{number}'
        path=folder/'receipt.json'
        receipt=None
        if path.is_file() and path.stat().st_size<=4096:
            receipt=json.loads(path.read_text(encoding='utf-8'))
            if receipt.get('candidate_sha256') is not None:
                candidate=folder/'candidates.jsonl'
                if not candidate.is_file() or candidate.stat().st_size>500_000 or hashlib.sha256(candidate.read_bytes()).hexdigest()!=receipt['candidate_sha256']:
                    raise ValueError('candidate artifact digest mismatch')
        if receipt is not None and t['state']=='CLAIMED':
            t=dict(t,state='RUNNING')
            api.update(number,t)  # evidence of actual worker execution
        updated=queue.finalize(t,receipt,now)
        api.update(number,updated)
        done.append({'issue':number,'task_id':t['task_id'],'state':updated['state'],'run_id':run_id,'run_attempt':run_attempt})
    return done
