"""Cross-run path claims with a Git fast-forward compare-and-swap backend.

An *optional companion* to private ScopeGuard, not a replacement. Scope claims are
only enforceable for integrations that explicitly call verify_pr before writing.
"""
import base64
import copy
import json
import re
import subprocess
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
_SHA = re.compile(r'^[a-f0-9]{40}$')
_REF = re.compile(r'^[A-Za-z0-9_./-]+$')
_STATE_PATH = 'tools/coordination/leases.json'
_LEASE_REF = 'coordination/leases'
_MAX_LEASES = 2000

class Denied(ValueError):
    """Expected closed-gate denial; safe to show as a reason code."""


def normalize_path(path):
    if not isinstance(path, str) or not path or len(path) > 512 or path != unicodedata.normalize('NFC',path):
        raise Denied('INVALID_PATH')
    if (path.startswith('/') or '\\' in path or '\x00' in path or '\n' in path
            or '\r' in path or any(ord(ch)<32 for ch in path)):
        raise Denied('UNSAFE_PATH')
    wildcard = path.endswith('/**')
    base = path[:-3] if wildcard else path
    if not base or any(seg in ('','.','..') for seg in base.split('/')) or '*' in base or '?' in base or '[' in base or ']' in base:
        raise Denied('UNSAFE_PATTERN')
    return base + ('/**' if wildcard else '')


def overlaps(a,b):
    a,b=normalize_path(a),normalize_path(b)
    ap=a[:-3] if a.endswith('/**') else a
    bp=b[:-3] if b.endswith('/**') else b
    return (ap==bp or (a.endswith('/**') and bp.startswith(ap+'/'))
            or (b.endswith('/**') and ap.startswith(bp+'/')))


def _identity(repo, branch, sha):
    if not isinstance(repo,str) or not _REPO.fullmatch(repo) or '..' in repo:
        raise Denied('INVALID_REPOSITORY')
    if not isinstance(branch,str) or not _REF.fullmatch(branch) or branch.startswith('/') or '..' in branch.split('/'):
        raise Denied('INVALID_BRANCH')
    if not isinstance(sha,str) or not _SHA.fullmatch(sha):
        raise Denied('INVALID_SHA')


def _validate_state(state):
    if (not isinstance(state,dict) or state.get('schema')!=1 or not isinstance(state.get('leases'),dict)
            or len(state['leases'])>_MAX_LEASES or not isinstance(state.get('events'),list)):
        raise Denied('INVALID_LEDGER_SCHEMA')
    if len(state['events'])>128:
        raise Denied('LEDGER_TOO_LARGE')
    for key,lease in state['leases'].items():
        if (not isinstance(key,str) or not isinstance(lease,dict)
                or lease.get('task_id')!=key or lease.get('state') not in ('CLAIMED','RELEASED','RECOVERED')):
            raise Denied('INVALID_LEASE_RECORD')
        _identity(lease.get('repository'),lease.get('base_branch'),lease.get('base_head_sha'))
        if not isinstance(lease.get('paths'),list) or not lease['paths'] or len(lease['paths'])>64:
            raise Denied('INVALID_LEASE_PATHS')
        for p in lease['paths']:normalize_path(p)
        if (not isinstance(lease.get('lease_id'),str) or not re.fullmatch('[a-f0-9]{32}',lease['lease_id'])
                or not isinstance(lease.get('owner'),str) or not lease['owner']):
            raise Denied('INVALID_LEASE_IDENTITY')
        if not isinstance(lease.get('expires_at'),(int,float)):
            raise Denied('INVALID_LEASE_EXPIRY')


def _report(status,reason=None,**detail):
    data={'status':status}
    if reason:data['reason']=reason
    data.update(detail)
    return data


