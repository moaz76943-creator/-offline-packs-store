"""Finite, fixed GitHub endpoints only; never issue-controlled API destinations."""
import json
import os
import re
import urllib.request
from . import engine, protocol

class GitHub:
    def __init__(self,token=None):
        self.token=token or os.environ['GITHUB_TOKEN']
        if not self.token:raise ValueError('missing token')
        self.base='https://api.github.com/repos/'+engine.REPO
    def request(self,path,body=None,method='GET'):
        read=(re.fullmatch(r'/issues\?state=all&per_page=100&page=([1-9]|1[0-9]|2[01])',path)
            or re.fullmatch(r'/issues/[1-9][0-9]{0,9}',path)
            or re.fullmatch(r'/actions/runs/[1-9][0-9]{0,19}(?:/jobs\?per_page=100)?',path))
        write=(method=='PATCH' and re.fullmatch(r'/issues/[1-9][0-9]{0,9}',path)) or (method=='POST' and path=='/issues')
        if (method=='GET' and not read) or (method!='GET' and not write):raise ValueError('unsafe endpoint')
        if method!='GET' and (os.getenv('GITHUB_REPOSITORY')!=engine.REPO or os.getenv('GITHUB_REF')!='refs/heads/main'):
            raise ValueError('main-only write protection')
        data=None if body is None else json.dumps(body,separators=(',',':')).encode()
        if data is not None and len(data)>12500:raise ValueError('oversized write')
        req=urllib.request.Request(self.base+path,data=data,method=method,headers={
            'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','User-Agent':'public-orchestration-v2'})
        with urllib.request.urlopen(req,timeout=20) as response:raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('oversized response')
        return json.loads(raw)
    def issues(self):
        for page in range(1,22):
            items=self.request(f'/issues?state=all&per_page=100&page={page}')
            if not isinstance(items,list):raise ValueError('bad issue inventory')
            if page==21 and items:raise ValueError('more than 2000 issues: compact/archive controller inventory required')
            yield from items
            if len(items)<100:return
    def one(self,n):return self.request(f'/issues/{n}')
    def run(self,n):return self.request(f'/actions/runs/{n}')
    def jobs(self,n):
        result=self.request(f'/actions/runs/{n}/jobs?per_page=100')
        if not isinstance(result.get('jobs'),list) or result.get('total_count',0)>100:raise ValueError('oversized job inventory')
        return result['jobs']
    def update(self,n,t):return self.request(f'/issues/{n}',{'body':protocol.serialize(t)},'PATCH')
    def create(self,t):
        if t['schema_version']!=protocol.VERSION or t['state']!='READY' or t['task_type']!='approved_snapshot_verify':raise ValueError('unsafe seed')
        body={'title':protocol.PREFIX+t['task_id'],'body':protocol.serialize(t)}
        result=self.request('/issues',body,'POST')
        if result.get('title')!=body['title'] or result.get('body')!=body['body'] or not engine.trusted(result):raise ValueError('unverified issue creation')
        return result['number']
