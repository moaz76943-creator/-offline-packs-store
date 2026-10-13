"""Bounded authenticated GitHub REST transport."""
import os,json,time,urllib.request,urllib.error

class APIError(RuntimeError):
    def __init__(self,status,details):
        super().__init__(f'HTTP {status}: {details[:200]}')
        self.status=status

class Transport:
    def __init__(self,repo,token=None):
        if repo.count('/')!=1:
            raise ValueError('Expected owner/repo')
        self.root='https://api.github.com/repos/'+repo
        self.token=os.getenv('GITHUB_TOKEN','') if token is None else token

    def call(self,path,method='GET',body=None):
        if not path.startswith('/'):
            raise ValueError('Repository-relative API path required')
        headers={'Accept':'application/vnd.github+json',
                 'User-Agent':'deutsch-smart-pr-merge',
                 'X-GitHub-Api-Version':'2022-11-28'}
        if self.token:
            headers['Authorization']='Bearer '+self.token
        payload=json.dumps(body).encode() if body is not None else None
        if payload is not None:
            headers['Content-Type']='application/json'
        request=urllib.request.Request(self.root+path,headers=headers,
                                       data=payload,method=method)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request,timeout=18) as result:
                    raw=result.read(5_000_000)
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as err:
                details=err.read(1000).decode('utf-8','replace')
                limited=err.headers.get('Retry-After') or err.headers.get('X-RateLimit-Remaining')=='0'
                if attempt<2 and (err.code in (429,500,502,503,504) or (err.code==403 and limited)):
                    time.sleep(min(16,max(2**attempt,int(err.headers.get('Retry-After','0') or 0))))
                    continue
                raise APIError(err.code,details) from err
            except (TimeoutError,OSError) as err:
                if attempt==2:
                    raise APIError(0,str(err)) from err
                time.sleep(2**attempt)

    def pages(self,path,max_pages=3):
        result=[]
        for page in range(1,max_pages+1):
            sep='&' if '?' in path else '?'
            part=self.call(path+sep+f'per_page=100&page={page}')
            if not isinstance(part,list):
                raise APIError(0,'Invalid pagination')
            result.extend(part)
            if len(part)<100:
                return result
        raise APIError(0,'Inventory exceeds fixed pagination bound')