class Coordinator:
    """Pure lease state transitions backed by a revisioned store (CAS)."""
    def __init__(self,store,api,clock=time.time,actor='unspecified'):
        self.store=store
        self.api=api
        self.clock=clock
        self.actor=actor

    def inspect(self,repo,branch,paths):
        try:
            _identity(repo,branch,'0'*40)
            proposed=[normalize_path(p) for p in paths]
            if not proposed or len(proposed)>64:raise Denied('EMPTY_OR_OVERSIZED_SCOPE')
            _,state=self.store.snapshot();_validate_state(state)
            for lease in state['leases'].values():
                if lease['state']=='CLAIMED' and lease['repository']==repo:
                    if any(overlaps(a,b) for a in proposed for b in lease['paths']):
                        return _report('READ_ONLY','SCOPE_CONFLICT',task_id=lease['task_id'],lease_expires_at=lease['expires_at'])
            return _report('READY')
        except Denied as exc:return _report('BLOCKED',str(exc))

    def _commit(self,mutator):
        for _ in range(4):
            try:
                version,state=self.store.snapshot()
                _validate_state(state)
                result,new=mutator(copy.deepcopy(state))
                if new is None:return result
                _validate_state(new)
                if self.store.commit(version,new):return result
            except Denied as exc:return _report('BLOCKED',str(exc))
        return _report('BLOCKED','CAS_CONTENTION')

    @staticmethod
    def _record(state,kind,lease):
        state['events']=(state['events']+[{'type':kind,'task_id':lease['task_id'],
                'lease_id':lease['lease_id'],'at':lease['updated_at']}])[-128:]

    def claim(self,task_id,repo,branch,base_sha,paths,owner,ttl=900,pr=None,run_id=None,run_attempt=None):
        try:
            _identity(repo,branch,base_sha)
            if not isinstance(task_id,str) or not task_id or len(task_id)>128:
                raise Denied('INVALID_TASK_ID')
            if not isinstance(owner,str) or not owner or len(owner)>128:raise Denied('INVALID_OWNER')
            if type(ttl) is not int or not 60<=ttl<=3600:raise Denied('INVALID_TTL')
            if not isinstance(paths,list) or not 0<len(paths)<=64:raise Denied('INVALID_PATH_COUNT')
            paths=[normalize_path(p) for p in paths]
            if len(set(paths))!=len(paths):raise Denied('DUPLICATE_PATH')
            if pr is not None and (type(pr) is not int or pr<1):raise Denied('INVALID_PR')
            if (run_id is None)!=(run_attempt is None):raise Denied('INCOMPLETE_RUN_IDENTITY')
            if run_id is not None and (type(run_id) is not int or run_id<1 or type(run_attempt) is not int or run_attempt<1):
                raise Denied('INVALID_RUN_IDENTITY')
            if self.api.branch_head(repo,branch)!=base_sha:raise Denied('BASE_HEAD_STALE')
        except Denied as exc:return _report('BLOCKED',str(exc))
        def mutate(state):
            for lease in state['leases'].values():
                if lease['state']=='CLAIMED' and lease['repository']==repo and any(
                        overlaps(x,y) for x in paths for y in lease['paths']):
                    return _report('READ_ONLY','SCOPE_CONFLICT',conflicting_task=lease['task_id']),None
            prior=state['leases'].get(task_id)
            if prior and prior['state']=='CLAIMED':return _report('BLOCKED','TASK_ALREADY_CLAIMED'),None
            if len(state['leases'])>=_MAX_LEASES and prior is None:
                raise Denied('LEDGER_CAPACITY_REACHED')
            # Re-read the target branch inside each CAS cycle: HEAD movement invalidates approval.
            if self.api.branch_head(repo,branch)!=base_sha:return _report('BLOCKED','BASE_HEAD_STALE'),None
            now=self.clock();lid=uuid.uuid4().hex
            claim={'task_id':task_id,'repository':repo,'base_branch':branch,'base_head_sha':base_sha,
                'paths':paths,'owner':owner,'actor':self.actor,'lease_id':lid,'lease_ttl':ttl,
                'issued_at':now,'updated_at':now,'expires_at':now+ttl,'pr_number':pr,
                'run_id':run_id,'run_attempt':run_attempt,'state':'CLAIMED'}
            state['leases'][task_id]=claim
            self._record(state,'CLAIM',claim)
            return _report('CLAIMED',lease_id=lid,expires_at=claim['expires_at']),state
        return self._commit(mutate)

    def _owned(self,state,task_id,lid,owner):
        lease=state['leases'].get(task_id)
        if not lease or lease['state']!='CLAIMED' or lease['lease_id']!=lid or lease['owner']!=owner:
            raise Denied('LEASE_FENCING_MISMATCH')
        return lease

    def renew(self,task_id,lid,owner,ttl):
        if type(ttl) is not int or not 60<=ttl<=3600:return _report('BLOCKED','INVALID_TTL')
        def mutate(state):
            lease=self._owned(state,task_id,lid,owner)
            now=self.clock()
            if now>=lease['expires_at']:raise Denied('LEASE_EXPIRED')
            if self.api.branch_head(lease['repository'],lease['base_branch'])!=lease['base_head_sha']:
                raise Denied('BASE_HEAD_STALE')
            lease['updated_at']=now;lease['expires_at']=now+ttl;lease['lease_ttl']=ttl
            self._record(state,'RENEW',lease)
            return _report('RENEWED',lease_id=lid,expires_at=lease['expires_at']),state
        return self._commit(mutate)

    def release(self,task_id,lid,owner):
        def mutate(state):
            lease=self._owned(state,task_id,lid,owner)
            lease['state']='RELEASED';lease['updated_at']=self.clock()
            self._record(state,'RELEASE',lease)
            return _report('RELEASED',lease_id=lid),state
        return self._commit(mutate)

    def recover(self,task_id,lid):
        def mutate(state):
            lease=state['leases'].get(task_id)
            if not lease or lease['state']!='CLAIMED' or lease['lease_id']!=lid:
                raise Denied('LEASE_FENCING_MISMATCH')
            now=self.clock()
            if now<=lease['expires_at']:raise Denied('LEASE_STILL_ACTIVE')
            if (lease.get('run_id') is None or not self.api.terminated_run(
                    lease['repository'],lease['run_id'],lease['run_attempt'])):
                raise Denied('RECOVERY_REQUIRES_VERIFIED_TERMINATED_RUN')
            lease['state']='RECOVERED';lease['updated_at']=now
            self._record(state,'RECOVER',lease)
            return _report('RECOVERED',lease_id=lid),state
        return self._commit(mutate)

    def verify_pr(self,task_id,lid,owner,number,expected_head):
        try:
            _,state=self.store.snapshot();_validate_state(state)
            lease=self._owned(state,task_id,lid,owner)
            if self.clock()>=lease['expires_at']:raise Denied('LEASE_EXPIRED')
            if lease['pr_number']!=number:raise Denied('PR_ID_MISMATCH')
            if not isinstance(expected_head,str) or not _SHA.fullmatch(expected_head):raise Denied('INVALID_SHA')
            if self.api.branch_head(lease['repository'],lease['base_branch'])!=lease['base_head_sha']:
                raise Denied('BASE_HEAD_STALE')
            meta,files=self.api.pr_files(lease['repository'],number)
            if (meta.get('number')!=number or meta.get('base_ref')!=lease['base_branch']
                    or meta.get('head_sha')!=expected_head):raise Denied('PR_HEAD_OR_BASE_MISMATCH')
            if (not isinstance(files,list) or len(files)!=meta.get('changed_files') or len(files)>3000):
                raise Denied('INCOMPLETE_PR_FILE_LIST')
            seen=set()
            for file in files:
                if not isinstance(file,dict):raise Denied('INVALID_FILE_RECORD')
                changed=[normalize_path(file.get('filename'))]
                if file.get('status')=='renamed':changed.append(normalize_path(file.get('previous_filename')))
                if changed[0] in seen:raise Denied('DUPLICATE_PR_FILE')
                seen.add(changed[0])
                for path in changed:
                    if not any(overlaps(path,allowed) for allowed in lease['paths']):
                        raise Denied('PR_FILE_OUTSIDE_CLAIM')
            if self.api.branch_head(lease['repository'],lease['base_branch'])!=lease['base_head_sha']:
                raise Denied('BASE_HEAD_CHANGED_DURING_VALIDATION')
            # Caller must separately check merge gates and a fresh GitHub PR head before write.
            return _report('AUTHORIZED_SCOPE_ONLY',task_id=task_id,pr=number,head_sha=expected_head)
        except (Denied,KeyError,TypeError) as exc:return _report('BLOCKED',str(exc))


class GhApi:
    """GitHub CLI REST adapter: strict JSON, fixed endpoint templates, 20s read/write timeout."""
    def request(self,path,method='GET',body=None):
        args=['gh','api','--method',method,path]
        if body is not None:args+=['--input','-']
        try:
            proc=subprocess.run(args,input=json.dumps(body) if body is not None else None,
                text=True,capture_output=True,timeout=20,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:raise Denied('GH_API_UNAVAILABLE') from exc
        if proc.returncode!=0 or len(proc.stdout)>4_000_000:raise Denied('GH_API_DENIED_OR_UNAVAILABLE')
        try:return json.loads(proc.stdout)
        except ValueError as exc:raise Denied('GH_API_INVALID_JSON') from exc

    def branch_head(self,repo,branch):
        _identity(repo,branch,'0'*40)
        data=self.request(f'repos/{repo}/branches/{quote(branch,safe="")}')
        sha=data.get('commit',{}).get('sha')
        if not isinstance(sha,str) or not _SHA.fullmatch(sha):raise Denied('BRANCH_SHA_UNAVAILABLE')
        return sha

    def terminated_run(self,repo,run_id,attempt):
        data=self.request(f'repos/{repo}/actions/runs/{run_id}')
        return (data.get('id')==run_id and data.get('run_attempt')==attempt
                and data.get('repository',{}).get('full_name')==repo
                and data.get('status')=='completed')

    def pr_files(self,repo,number):
        data=self.request(f'repos/{repo}/pulls/{number}')
        head=data.get('head') or {};base=data.get('base') or {}
        meta={'number':data.get('number'),'head_sha':head.get('sha'),
              'base_ref':base.get('ref'),'changed_files':data.get('changed_files')}
        files=[]
        for page in range(1,32):
            part=self.request(f'repos/{repo}/pulls/{number}/files?per_page=100&page={page}')
            if not isinstance(part,list) or len(part)>100:raise Denied('INVALID_PR_FILE_RESPONSE')
            files.extend(part)
            if len(part)<100:break
        return meta,files


class GitRefStore:
    """A private-repository ledger, written via non-force Git fast-forward CAS."""
    def __init__(self,api,repository,ref=_LEASE_REF):
        if not isinstance(repository,str) or not _REPO.fullmatch(repository):
            raise Denied('INVALID_LEDGER_REPOSITORY')
        if ref!=_LEASE_REF:raise Denied('UNAPPROVED_LEDGER_REF')
        self.api=api;self.repo=repository;self.ref=ref
        info=api.request(f'repos/{repository}')
        if info.get('private') is not True:raise Denied('LEDGER_REPOSITORY_MUST_BE_PRIVATE')

    def _ref(self):
        value=self.api.request(f'repos/{self.repo}/git/ref/heads/{self.ref}')
        sha=value.get('object',{}).get('sha')
        if not isinstance(sha,str) or not _SHA.fullmatch(sha):raise Denied('INVALID_LEDGER_HEAD')
        return sha

    def snapshot(self):
        sha=self._ref()
        data=self.api.request(f'repos/{self.repo}/contents/{_STATE_PATH}?ref={quote(self.ref,safe="")}')
        try:
            raw=base64.b64decode(data['content'],validate=False)
            if len(raw)>1_500_000:raise Denied('LEDGER_TOO_LARGE')
            def distinct(pairs):
                obj={}
                for key,value in pairs:
                    if key in obj:raise Denied('DUPLICATE_LEDGER_KEY')
                    obj[key]=value
                return obj
            payload=json.loads(raw.decode('utf-8'),object_pairs_hook=distinct)
        except (KeyError,UnicodeError,ValueError) as exc:raise Denied('INVALID_LEDGER_CONTENTS') from exc
        _validate_state(payload)
        return sha,payload

    def commit(self,parent,state):
        _validate_state(state)
        raw=json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        if len(raw.encode('utf8'))>1_500_000:raise Denied('LEDGER_TOO_LARGE')
        try:
            base=self.api.request(f'repos/{self.repo}/git/commits/{parent}')
            tree=base['tree']['sha']
            blob=self.api.request(f'repos/{self.repo}/git/blobs',method='POST',
                body={'content':raw,'encoding':'utf-8'})['sha']
            new_tree=self.api.request(f'repos/{self.repo}/git/trees',method='POST',body={
                'base_tree':tree,'tree':[{'path':_STATE_PATH,'mode':'100644','type':'blob','sha':blob}]})['sha']
            new_commit=self.api.request(f'repos/{self.repo}/git/commits',method='POST',body={
                'message':'chore(coordination): rotate lease state [skip ci]',
                'tree':new_tree,'parents':[parent]})['sha']
            if not _SHA.fullmatch(new_commit):raise Denied('INVALID_NEW_COMMIT')
            # Two divergent children of the same parent: only one non-force PATCH may succeed.
            self.api.request(f'repos/{self.repo}/git/refs/heads/{self.ref}',method='PATCH',
                body={'sha':new_commit,'force':False})
            return True
        except Denied:
            # Fail closed: any GitHub write error is conservatively a lost CAS/unknown commit.
            return False


def bootstrap_private_store(api,repository):
    """One-time opt-in; does not run implicitly during claim/renew/verify."""
    store=GitRefStore.__new__(GitRefStore)
    if not isinstance(repository,str) or not _REPO.fullmatch(repository):raise Denied('INVALID_REPOSITORY')
    info=api.request(f'repos/{repository}')
    if info.get('private') is not True:raise Denied('LEDGER_REPOSITORY_MUST_BE_PRIVATE')
    parent=api.branch_head(repository,'staging/v2-full-platform')
    base=api.request(f'repos/{repository}/git/commits/{parent}')
    raw=json.dumps({'schema':1,'leases':{},'events':[]},separators=(',',':'))
    blob=api.request(f'repos/{repository}/git/blobs',method='POST',body={'content':raw,'encoding':'utf-8'})['sha']
    tree=api.request(f'repos/{repository}/git/trees',method='POST',body={'base_tree':base['tree']['sha'],
           'tree':[{'path':_STATE_PATH,'mode':'100644','type':'blob','sha':blob}]})['sha']
    commit=api.request(f'repos/{repository}/git/commits',method='POST',body={
        'message':'chore(coordination): initialize private lease registry [skip ci]',
        'tree':tree,'parents':[parent]})['sha']
    api.request(f'repos/{repository}/git/refs',method='POST',body={
        'ref':f'refs/heads/{_LEASE_REF}','sha':commit})
    return commit
